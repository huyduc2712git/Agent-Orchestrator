"""Jarvis orchestrator — hiện thực 6 phase từ docs/design.md.

Phase 1: Tiếp nhận (chat) -> Phase 2: Phân tích & lập kế hoạch (chia subtask chain)
-> Phase 3: Phân công (scheduler chạy agent) -> Phase 4: Theo dõi (event bus, không chờ)
-> Phase 5: QA + closure (verify độc lập) -> Phase 6: Ghi nhớ (memory + wiki).
"""
import json
import logging
import re

from .. import config, llm
from .. import git_ops
from ..agents.registry import AGENTS, WORKER_KEYS, roster_description
from ..agents.runtime import run_agent
from ..board import store
from ..board.models import Task
from ..links import default_registry, detect_links
from ..memory import store as memory
from .. import settings as app_settings

log = logging.getLogger("orchestrator")

PLANNING_PROMPT = """Bạn là Jarvis — chat orchestrator của một hệ thống multi-agent. Bạn KHÔNG tự code.

Đội hình agent chuyên môn:
{roster}

MEMORY (bài học/quyết định cũ):
{memory}

WIKI (kiến trúc, connections, features đã có):
{wiki}

BOARD hiện tại:
{board}

Lịch sử chat gần đây:
{history}

Người dùng vừa nhắn: "{message}"

Phân tích và trả về DUY NHẤT một JSON object (không giải thích thêm), theo một trong hai dạng:

1) Nếu tin nhắn là câu hỏi/trao đổi/hỏi tiến độ — KHÔNG cần tạo task mới:
{{"action": "reply", "message": "<trả lời tiếng Việt, dựa trên board/memory/wiki ở trên>"}}

2) Nếu tin nhắn là yêu cầu công việc cần thực thi:
{{"action": "plan",
  "reply": "<xác nhận ngắn gọn với người dùng: đã hiểu gì, sẽ chia việc thế nào>",
  "task": {{
    "title": "<tên task cha>",
    "description": "<mô tả đầy đủ yêu cầu>",
    "project": "<slug — BỎ QUA nếu có Active Project ở dưới, hệ thống sẽ gán>",
    "project_dir": "<path tuyệt đối nếu người dùng chỉ định, nếu không thì để chuỗi rỗng>"
  }},
  "subtasks": [
    {{"title": "...", "description": "<yêu cầu chi tiết + ràng buộc kỹ thuật, agent không được hỏi lại>",
      "agent": "<stark|banner|hawkeye|pepper>", "depends_on": [<index các subtask phải xong trước, tính từ 0>],
      "tags": []}}
  ]
}}

Active Project (nếu có): {active_project}
— Nếu Active Project khác rỗng: LUÔN dùng đúng slug đó, KHÔNG tạo project mới. Task mới nằm trong project đang chọn.
— Chỉ đề xuất project mới khi Active Project rỗng VÀ người dùng yêu cầu tạo project mới rõ ràng.

Link context (parser-registry đã quét tin nhắn):
{link_hints}

Quy tắc lập kế hoạch:
- Task nhỏ 1 bước -> 1 subtask cho đúng agent chuyên môn. Task phức tạp -> chia subtask chain có dependency.
- LUÔN có subtask QA cuối cùng gán cho hawkeye, depends_on toàn bộ subtask build. Mô tả phải gồm:
  * TỪNG acceptance criteria cụ thể (file, URL status 200, nội dung...)
  * Visual QA bắt buộc nếu có UI: Live URL, screenshot desktop+mobile, inspect_render
  * Nếu có dev server URL từ builder thì ghi rõ trong description QA
- Mô tả subtask phải đầy đủ context (steer message). Tuân thủ hướng dẫn Build/QA trong Link context ở trên (đưa nguyên văn URL, tags).
- Việc liên quan DB migration / security / deploy production: thêm tag tương ứng ("db-migration", "security", "deploy-prod") để hệ thống bắt buộc operator review.
- Trả lời người dùng ngay trong "reply" — không để họ chờ trong im lặng.
"""

CLOSURE_VERIFY_PROMPT = """Task cha: {title}
{description}

Các subtask và deliverable:
{deliverables}

QA verdict của Hawkeye:
{qa_verdict}

Live URL của project (orchestrator serve tĩnh): {preview_url}

Nhiệm vụ của bạn (Jarvis, final review — Phase 5): VERIFY ĐỘC LẬP, không tin lời khai suông.
Dùng tool kiểm tra thực tế: list_dir/read_file xem file có tồn tại và đúng nội dung không,
http_get Live URL ở trên (phải trả status=200 nếu là sản phẩm web). Kiểm tra ít nhất 2-3 điểm quan trọng nhất.
Sau khi kiểm tra, post_message một "Final Review" tổng hợp evidence chain (build -> QA -> verify),
ghi rõ "Live URL verified: <url> (status 200)" nếu đã check được.
Rồi trả lời text cuối: dòng đầu tiên là "VERDICT: APPROVED" hoặc "VERDICT: REJECTED", sau đó là lý do.
"""

