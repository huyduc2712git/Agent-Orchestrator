"""Scheduler — Phase 3+4: chạy subtask khi dependency đã xong, không chờ đồng bộ."""
import asyncio
import logging
import re
from datetime import datetime, timezone

from .. import config
from ..agents.registry import AGENTS, WORKER_KEYS
from ..agents.runtime import run_agent
from ..board import store
from ..board.models import Task
from . import orchestrator

log = logging.getLogger("scheduler")

_COMPLETION_RE = re.compile(
    r"(✅\s*DONE\b|\bDONE\b.{0,40}bug-|"
    r"ĐÃ\s*FIX|DA\s*FIX|ĐÃ\s*HOÀN\s*THÀNH|DA\s*HOAN\s*THANH|"
    r"toàn\s*bộ\s*yêu\s*cầu\s*fix\s*đã\s*được|"
    r"fix\s*đã\s*được\s*triển\s*khai|"
    r"VERDICT:\s*PASS|"
    r"##\s*[^\n]{0,80}[—\-]\s*PASS\b)",
    re.I,
)
# Amuro/Heiji hay mở đầu "## Tổng kết" cả khi FAIL — không được coi là DONE.
_FAIL_RE = re.compile(
    r"(VERDICT:\s*FAIL|"
    r"##\s*[^\n]{0,80}[—\-]\s*FAIL\b|"
    r"\bREJECTED\b|"
    r"Pentest[^\n]{0,40}\bFAIL\b|"
    r"Security Review[^\n]{0,40}\bFAIL\b)",
    re.I,
)


def _agent_reported_done(task_id: str) -> bool:
    """True nếu worker từng báo DONE/PASS gần đây — tránh requeue sau reload.

    Không coi "## Tổng kết … FAIL" là xong (trước đây orphan reload đẩy Amuro
    FAIL về testing ngay, làm Operator Chạy lại bị khóa lại).
    """
    seen = 0
    for ev in reversed(store.list_events(task_id)):
        if ev.kind != "comment":
            continue
        if ev.agent in ("system", "conan", "operator"):
            continue
        seen += 1
        msg = ev.message or ""
        if _FAIL_RE.search(msg):
            if seen >= 8:
                break
            continue
        if _COMPLETION_RE.search(msg):
            return True
        if seen >= 8:  # chỉ xét vài comment worker mới nhất
            break
    return False


def _finish_or_requeue(task: Task, *, reason: str) -> str:
    """Đưa sang testing nếu đã có deliverable; ngược lại backlog. Trả status đã set."""
    if _agent_reported_done(task.id):
        if task.assignee in ("kid", "agasa"):
            ok, app_reason = orchestrator.project_has_real_app(task.project_dir or "")
            if not ok:
                store.set_status(task.id, "backlog", "system")
                store.add_event(
                    task.id, "conan", "system",
                    f"{reason} — agent báo DONE nhưng chưa có app ({app_reason}) → backlog.",
                )
                return "backlog"
        store.set_status(task.id, "testing", "system")
        store.add_event(
            task.id, "conan", "system",
            f"{reason} — đã có comment DONE/ĐÃ FIX → testing (không chạy lại từ đầu).",
        )
        log.info("%s %s → testing (%s, already DONE)", task.assignee, task.id, reason)
        return "testing"
    store.set_status(task.id, "backlog", "system")
    store.add_event(task.id, "system", "system", f"{reason} → backlog để chạy tiếp.")
    return "backlog"

_in_flight: set[str] = set()
_semaphore: asyncio.Semaphore | None = None
_task_retry_counts: dict[str, int] = {}
_last_auto_check_time: float = 0.0
_last_handoff_time: float = 0.0
HANDOFF_INTERVAL_SECONDS = 15