MEMORY_PROMPT = """Task vừa hoàn thành:
- Tiêu đề: {title}
- Mô tả: {description}
- Kết quả: {summary}

Hãy trả về DUY NHẤT một JSON object:
{{"memory_entry": "<1-2 câu tiếng Việt: quyết định/pattern/bài học đáng nhớ cho task sau>",
  "feature_slug": "<slug ngắn cho wiki, hoặc chuỗi rỗng nếu không đáng ghi wiki>",
  "feature_doc": "<nội dung markdown mô tả feature: nó là gì, file ở đâu, chạy thế nào — hoặc chuỗi rỗng>"}}
"""


def _board_snapshot() -> str:
    tasks = store.list_tasks()
    if not tasks:
        return "(board trống)"
    lines = []
    for t in tasks[-30:]:
        parent = f" (con của {t.parent_id})" if t.parent_id else ""
        lines.append(f"{t.id} [{t.type}/{t.status}] {t.title} — {t.assignee or 'chưa gán'}{parent}")
    return "\n".join(lines)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "project"


async def handle_chat(user_message: str, project: str | None = None) -> None:
    """Phase 1 + 2: tiếp nhận, phân tích, lập kế hoạch, trả lời ngay.

    `project`: slug project đang chọn trên UI — task mới buộc gắn vào đây.
    """
    history = store.list_chat(limit=10)
    history_text = "\n".join(f"{m['role']}: {m['message'][:300]}" for m in history[:-1]) or "(chưa có)"

    active = (project or app_settings.active_project() or "").strip()
    detected_links = detect_links(user_message)
    link_hints = default_registry.planning_hints(detected_links)

    prompt = PLANNING_PROMPT.format(
        roster=roster_description(),
        memory=memory.read_memory()[-4000:],
        wiki=memory.read_wiki_summary(3000),
        board=_board_snapshot(),
        history=history_text,
        message=user_message.replace('"', "'"),
        active_project=active or "(chưa chọn — có thể tạo project mới nếu cần)",
        link_hints=link_hints,
    )

    try:
        planner = app_settings.resolve_llm(role="planner")
        raw = await llm.chat_text(
            [{"role": "user", "content": prompt}],
            model=planner["model"],
            base_url=planner["base_url"],
            api_key=planner["api_key"],
        )
        decision = llm.extract_json(raw)
    except Exception as e:
        log.exception("Planning failed")
        store.add_chat("jarvis", f"Xin lỗi, tôi gặp lỗi khi phân tích yêu cầu: {e}")
        return

    if decision.get("action") == "reply":
        store.add_chat("jarvis", decision.get("message", "(không có nội dung)"))
        return

    # action == plan: tạo task cha + subtask chain có dependency
    tinfo = decision.get("task", {})
    subtasks_info = decision.get("subtasks", [])
    if not tinfo.get("title") or not subtasks_info:
        store.add_chat("jarvis", decision.get("reply") or "Tôi chưa đủ thông tin để lập kế hoạch — bạn mô tả rõ hơn được không?")
        return

    # Ưu tiên project đang chọn trên UI; không tạo project mới mỗi lần chat
    if active:
        proj = app_settings.get_project(active) or app_settings.upsert_project(active)
        project_slug = proj["slug"]
        project_dir = proj.get("project_dir") or str(config.WORKSPACE_DIR / "projects" / project_slug)
    else:
        project_slug = tinfo.get("project") or _slug(tinfo["title"])
        project_dir = tinfo.get("project_dir") or str(config.WORKSPACE_DIR / "projects" / project_slug)
        app_settings.upsert_project(project_slug, name=project_slug, project_dir=project_dir)

    # GitHub/GitLab: clone vào project trước khi tạo subtask (parser-registry)
    git_link = next(
        (x for x in detected_links if x.get("type") in ("github", "gitlab") and x.get("clone_url")),
        None,
    )
    if not git_link:
        # fallback: link trong description plan
        git_link = default_registry.first_of_type(
            tinfo.get("description", ""), "github", "gitlab"
        )
    git_url = (git_link or {}).get("clone_url") or ""
    extra_tags: list[str] = []
    for link in detected_links:
        for t in link.get("tags") or []:
            if t not in extra_tags:
                extra_tags.append(t)

    git_note = ""
    if git_url:
        store.add_chat("jarvis", f"Đang chuẩn bị git repo `{git_url}` vào project `{project_slug}`…")
        clone = git_ops.ensure_clone(git_url, project_dir)
        if not clone.get("ok"):
            store.add_chat(
                "jarvis",
                f"Không clone được repo: {clone.get('error')}\n"
                "Repo private? Thêm Git token trong Settings, hoặc kiểm tra link.",
            )
            return
        project_dir = clone.get("path") or project_dir
        app_settings.upsert_project(project_slug, project_dir=project_dir)
        git_note = (
            f"\n\n[Git workspace]\n"
            f"- remote: {clone.get('remote')}\n"
            f"- path: {project_dir}\n"
            f"- branch: {clone.get('branch')}\n"
            f"- {clone.get('message')}\n"
            f"Làm việc TRÊN repo này. Dùng git_status để xác nhận. "
            f"Commit qua run_command khi xong (không force push)."
        )
        tinfo["description"] = (tinfo.get("description") or "") + git_note

    # Gắn steer từ từng link đã detect vào subtask
    for st in subtasks_info:
        agent = st.get("agent", "")
        tags = list(st.get("tags") or [])
        for t in extra_tags:
            if t not in tags:
                tags.append(t)
        steers = []
        for link in detected_links:
            if agent == "hawkeye" and link.get("steer_qa"):
                steers.append(link["steer_qa"])
            elif agent != "hawkeye" and link.get("steer_build"):
                steers.append(link["steer_build"])
        if steers:
            st["description"] = (st.get("description") or "") + "\n\n" + "\n".join(steers)
        st["tags"] = tags

    parent = store.create_task(
        title=tinfo["title"],
        description=tinfo.get("description", ""),
        project=project_slug,
        project_dir=project_dir,
        created_by="jarvis",
        tags=extra_tags,
    )
    store.set_status(parent.id, "in_progress", "jarvis")

    created: list[Task] = []
    for st in subtasks_info:
        agent = st.get("agent", "stark")
        if agent not in WORKER_KEYS:
            agent = "stark"
        sub = store.create_task(
            title=st.get("title", "Subtask"),
            description=st.get("description", ""),
            assignee=agent,
            project=project_slug,
            project_dir=project_dir,
            parent_id=parent.id,
            tags=st.get("tags", []),
            created_by="jarvis",
        )
        created.append(sub)
    for st, sub in zip(subtasks_info, created):
        for idx in st.get("depends_on", []):
            if isinstance(idx, int) and 0 <= idx < len(created) and created[idx].id != sub.id:
                store.add_dep(sub.id, created[idx].id, "blocks")

    store.add_event(
        parent.id, "jarvis", "comment",
        "Kế hoạch: " + "; ".join(f"{s.id}→{s.assignee}" for s in created),
    )

    plan_lines = "\n".join(
        f"- {s.id} → {AGENTS[s.assignee].display}: {s.title}" for s in created
    )
    reply = decision.get("reply", "Đã lập kế hoạch.")
    store.add_chat("jarvis", f"{reply}\n\nKế hoạch ({parent.id} — project `{project_slug}`):\n{plan_lines}")