def _build_worker_prompt(task: Task) -> str:
    parts = [f"TASK {task.id}: {task.title}", "", task.description or "(không có mô tả)"]

    parent = store.get_task(task.parent_id) if task.parent_id else None
    if parent:
        parts += ["", f"Bối cảnh task cha ({parent.id}): {parent.title}",
                  parent.description[:1000]]

    # Deliverable của các dependency đã xong — context bàn giao
    dep_parts = []
    for dep in store.get_deps(task.id):
        if dep["dep_type"] != "blocks":
            continue
        src = store.get_task(dep["depends_on"])
        if not src:
            continue
        comments = [e for e in store.list_events(src.id) if e.kind == "comment"]
        if comments:
            dep_parts.append(f"[{src.id}] {src.title} ({src.assignee}):\n{comments[-1].message[:1000]}")
    if dep_parts:
        parts += ["", "Deliverable từ các bước trước (dùng làm input):", *dep_parts]

    if task.type == "bug":
        parts += ["", f"Đây là BUG cần fix. Severity: {task.severity or 'n/a'}.",
                  f"Repro steps: {task.repro_steps or 'n/a'}",
                  "Fix xong phải tự verify lại và post_message evidence."]

    preview_url = f"{config.BASE_URL}/preview/{task.project}/"
    parts += ["", f"Project directory: {task.project_dir}",
              f"Live URL (orchestrator serve tĩnh project này): {preview_url} — "
              "nếu sản phẩm là web/trang tĩnh, hãy verify bằng http_get và ghi Live URL "
              "vào deliverable để người dùng bấm vào xem.",
              "Hoàn thành công việc, post_message deliverable, rồi tổng kết bằng text."]

    if task.assignee == "heiji":
        # Checklist từng build sub của task cha
        per_sub_lines: list[str] = []
        if parent:
            builders = [
                t for t in store.list_tasks(parent_id=parent.id)
                if t.assignee in ("kid", "agasa") and t.type != "bug"
            ]
            builders = sorted(builders, key=lambda t: (t.created_at or "", t.id))
            if builders:
                per_sub_lines = [
                    "",
                    "=== QA TỪNG BUILD SUB (bắt buộc — tuần tự theo kế hoạch) ===",
                    "Duyệt LẦN LƯỢT từng sub dưới đây. Sub FAIL → create_bug_ticket với "
                    "related_subtask_id = id sub đó (vd sub-2534). "
                    "VERDICT PASS chỉ khi mọi sub PASS.",
                ]
                for i, b in enumerate(builders, 1):
                    per_sub_lines.append(
                        f"{i}. [{b.id}] {b.title} ({b.assignee}) — status={b.status}"
                    )
        parts += [
            "",
            "=== VISUAL QA CHECKLIST (bắt buộc) ===",
            "1. Live URL: dùng URL từ deliverable builder hoặc preview URL ở trên. "
            "Nếu cần dev server (Vite): run_command Start-Process nền, http_get verify 200.",
            "1b. API smoke SAME-ORIGIN (bắt buộc nếu FE gọi /api/...):",
            f"   a) http_get trực tiếp backend (vd http://127.0.0.1:3000/api/health).",
            f"   b) http_get QUA Live host: {config.BASE_URL}/api/<path-FE-đang-gọi> "
            "(cùng origin trình duyệt khi mở preview — KHÔNG chỉ check :3000).",
            "   Grep src tìm fetch('/api/...') để biết path thật (search/stream/health…).",
            "   UI 200 + backend :3000 OK nhưng /api/* trên Live host = 404/502 → VERDICT: FAIL.",
            "   Root cause thường: preview chỉ serve static, thiếu proxy/api_base. "
            "Hướng fix ghi rõ: (1) set project api_base + Orchestrator proxy /api, "
            "(2) hoặc rewrite FE gọi absolute API URL backend, (3) hoặc Vite proxy. "
            "create_bug_ticket(related_subtask_id=…, area=…, repro) khi FAIL — KHÔNG PASS khi còn lỗi. "
            "Conan không tạo bug; chỉ Final Review sau khi bạn PASS.",
            "2. figma_get nếu description có link Figma — lấy màu/font/layout spec.",
            "3. screenshot_url: desktop top + mobile top + ít nhất 1 interaction shot (tab click).",
            "4. inspect_render: chạy CSS/RENDER VERIFICATION table (brand_hex, body_bg_hex từ Figma nếu có).",
            "5. compare_image nếu có file reference PNG trong project (vd mockup/, reference/).",
            "6. post_message 'Visual QA Report' với bảng kết quả TỪNG build sub (PASS/FAIL) "
            "+ screenshot view_url + bảng API checks (same-origin).",
            "7. VERDICT: PASS hoặc VERDICT: FAIL — kèm evidence, không khẳng định suông.",
            *per_sub_lines,
        ]
    if "git-repo" in (task.tags or []) or "github" in (task.tags or []) or "gitlab" in (task.tags or []):
        parts += [
            "",
            "=== GIT WORKSPACE & COMMIT POLICY (NGHIÊM CẤM TỰ COMMIT/PUSH) ===",
            "1. Project này gắn với Git. Dùng git_status trước khi sửa code.",
            "2. AGENT KHÔNG ĐƯỢC TỰ ĐỘNG RUN 'git commit' HOẶC 'git push'.",
            "3. Agent chỉ thực hiện sửa code, cài thư viện, build và verify kết quả tại chỗ.",
            "4. Việc commit và push mã nguồn lên Git sẽ do NGƯỜI DÙNG tự kiểm tra và bấm thủ công.",
            "",
            "=== CLONE → RUN APP SMOKE (một tiến trình, bắt buộc) ===",
            "Clone chỉ là bước 0. Trước khi báo xong phải:",
            "A. install deps (npm/bun) nếu thiếu node_modules",
            "B. build FE (vite/react) hoặc start FE dev — Live URL/UI http_get 200",
            "C. nếu có backend (server.ts / express / api scripts): START server nền + http_get API/health OK",
            "D. SAME-ORIGIN API: sau khi Live URL đã mở được, http_get "
            f"{config.BASE_URL}/api/<path> (path FE dùng, vd /api/health hoặc /api/zing/...). "
            "Backend :3000 OK mà Live host /api 404 = CHƯA XONG — phải fix proxy/api_base "
            "hoặc create_bug_ticket ghi hướng fix, không bàn giao PASS giả.",
            "E. deliverable ghi: Live URL UI + API direct URL + API same-origin URL + status từng cái",
        ]

    if task.assignee in ("kid", "agasa"):
        parts += [
            "",
            "=== KHI PHÁT HIỆN LỖI (Kid/Agasa) ===",
            "Không bỏ qua 4xx/5xx. Phải: (1) tái hiện bằng http_get, (2) chẩn đoán root cause ngắn, "
            "(3) sửa nếu trong phạm vi task HOẶC create_bug_ticket với hướng fix cụ thể, "
            "(4) post_message evidence. UI đẹp ≠ xong nếu API same-origin fail.",
        ]

    parts += [
        "",
        "=== NODE / NPM / FRAMEWORK CHECK (Bắt buộc kiểm tra) ===",
        "1. Nếu project chứa package.json, BẮT BUỘC kiểm tra thư mục node_modules.",
        "2. Nếu CHƯA CÓ node_modules, phải chạy run_command 'npm install' (hoặc 'bun install') để cài đặt đủ thư viện.",
        "3. Nếu project dùng React/Vue/Vite (.tsx/.vue), trình duyệt sẽ bị MÀN HÌNH TRẮNG nếu chỉ serve file index.html thô. Phải chạy 'npm run build' hoặc 'npx vite build' để bundle ra dist tĩnh, hoặc bật dev server trước khi hoàn tất!",
        "4. Preview /preview/... serve FILE TĨNH. Backend start riêng. "
        "FE absolute fetch('/api/...') sẽ đập vào host Live URL — phải smoke same-origin, không chỉ :3000.",
    ]
    return "\n".join(parts)


async def _run_worker(task: Task) -> None:
    assert _semaphore is not None
    agent = AGENTS[task.assignee]
    async with _semaphore:
        try:
            if task.parent_id:
                parent = store.get_task(task.parent_id)
                if parent and parent.status in ("blocked", "failed", "archived"):
                    log.info("Worker %s hủy chạy %s vì parent task %s ở trạng thái %s", task.assignee, task.id, parent.id, parent.status)
                    if parent.status in ("blocked", "failed"):
                        store.set_status(task.id, parent.status, "system")
                    return

            store.set_status(task.id, "in_progress", task.assignee)
            log.info("Start %s -> %s (%s)", task.id, task.assignee, task.title)
            result = await run_agent(
                task.assignee,
                agent.system_prompt(),
                _build_worker_prompt(task),
                task,
                agent.tools,
            )
            curr = store.get_task(task.id)
            parent = store.get_task(task.parent_id) if task.parent_id else None
            if (curr and curr.status in ("blocked", "failed", "archived", "testing", "done")) or (
                parent and parent.status in ("blocked", "failed", "archived")
            ):
                log.info(
                    "Worker %s kết thúc sớm cho %s vì status/parent đã là %s",
                    task.assignee, task.id, curr.status if curr else "?",
                )
                return
            # Marker do runtime gắn khi hết vòng lặp — không dò cụm từ tự do của LLM
            ITERATION_LIMIT_MARKER = "[ITERATION_LIMIT_REACHED]"
            hit_limit = (result or "").startswith(ITERATION_LIMIT_MARKER)
            display = result
            if hit_limit:
                display = result[len(ITERATION_LIMIT_MARKER):].lstrip()
            store.add_event(task.id, task.assignee, "comment", display[:4000])

            # Đã post DONE trong vòng này (hoặc trước reload) → testing, kể cả khi hit_limit
            if _agent_reported_done(task.id) and not (
                task.assignee in ("kid", "agasa")
                and not orchestrator.project_has_real_app(task.project_dir or "")[0]
            ):
                store.set_status(task.id, "testing", task.assignee)
                if hit_limit:
                    store.add_event(
                        task.id, "conan", "system",
                        "Chạm giới hạn vòng lặp nhưng đã có DONE → testing.",
                    )
            elif hit_limit:
                log.warning("Worker %s chạm max iterations trên %s", task.assignee, task.id)
                _finish_or_requeue(
                    task,
                    reason="Chạm giới hạn vòng lặp tool",
                )
            elif task.assignee in ("kid", "agasa"):
                # Không cho vào testing/QA nếu project vẫn trống/stub (Kid nói xong nhưng chưa code)
                ok, reason = orchestrator.project_has_real_app(task.project_dir or "")
                if not ok:
                    log.warning(
                        "Worker %s '%s' kết thúc nhưng deliverable chưa có (%s) — requeue backlog",
                        task.assignee, task.id, reason,
                    )
                    store.set_status(task.id, "backlog", task.assignee)
                    store.add_event(
                        task.id, "conan", "system",
                        f"Chưa chuyển QA: {reason}. Làm lại — scaffold/build tới khi có source thật trên đĩa.",
                    )
                    store.add_chat(
                        "conan",
                        f"⏳ {task.id} ({task.title}): Kid/Agasa báo xong nhưng project chưa có app "
                        f"({reason}) — giữ backlog, chưa vào QA.",
                    )
                else:
                    store.set_status(task.id, "testing", task.assignee)
            else:
                store.set_status(task.id, "testing", task.assignee)
        except Exception as e:
            log.exception("Worker %s failed on %s", task.assignee, task.id)
            err_str = str(e)
            if "429" in err_str or "Rate limit" in err_str or "FreeUsageLimitError" in err_str or "LLMError" in str(type(e)):
                log.warning("Worker %s hit LLM Rate Limit on %s — requeuing to backlog for auto-retry", task.assignee, task.id)
                store.set_status(task.id, "backlog", task.assignee)
                store.add_event(task.id, "system", "system", f"API LLM nghẽn tạm thời ({err_str[:150]}) — tự động chờ để thử lại.")
            else:
                store.set_status(task.id, "blocked", task.assignee)
                store.add_event(task.id, "system", "system", f"Agent gặp lỗi: {e}")
                store.add_chat("conan", f"⚠️ {task.id} ({task.title}) bị blocked do lỗi: {str(e)[:200]}")
        finally:
            _in_flight.discard(task.id)

    if task.parent_id:
        try:
            await orchestrator.check_parent_progress(task.parent_id)
        except Exception:
            log.exception("check_parent_progress failed for %s", task.parent_id)