# ---------- Phase 5: closure ----------

def _qa_verdict(parent_id: str) -> tuple[str, str]:
    """Lấy verdict QA từ các comment của hawkeye (mới nhất trước). Trả về (PASS|FAIL|UNKNOWN, text)."""
    subtasks = store.list_tasks(parent_id=parent_id)
    qa_tasks = [t for t in subtasks if t.assignee == "hawkeye"]
    newest_text = ""
    for qa in reversed(qa_tasks):
        for ev in reversed(store.list_events(qa.id)):
            if ev.agent != "hawkeye" or ev.kind != "comment":
                continue
            text = ev.message
            newest_text = newest_text or text
            up = text.upper()
            if re.search(r"VERDICT:\s*PASS", up):
                return "PASS", text
            if re.search(r"VERDICT:\s*FAIL", up):
                return "FAIL", text
            if "FAIL" in up and "PASS" not in up:
                return "FAIL", text
            if "PASS" in up:
                return "PASS", text
    if newest_text:
        return "UNKNOWN", newest_text
    return "UNKNOWN", "(chưa có báo cáo QA)"


def _open_related_bugs(parent: Task) -> list[Task]:
    bugs = store.list_tasks(type="bug", status=["backlog", "in_progress", "blocked"])
    return [b for b in bugs if b.project == parent.project]