def auto_recover_stuck_and_blocked_tasks() -> None:
    """Conan Auto-Recovery Patrol — Quét định kỳ mỗi 2 phút:
    1. Reset subtask/task bị in_progress mà không nằm trong _in_flight (bị kẹt tiến trình).
    1b. Task nằm trong _in_flight nhưng im quá lâu (worker treo LLM) → bỏ in_flight + requeue.
    2. Tự động rerun subtask/task bị blocked (tối đa 3 lần retry).
    """
    now_utc = datetime.now(timezone.utc)
    STALE_IN_FLIGHT_SEC = 600  # 10 phút không heartbeat → coi worker chết

    # 1b. Worker treo nhưng vẫn chiếm _in_flight → scheduler không bao giờ spawn lại
    stale_ids = []
    for tid in list(_in_flight):
        t = store.get_task(tid)
        if not t:
            _in_flight.discard(tid)
            continue
        # Ưu tiên mốc event/tool gần nhất (updated_at được touch mỗi tool)
        stamp = store.last_event_at(tid) or t.updated_at
        try:
            updated_dt = datetime.fromisoformat(stamp)
            age = (now_utc - updated_dt).total_seconds()
        except Exception:
            age = 0
        if age > STALE_IN_FLIGHT_SEC:
            stale_ids.append(tid)
    for tid in stale_ids:
        t = store.get_task(tid)
        log.warning(
            "Conan Auto-Recovery: stale _in_flight %s (im >%ss) — discard + requeue",
            tid, STALE_IN_FLIGHT_SEC,
        )
        _in_flight.discard(tid)
        if t and t.status == "in_progress":
            dest = _finish_or_requeue(t, reason="Auto-Recovery: worker treo / không heartbeat")
            if dest == "backlog":
                store.add_chat(
                    "conan",
                    f"🔄 Conan Auto-Recovery: {tid} ({t.title}) worker treo quá lâu — chạy lại từ backlog.",
                )
        elif t and t.status == "backlog":
            # Desync: đã backlog nhưng còn chiếm slot — chỉ nhả slot
            log.info("Discard stale in_flight for backlog task %s", tid)

    # 1. Quét toàn bộ task/subtask in_progress bị kẹt không có worker thread thực thi
    in_prog = store.list_tasks(status=["in_progress"])
    for t in in_prog:
        # Task cha có subtasks -> chỉ là container chờ subtask chạy xong, không có worker riêng trong _in_flight
        is_parent = not t.parent_id and bool(store.list_tasks(parent_id=t.id))
        if is_parent:
            continue

        if t.id not in _in_flight:
            try:
                if t.parent_id:
                    parent = store.get_task(t.parent_id)
                    if parent and parent.status in ("blocked", "failed", "archived", "done"):
                        target_st = parent.status if parent.status in ("blocked", "failed") else "done"
                        log.info("Conan Auto-Recovery: Parent task %s is %s — setting subtask %s -> %s", t.parent_id, parent.status, t.id, target_st)
                        store.set_status(t.id, target_st, "conan")
                        continue

                updated_dt = datetime.fromisoformat(t.updated_at)
                if (now_utc - updated_dt).total_seconds() > 120:
                    log.info("Conan Auto-Recovery: stuck in_progress %s (%s)", t.id, t.title)
                    dest = _finish_or_requeue(t, reason="Auto-Recovery: task kẹt tiến trình / reload")
                    if dest == "backlog":
                        store.add_chat(
                            "conan",
                            f"🔄 Conan Auto-Recovery: kích hoạt lại {t.id} ({t.title}) do bị dừng tiến trình.",
                        )
                    else:
                        store.add_chat(
                            "conan",
                            f"✅ {t.id}: agent đã báo DONE trước khi kẹt/reload — chuyển testing, không chạy lại.",
                        )
            except Exception:
                pass

    # 2. Quét task/subtask bị blocked để tự động rerun (tối đa 3 lần)
    blocked_tasks = store.list_tasks(status=["blocked"])
    for t in blocked_tasks:
        if t.parent_id:
            parent = store.get_task(t.parent_id)
            if parent and parent.status == "blocked":
                # Parent task đang blocked -> giữ nguyên subtask blocked, không auto-recover
                continue

        # Nếu Operator chủ động block -> KHÔNG tự động auto-recover, giữ nguyên blocked chờ Operator
        events = store.list_events(t.id)
        if any(e.agent == "operator" and ("blocked" in e.message.lower() or "dừng" in e.message.lower()) for e in events[-10:]):
            continue

        is_parent = not t.parent_id and bool(store.list_tasks(parent_id=t.id))
        if is_parent:
            # Parent blocked: nếu Final Review mới nhất đã APPROVED → đóng luôn (đừng kẹt vì QA FAIL cũ)
            events = store.list_events(t.id)
            final_blobs = [
                e.message.upper()
                for e in events[-30:]
                if e.agent == "conan" and "FINAL REVIEW" in e.message.upper()
            ]
            if any(orchestrator._parse_conan_verdict(m) for m in final_blobs):
                log.info("Auto-Recovery: %s có Final Review APPROVED — đóng task thay vì giữ blocked", t.id)
                for st in store.list_tasks(parent_id=t.id):
                    if st.status in ("testing", "review"):
                        store.set_status(st.id, "done", "conan")
                    elif st.status in ("blocked", "failed", "backlog", "in_progress"):
                        # về testing rồi done (state machine không cho blocked→done trực tiếp)
                        if st.status in ("blocked", "failed"):
                            store.set_status(st.id, "backlog", "conan")
                        if store.get_task(st.id).status == "backlog":
                            store.set_status(st.id, "in_progress", "conan")
                        cur = store.get_task(st.id)
                        if cur and cur.status == "in_progress":
                            store.set_status(st.id, "testing", "conan")
                        store.set_status(st.id, "done", "conan")
                # Parent: blocked → backlog → in_progress → testing → done
                store.set_status(t.id, "backlog", "conan")
                store.set_status(t.id, "in_progress", "conan")
                store.set_status(t.id, "testing", "conan")
                store.set_status(t.id, "done", "conan")
                store.add_event(
                    t.id, "conan", "system",
                    "Auto-Recovery: Final Review đã APPROVED — đóng task (bỏ qua QA FAIL cũ).",
                )
                store.add_chat(
                    "conan",
                    f"✅ {t.id}: Final Review đã APPROVED nhưng task bị kẹt blocked do QA FAIL cũ — đã đóng task.",
                )
                continue

            blobs = [e.message.upper() for e in events[-20:]]
            # Heiji FAIL nằm trên subtask testing — check luôn children
            for st in store.list_tasks(parent_id=t.id):
                blobs.extend(e.message.upper() for e in store.list_events(st.id)[-8:])
            qa_failed = any(
                ("VERDICT: FAIL" in m)
                or ("VERDICT: REJECTED" in m)
                or ("QA: FAIL" in m)
                or ("KHÔNG ĐẠT" in m)
                or ("REJECTED" in m and "APPROVED" not in m)
                for m in blobs
            )
            if qa_failed:
                _task_retry_counts[t.id] = max(_task_retry_counts.get(t.id, 0), 3)
                # Chỉ thông báo 1 lần — reload server / vòng auto-recover sau không spam chat
                already_notified = any(
                    "bỏ qua auto-retry" in (e.message or "")
                    or "QA/Review FAIL" in (e.message or "")
                    for e in events[-40:]
                )
                if not already_notified:
                    store.add_event(
                        t.id, "conan", "system",
                        "Auto-Recovery: bỏ qua auto-retry — QA/Final review đã FAIL. "
                        "Cần builder fix rồi bấm '↺ Chạy lại'.",
                    )
                    store.add_chat(
                        "conan",
                        f"⛔ {t.id} bị blocked vì QA/Review FAIL — không tự chạy lại closure. "
                        f"Sửa code (hoặc giao lại fix), rồi bấm '↺ Chạy lại' trên board.",
                    )
                continue

        retries = _task_retry_counts.get(t.id, 0)
        if retries < 3:
            _task_retry_counts[t.id] = retries + 1
            log.info("Conan Auto-Recovery: Rerunning blocked task %s (%s) — Retry %s/3", t.id, t.title, retries + 1)
            store.add_event(t.id, "conan", "system", f"Conan Auto-Recovery: Tự động chạy lại task bị blocked (Lần retry {retries + 1}/3).")
            store.set_status(t.id, "backlog", "conan")
            store.add_chat("conan", f"🔄 Conan Auto-Recovery: Task {t.id} ({t.title}) bị kẹt/lỗi -> Tự động chạy lại lần {retries + 1}/3.")
        elif retries == 3:
            _task_retry_counts[t.id] = 4  # Đánh dấu đã thông báo
            store.set_status(t.id, "failed", "conan")
            store.add_chat("conan", f"⛔ Task {t.id} ({t.title}) đã fail 3 lần. Dừng tự động chạy lại. Task được đưa vào trạng thái Failed (thất bại).")
            log.warning("Task %s reached max retries (3) and is failed.", t.id)

            # Nếu là task cha, huỷ luôn các task con chưa hoàn thành
            if not t.parent_id:
                subtasks = store.list_tasks(parent_id=t.id)
                for st in subtasks:
                    if st.status not in ("done", "archived", "failed"):
                        store.set_status(st.id, "failed", "conan")
                        store.add_event(st.id, "conan", "system", f"Task cha {t.id} đã thất bại, subtask tự động bị huỷ.")

    # 3. Conan kiểm tra tiến độ parent — bỏ blocked/failed (đã chờ operator, không spam chat)
    parent_tasks = [
        t for t in store.list_tasks(include_archived=False)
        if not t.parent_id and t.status not in ("done", "archived", "failed", "blocked")
    ]
    for pt in parent_tasks:
        try:
            asyncio.create_task(orchestrator.check_parent_progress(pt.id))
        except Exception:
            pass