MAX_FIX_ROUNDS = 2


def _fix_rounds(parent: Task) -> int:
    return sum(1 for t in parent.tags if t.startswith("fix-round"))


def _requeue_qa(qa: Task, mark_tag: str, reason: str, chat_msg: str) -> None:
    store.update_task_fields(qa.id, tags=[*qa.tags, mark_tag])
    store.set_status(qa.id, "in_progress", "jarvis")
    store.set_status(qa.id, "backlog", "jarvis")
    store.add_event(qa.id, "jarvis", "system", reason)
    store.add_chat("jarvis", chat_msg)


async def check_parent_progress(parent_id: str) -> None:
    """Được gọi mỗi khi một subtask xong. Nếu tất cả đã ở testing/done -> chạy closure."""
    parent = store.get_task(parent_id)
    if not parent or parent.status in ("done", "archived", "review"):
        return
    subtasks = store.list_tasks(parent_id=parent_id)
    if not subtasks:
        return
    if any(t.status in ("backlog", "in_progress", "blocked") for t in subtasks):
        return

    # Fix round: nếu QA đã tạo bug đang mở, giao cho builder xử lý trước khi đóng
    open_bugs = _open_related_bugs(parent)
    if open_bugs:
        rounds = _fix_rounds(parent)
        if rounds >= MAX_FIX_ROUNDS:
            store.set_status(parent_id, "blocked", "jarvis")
            store.add_chat(
                "jarvis",
                f"{parent.id} vẫn còn {len(open_bugs)} bug mở sau {MAX_FIX_ROUNDS} fix round "
                f"({', '.join(b.id for b in open_bugs)}) — dừng tự động, cần bạn xem xét trên board.",
            )
            return
        store.update_task_fields(parent_id, tags=[*parent.tags, f"fix-round-{rounds + 1}"])
        for bug in open_bugs:
            store.update_task_fields(bug.id, assignee="stark", parent_id=parent_id)
            store.add_event(bug.id, "jarvis", "system",
                            f"Giao stark xử lý trong fix round {rounds + 1} trước khi đóng task cha.")
        store.add_chat(
            "jarvis",
            f"QA phát hiện {len(open_bugs)} bug ở {parent.id} — fix round {rounds + 1}: "
            + ", ".join(b.id for b in open_bugs),
        )
        return  # scheduler sẽ chạy bug fix, xong sẽ gọi lại hàm này

    await _closure(parent, subtasks)


async def _closure(parent: Task, subtasks: list[Task]) -> None:
    """Phase 5: Pepper tổng hợp -> Jarvis verify độc lập -> done -> Phase 6: ghi nhớ."""
    verdict, qa_text = _qa_verdict(parent.id)

    qa_tasks = [t for t in subtasks if t.assignee == "hawkeye"]
    qa = qa_tasks[-1] if qa_tasks else None

    # QA chưa có verdict rõ ràng (agent kẹt/chưa báo cáo) -> chạy lại QA một lần
    # thay vì final review trên dữ liệu rỗng.
    if verdict == "UNKNOWN" and qa and qa.status == "testing" and "qa-retry" not in qa.tags:
        _requeue_qa(
            qa, "qa-retry",
            "Báo cáo QA chưa có verdict PASS/FAIL rõ ràng — requeue để Hawkeye chạy lại.",
            f"Báo cáo QA của {qa.id} chưa có verdict rõ ràng — tôi cho Hawkeye chạy QA lại "
            f"trước khi review cuối {parent.id}.",
        )
        return

    # QA FAIL nhưng bug đã được fix trong fix round sau đó -> re-QA để verdict phản ánh code mới.
    rounds = _fix_rounds(parent)
    if verdict == "FAIL" and qa and qa.status == "testing" and rounds > 0 \
            and f"reqa-{rounds}" not in qa.tags:
        _requeue_qa(
            qa, f"reqa-{rounds}",
            f"Verdict FAIL là từ trước fix round {rounds} — requeue để Hawkeye re-verify code đã sửa.",
            f"Bug ở {parent.id} đã được fix — tôi cho Hawkeye QA lại để xác nhận trước khi đóng.",
        )
        return

    # Pepper tổng hợp báo cáo QA lên task cha
    try:
        pepper = AGENTS["pepper"]
        deliverables = _collect_deliverables(subtasks)
        await run_agent(
            "pepper",
            pepper.system_prompt(),
            f"Task cha {parent.id}: {parent.title}\n\nDeliverable các subtask:\n{deliverables}\n\n"
            f"QA verdict: {verdict}\n{qa_text[:2000]}\n\n"
            "Hãy post_message lên task hiện tại báo cáo QA Complete:\n"
            f"- Tiêu đề: '## QA Complete — {verdict}' (PASS hoặc FAIL)\n"
            "- Tóm tắt: deliverable build, Live URL, screenshot links từ Hawkeye, CSS checks, bug tickets.\n"
            "- Khuyến nghị bước tiếp (nếu FAIL: cần fix gì; nếu PASS: sẵn sàng final review).\n"
            "Rồi trả lời text ngắn.",
            parent,
            pepper.tools,
            max_iterations=6,
        )
    except Exception:
        log.exception("Pepper summary failed (non-blocking)")

    # Jarvis verify độc lập — không tin lời khai suông
    jarvis = AGENTS["jarvis"]
    preview_url = f"{config.BASE_URL}/preview/{parent.project}/"
    try:
        result = await run_agent(
            "jarvis",
            jarvis.system_prompt(),
            CLOSURE_VERIFY_PROMPT.format(
                title=parent.title,
                description=parent.description[:1500],
                deliverables=_collect_deliverables(subtasks),
                qa_verdict=f"{verdict}\n{qa_text[:1500]}",
                preview_url=preview_url,
            ),
            parent,
            jarvis.tools,
            max_iterations=16,
        )
    except Exception as e:
        log.exception("Jarvis closure verify failed")
        store.set_status(parent.id, "blocked", "jarvis")
        store.add_chat("jarvis", f"Không thể verify {parent.id} do lỗi: {e}. Task chuyển sang blocked.")
        return

    approved = "APPROVED" in result.upper().split("\n")[0] or (
        "APPROVED" in result.upper() and "REJECTED" not in result.upper()
    )

    if not approved or verdict == "FAIL":
        store.set_status(parent.id, "blocked", "jarvis")
        store.add_chat(
            "jarvis",
            f"Final review {parent.id}: KHÔNG đạt (QA: {verdict}). Task chuyển sang blocked — "
            f"bạn xem chi tiết trên board, có thể bấm '↺ Chạy lại' trên card để review lại.\n\n{result[:800]}",
        )
        return

    # Đóng toàn bộ: subtask + bug -> done, parent -> done (hoặc review nếu operator gate)
    for t in subtasks:
        if t.status == "testing":
            store.set_status(t.id, "done", "jarvis")
    if parent.review_type == "operator":
        store.set_status(parent.id, "testing", "jarvis")
        store.set_status(parent.id, "review", "jarvis")
        store.add_chat(
            "jarvis",
            f"{parent.id} đã qua QA và verify, nhưng thuộc diện operator review "
            f"(tags: {', '.join(parent.tags)}). Chờ bạn bấm Approve trên board.\n"
            f"🔗 Xem trước khi duyệt: {preview_url}",
        )
    else:
        store.set_status(parent.id, "testing", "jarvis")
        store.set_status(parent.id, "done", "jarvis")
        store.add_chat(
            "jarvis",
            f"Hoàn tất {parent.id} — {parent.title}.\n"
            f"🔗 Live URL: {preview_url}\n\n{result[:600]}",
        )

    await _phase6_memorize(parent, result)


def _collect_deliverables(subtasks: list[Task]) -> str:
    parts = []
    for t in subtasks:
        comments = [e for e in store.list_events(t.id) if e.kind == "comment"]
        last = comments[-1].message[:800] if comments else "(không có deliverable message)"
        parts.append(f"[{t.id}] {t.title} ({t.assignee}, {t.status}):\n{last}")
    return "\n\n".join(parts)


async def _phase6_memorize(parent: Task, summary: str) -> None:
    """Phase 6: cập nhật MEMORY.md + wiki features."""
    try:
        summary_llm = app_settings.resolve_llm(role="summary")
        raw = await llm.chat_text([{
            "role": "user",
            "content": MEMORY_PROMPT.format(
                title=parent.title,
                description=parent.description[:800],
                summary=summary[:1200],
            ),
        }], model=summary_llm["model"], base_url=summary_llm["base_url"], api_key=summary_llm["api_key"])
        data = llm.extract_json(raw)
        if data.get("memory_entry"):
            memory.append_memory(data["memory_entry"], parent.id)
        if data.get("feature_slug") and data.get("feature_doc"):
            memory.write_feature(data["feature_slug"], data["feature_doc"])
        store.add_event(parent.id, "jarvis", "system", "Phase 6: đã cập nhật memory/wiki.")
    except Exception:
        log.exception("Phase 6 memorize failed (non-blocking)")