async def scheduler_loop() -> None:
    """Quét board định kỳ, spawn agent cho task đủ điều kiện chạy."""
    global _semaphore, _last_auto_check_time, _last_handoff_time
    _semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_AGENTS)
    log.info("Scheduler started")

    # Khôi phục các subtask in_progress bị mồ côi do server restart (CHỈ reset worker subtask, KHÔNG reset parent task)
    try:
        orphaned = [
            t for t in store.list_tasks(status=["in_progress"])
            if t.parent_id  # Chỉ reset subtask
        ]
        for ot in orphaned:
            parent = store.get_task(ot.parent_id)
            if parent and parent.status in ("done", "archived", "failed", "blocked"):
                if parent.status in ("done", "archived"):
                    log.info("Parent task %s is %s — marking orphaned subtask %s -> done", ot.parent_id, parent.status, ot.id)
                    store.set_status(ot.id, "done", "system")
                else:
                    log.info("Parent task %s is %s — setting orphaned subtask %s -> %s", ot.parent_id, parent.status, ot.id, parent.status)
                    store.set_status(ot.id, parent.status, "system")
            else:
                dest = _finish_or_requeue(ot, reason="Server reload — orphan in_progress")
                log.info(
                    "Orphaned in_progress subtask %s -> %s",
                    ot.id, dest,
                )
    except Exception:
        log.exception("Failed to reset orphaned in_progress tasks")

    # Sync cập nhật real-time trạng thái parent tasks ngay lập tức khi khởi động
    try:
        auto_recover_stuck_and_blocked_tasks()
    except Exception:
        log.exception("Initial auto-recover check failed")

    while True:
        try:
            current_time = asyncio.get_event_loop().time()
            if current_time - _last_auto_check_time > 120:  # Quét mỗi 2 phút
                _last_auto_check_time = current_time
                auto_recover_stuck_and_blocked_tasks()

            if current_time - _last_handoff_time >= HANDOFF_INTERVAL_SECONDS:
                _last_handoff_time = current_time
                try:
                    from .handoff import write_handoff_snapshot
                    write_handoff_snapshot()
                except Exception:
                    log.exception("write_handoff_snapshot failed")

            candidates = store.list_tasks(status=["backlog"])
            for t in candidates:
                if t.assignee not in WORKER_KEYS or t.id in _in_flight:
                    continue
                if t.parent_id:
                    parent = store.get_task(t.parent_id)
                    if parent and parent.status in ("done", "archived", "failed", "blocked"):
                        if parent.status == "done":
                            store.set_status(t.id, "done", "system")
                        elif parent.status in ("blocked", "failed"):
                            store.set_status(t.id, parent.status, "system")
                        continue
                    # Critic (QA/Security/Pentest) không chạy khi còn build sub đang làm
                    if t.assignee in ("heiji", "akai", "amuro", "haibara"):
                        siblings = store.list_tasks(parent_id=t.parent_id)
                        busy_builders = [
                            s for s in siblings
                            if s.assignee in ("kid", "agasa") and s.type != "bug"
                            and s.status in ("backlog", "in_progress", "blocked")
                        ]
                        if busy_builders:
                            continue
                if not store.deps_satisfied(t.id):
                    continue
                _in_flight.add(t.id)
                asyncio.create_task(_run_worker(t))
        except Exception:
            log.exception("Scheduler tick failed")
        await asyncio.sleep(config.SCHEDULER_INTERVAL_SECONDS)
