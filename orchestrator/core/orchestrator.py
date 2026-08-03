"""Conan orchestrator — hiện thực 6 phase từ docs/design.md.

Phase 1: Tiếp nhận (chat) -> Phase 2: Phân tích & lập kế hoạch (chia subtask chain)
-> Phase 3: Phân công (scheduler chạy agent) -> Phase 4: Theo dõi (event bus, không chờ)
-> Phase 5: QA + closure (verify độc lập) -> Phase 6: Ghi nhớ (memory + wiki).
"""
import base64
import json
import logging
import mimetypes
import re
from pathlib import Path

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

PLANNING_PROMPT = """Bạn là Conan — chat orchestrator của một hệ thống multi-agent. Bạn KHÔNG tự code.

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
      "agent": "<kid|agasa|heiji|haibara|akai|amuro>", "depends_on": [<index các subtask phải xong trước, tính từ 0>],
      "tags": []}}
  ]
}}

Active Project (nếu có): {active_project}
— Nếu Active Project khác rỗng: LUÔN dùng đúng slug đó, KHÔNG tạo project mới. Task mới nằm trong project đang chọn.
— Chỉ đề xuất project mới khi Active Project rỗng VÀ người dùng yêu cầu tạo project mới rõ ràng.
— project_dir: nếu user ghi đường dẫn tuyệt đối (vd D:\\Dev\\voxbeat, /home/me/apps/foo) → BẮT BUỘC điền đúng vào task.project_dir.
  Không được để trống nếu user đã chỉ định. Không đề xuất clone vào thư mục trong cây AI Orchestrator.

Link context (parser-registry đã quét tin nhắn):
{link_hints}
Projects root mặc định (ngoài Orchestrator): {projects_root}

Quy tắc lập kế hoạch:
- Task nhỏ 1 bước -> 1 subtask cho đúng agent chuyên môn. Task phức tạp -> chia subtask chain có dependency.
- CLONE GIT: repo nặng KHÔNG clone vào thư mục Orchestrator. Dùng path user chỉ định, hoặc Projects root ở trên + slug.
  Trong reply hãy nêu rõ sẽ clone vào path nào.
- CLONE / MỞ REPO / "chạy app" (có GitHub/GitLab hoặc package.json + server): đây là MỘT tiến trình, KHÔNG tách "chỉ clone" là xong.
  Phải cover trong subtask build (kid và/hoặc agasa):
  (1) confirm repo đã clone, (2) install deps, (3) build FE nếu cần,
  (4) START app — cả frontend preview/dev VÀ backend/API nếu repo có server (Express, FastAPI, scripts "dev"/"start", server.ts…),
  (5) smoke: http_get Live URL UI = 200 VÀ http_get API trực tiếp (:3000…) VÀ http_get
      cùng path /api/... trên host Live URL (same-origin trình duyệt).
  UI đẹp / backend direct OK mà preview host /api 404 = CHƯA XONG — plan phải cover proxy/api_base hoặc bugfix.
- CẤM tạo subtask QA/Review riêng cho Heiji/Haibara ("Kiểm tra chất lượng", "QA verify", "đảm bảo chất lượng"…).
  QA là QUY TRÌNH TỰ ĐỘNG: khi Kid/Agasa xong → hệ thống đưa sang Testing → Heiji test. Plan chỉ gồm subtask BUILD.
- Security (Akai) và Pentest (Amuro) cũng được hệ thống tự tạo SAU khi QA PASS — CẤM tạo subtask akai/amuro/heiji/haibara trong plan.
- Chỉ tạo subtask phát triển thật: Kid (UI/scaffold/frontend), Agasa (backend/API/data). Thứ tự: scaffold → build → integrate (dependency đúng).
- Mô tả subtask phải đầy đủ context (steer message). Tuân thủ hướng dẫn Build/QA trong Link context ở trên (đưa nguyên văn URL, tags).
- Việc liên quan DB migration / security / deploy production: thêm tag tương ứng ("db-migration", "security", "deploy-prod") để hệ thống bắt buộc operator review.
- Trả lời người dùng ngay trong "reply" — không để họ chờ trong im lặng.

ĐỊNH DẠNG OUTPUT (bắt buộc): ký tự đầu tiên là "{{", ký tự cuối cùng là "}}".
KHÔNG bọc trong mảng [...], KHÔNG code fence ```, KHÔNG text trước/sau JSON.
"""

CLOSURE_VERIFY_PROMPT = """Task cha: {title}
{description}

Các subtask và deliverable:
{deliverables}

QA verdict của Heiji:
{qa_verdict}

Live URL của project (orchestrator serve tĩnh): {preview_url}

Nhiệm vụ của bạn (Conan, final review — Phase 5): VERIFY ĐỘC LẬP, không tin lời khai suông.
Dùng tool kiểm tra thực tế: list_dir/read_file xem file có tồn tại và đúng nội dung không,
http_get Live URL ở trên (phải trả status=200 nếu là sản phẩm web).
LƯU Ý ĐẶC BIỆT:
- package.json thiếu node_modules, hoặc React/Vite chưa build → màn trắng → REJECT.
- Nếu repo có backend/API (server.ts, express, scripts start/dev server, thư mục api/server): 
  CHỈ http_get preview UI = 200 LÀ KHÔNG ĐỦ. Phải http_get health/API trực tiếp (port phổ biến :3000/:8000)
  VÀ http_get cùng path trên host Live URL (same-origin — FE fetch('/api/...')).
  Direct OK mà Live host /api 404 → REJECT (thiếu proxy/api_base).
  UI ổn mà API không chạy / lỗi → VERDICT: REJECTED.
Sau khi kiểm tra, post_message một "Final Review" tổng hợp evidence chain (build -> QA -> verify),
ghi rõ "Live URL verified", "API direct verified", "API same-origin verified".
Rồi trả lời text cuối:
- Dòng đầu: "VERDICT: APPROVED" hoặc "VERDICT: REJECTED"
- Nếu REJECTED: liệt kê từng lỗi (bullet: file/URL/triệu chứng). BẠN KHÔNG tạo bug ticket —
  hệ thống sẽ trả việc về Heiji (QA) để create_bug_ticket → Kid fix → QA lại.
  Chỉ review khi QA đã PASS.
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


_CRITIC_PLAN_AGENTS = frozenset({"heiji", "haibara", "akai", "amuro", "conan"})
_QA_TITLE_MARKERS = (
    "kiểm tra và đảm bảo chất lượng",
    "kiểm tra chất lượng",
    "đảm bảo chất lượng",
    "qa verify",
    "visual qa",
    "quality assurance",
    "kiểm thử",
)


def _filter_build_only_subtasks(subtasks_info: list) -> list:
    """Loại subtask QA/Security khỏi plan — QA/Akai/Amuro do hệ thống tự chạy sau build."""
    if not subtasks_info:
        return []
    keep_old: list[int] = []
    for i, st in enumerate(subtasks_info):
        agent = (st.get("agent") or "kid").lower().strip()
        title = (st.get("title") or "").lower()
        if agent in _CRITIC_PLAN_AGENTS:
            continue
        if any(m in title for m in _QA_TITLE_MARKERS):
            continue
        keep_old.append(i)
    if not keep_old:
        return []
    old_to_new = {old: new for new, old in enumerate(keep_old)}
    out: list[dict] = []
    for old in keep_old:
        st = dict(subtasks_info[old])
        agent = (st.get("agent") or "kid").lower().strip()
        if agent not in WORKER_KEYS or agent in _CRITIC_PLAN_AGENTS:
            st["agent"] = "kid"
        deps = []
        for d in st.get("depends_on") or []:
            if isinstance(d, int) and d in old_to_new:
                deps.append(old_to_new[d])
        st["depends_on"] = deps
        out.append(st)
    return out


async def _fallback_plain_reply(user_message: str, history_text: str, planner: dict) -> bool:
    """Planner hỏng JSON — vẫn trả lời người dùng bằng text thường. True nếu đã reply."""
    prompt = (
        "Bạn là Conan — orchestrator của hệ thống multi-agent, trả lời bằng tiếng Việt, "
        "ngắn gọn và cụ thể. Trả lời bằng VĂN BẢN THƯỜNG (không JSON).\n\n"
        f"BOARD hiện tại:\n{_board_snapshot()}\n\n"
        f"MEMORY:\n{memory.read_memory()[-2000:]}\n\n"
        f"Lịch sử chat:\n{history_text}\n\n"
        f'Người dùng hỏi: "{user_message}"\n\n'
        "Nếu đây là yêu cầu giao việc (cần tạo task), hãy nói rõ bạn cần họ gửi lại "
        "để lập kế hoạch; nếu là câu hỏi thì trả lời trực tiếp."
    )
    try:
        text = await llm.chat_text(
            [{"role": "user", "content": prompt}],
            model=planner["model"],
            base_url=planner["base_url"],
            api_key=planner["api_key"],
        )
    except Exception:
        log.exception("Fallback plain reply failed")
        return False
    text = (text or "").strip()
    if not text:
        return False
    store.add_chat("conan", text)
    return True


def _prepare_vision_data_url(path: Path) -> tuple[str, str]:
    """Nén/resize ảnh trước khi gửi vision API — tránh HTTP 413 Payload Too Large.

    Trả về (data_url, mime). Giữ file gốc trên đĩa (preview chat); chỉ nén bản gửi LLM.
    """
    from io import BytesIO

    from PIL import Image

    raw = path.read_bytes()
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    img = Image.open(BytesIO(raw))
    w0, h0 = img.size
    # Ảnh nhỏ sẵn thì khỏi nén
    if len(raw) <= config.VISION_IMAGE_MAX_BYTES and max(w0, h0) <= config.VISION_IMAGE_MAX_SIDE:
        return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}", mime

    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    max_side = config.VISION_IMAGE_MAX_SIDE
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / float(max(w, h))
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)

    quality = config.VISION_IMAGE_JPEG_QUALITY
    out = BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    data = out.getvalue()
    while len(data) > config.VISION_IMAGE_MAX_BYTES and quality > 45:
        quality -= 10
        out = BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        data = out.getvalue()

    log.info(
        "Vision image compressed: %s %dx%d %sB → jpeg q=%s %sB",
        path.name, w0, h0, len(raw), quality, len(data),
    )
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}", "image/jpeg"


async def analyze_image_and_chat(
    message: str,
    image_path: str,
    project: str | None = None,
) -> None:
    """Đọc ảnh bằng model vision → ghép mô tả text → gọi handle_chat như tin thường.

    Không fallback ngầm sang model text nếu chưa cấu hình role vision / MODEL_VISION.
    """
    roles = app_settings.role_models()
    path = Path(image_path)
    if not path.is_file():
        store.add_chat("conan", f"Không tìm thấy file ảnh: `{image_path}`")
        return

    # Ưu tiên role Vision; nếu chưa gán thì dùng MODEL_VISION env; cuối cùng fallback Planner
    # (nhiều model multimodal như llama-4-scout được gán Planner nhưng quên gán Vision).
    used_fallback = False
    if roles.get("vision"):
        vision = app_settings.resolve_llm(role="vision")
    elif config.MODEL_VISION:
        vision = {
            "model": config.MODEL_VISION,
            "base_url": config.LLM_BASE_URL,
            "api_key": config.LLM_API_KEY,
            "name": config.MODEL_VISION,
        }
    elif roles.get("planner"):
        vision = app_settings.resolve_llm(role="planner")
        used_fallback = True
    else:
        store.add_chat(
            "conan",
            "Chưa cấu hình model đọc ảnh (role **Vision**) trong Settings. "
            "Gán một model hỗ trợ ảnh (vd llama-4-scout, GPT-4o, Gemini) rồi thử lại.",
        )
        return

    if used_fallback:
        log.info(
            "Vision role chưa gán — dùng tạm model Planner `%s` để đọc ảnh",
            vision.get("name") or vision.get("model"),
        )

    mime_guess = mimetypes.guess_type(str(path))[0] or "image/png"
    if not mime_guess.startswith("image/"):
        store.add_chat("conan", f"File không phải ảnh hợp lệ (`{mime_guess}`).")
        return

    try:
        data_url, _mime = _prepare_vision_data_url(path)
    except Exception as e:
        log.exception("Vision image prepare failed")
        store.add_chat("conan", f"Không xử lý được ảnh trước khi gửi model: {e}")
        return

    user_text = (message or "").strip() or "Hãy mô tả ảnh này và đề xuất việc cần làm."

    prompt_blocks = [
        {
            "type": "text",
            "text": (
                "Bạn là trợ lý vision cho Conan (orchestrator). "
                "Mô tả ảnh bằng tiếng Việt, ngắn gọn, đủ chi tiết để lập kế hoạch làm việc "
                "(UI elements, layout, lỗi nhìn thấy, text trên ảnh nếu có). "
                "Không bịa chi tiết không có trong ảnh.\n\n"
                f"Yêu cầu kèm theo của người dùng: {user_text}"
            ),
        },
        {"type": "image_url", "image_url": {"url": data_url}},
    ]

    try:
        msg = await llm.chat(
            [{"role": "user", "content": prompt_blocks}],
            model=vision["model"],
            base_url=vision["base_url"],
            api_key=vision["api_key"],
        )
        description = (msg.get("content") or "").strip()
    except llm.LLMError as e:
        log.exception("Vision model failed")
        store.add_chat("conan", f"Gọi model đọc ảnh thất bại: {e}")
        return
    except Exception as e:
        log.exception("Vision analyze crashed")
        store.add_chat("conan", f"Gọi model đọc ảnh thất bại: {e}")
        return

    if not description:
        store.add_chat("conan", "Model đọc ảnh trả về rỗng — thử model vision khác trong Settings.")
        return

    enriched = (
        f"{user_text}\n\n"
        f"[Mô tả từ ảnh đính kèm — model `{vision.get('name') or vision['model']}`]\n"
        f"{description}"
    )
    await handle_chat(enriched, project=project)


async def handle_chat(user_message: str, project: str | None = None) -> None:
    """Phase 1 + 2: tiếp nhận, phân tích, lập kế hoạch, trả lời ngay.

    `project`: slug project đang chọn trên UI — task mới buộc gắn vào đây.
    """
    from ..paths import (
        extract_target_dir,
        is_under_orchestrator,
        resolve_project_dir,
        wants_default_path,
    )

    history = store.list_chat(limit=10)
    history_text = "\n".join(f"{m['role']}: {m['message'][:300]}" for m in history[:-1]) or "(chưa có)"

    active = (project or app_settings.active_project() or "").strip()
    forced_dir = ""  # path user chọn khi trả lời pending_clone
    accepted_default = False

    # Tiếp tục chờ chọn thư mục clone
    pending = app_settings.pending_clone()
    if pending:
        chosen = extract_target_dir(user_message)
        if chosen or wants_default_path(user_message):
            forced_dir = chosen or ""
            accepted_default = wants_default_path(user_message) and not chosen
            user_message = pending.get("message") or user_message
            if pending.get("project"):
                active = pending["project"]
            app_settings.clear_pending_clone()
        elif detect_links(user_message):
            # User gửi yêu cầu mới → hủy pending cũ
            app_settings.clear_pending_clone()
        else:
            sug = pending.get("suggested_dir") or app_settings.effective_projects_root()
            store.add_chat(
                "conan",
                f"Vẫn đang chờ thư mục clone cho `{pending.get('url')}`.\n"
                f"— Gửi path tuyệt đối (vd `D:\\Dev\\myapp`)\n"
                f"— Hoặc gõ `mặc định` → `{sug}`\n"
                f"— Đổi gốc mặc định trong Settings → Projects",
            )
            return

    detected_links = detect_links(user_message)
    link_hints = default_registry.planning_hints(detected_links)

    # Clone git: hỏi thư mục nếu user chưa chỉ định (tránh nhồi vào Orchestrator)
    git_early = next(
        (x for x in detected_links if x.get("type") in ("github", "gitlab") and x.get("clone_url")),
        None,
    )
    msg_path = forced_dir or extract_target_dir(user_message)
    if (
        git_early
        and not msg_path
        and not accepted_default
        and not wants_default_path(user_message)
    ):
        need_ask = True
        if active:
            ap = app_settings.get_project(active)
            pdir = (ap or {}).get("project_dir") or ""
            if pdir and not is_under_orchestrator(pdir):
                need_ask = False
            elif pdir and (Path(pdir) / ".git").is_dir():
                need_ask = False  # project đã gắn repo
        if need_ask:
            repo = git_early.get("repo") or "project"
            slug_guess = _slug(repo)
            suggested, _ = resolve_project_dir(
                slug=slug_guess if not active else active,
                projects_root=app_settings.effective_projects_root(),
            )
            app_settings.set_pending_clone({
                "url": git_early["clone_url"],
                "message": user_message,
                "project": active,
                "suggested_dir": suggested,
            })
            store.add_chat(
                "conan",
                f"Repo `{git_early['clone_url']}` — bạn muốn clone vào thư mục nào?\n"
                f"— Path tuyệt đối, vd: `D:\\Dev\\{slug_guess}`\n"
                f"— Hoặc gõ `mặc định` → `{suggested}` (ngoài thư mục Orchestrator)\n"
                f"— Đổi thư mục gốc: Settings → Projects root",
            )
            return

    prompt = PLANNING_PROMPT.format(
        roster=roster_description(),
        memory=memory.read_memory()[-4000:],
        wiki=memory.read_wiki_summary(3000),
        board=_board_snapshot(),
        history=history_text,
        message=user_message.replace('"', "'"),
        active_project=active or "(chưa chọn — có thể tạo project mới nếu cần)",
        link_hints=link_hints,
        projects_root=app_settings.effective_projects_root(),
    )

    planner = app_settings.resolve_llm(role="planner")
    try:
        decision = await llm.chat_json(
            [{"role": "user", "content": prompt}],
            model=planner["model"],
            base_url=planner["base_url"],
            api_key=planner["api_key"],
            expect_object=True,
        )
        decision = llm.normalize_json_object(decision)
        if not isinstance(decision, dict):
            raise ValueError(f"Planner trả về không phải object: {type(decision)}")
        if "action" not in decision and ("message" in decision or "reply" in decision):
            # Model quên action — câu hỏi → reply
            decision = {
                "action": "reply",
                "message": decision.get("message") or decision.get("reply") or "",
            }
    except Exception as e:
        log.exception("Planning failed")
        # Câu hỏi không được fail cứng: trả lời bằng text thường
        answered = await _fallback_plain_reply(user_message, history_text, planner)
        if not answered:
            store.add_chat(
                "conan",
                "Xin lỗi, model planner đang trả về dữ liệu không hợp lệ nên tôi chưa lập được kế hoạch. "
                f"Thử gửi lại, hoặc đổi model Planner trong Settings.\nChi tiết: {e}",
            )
        return

    if decision.get("action") == "reply":
        store.add_chat("conan", decision.get("message", "(không có nội dung)"))
        return

    # action == plan: tạo task cha + subtask chain có dependency
    tinfo = decision.get("task", {})
    subtasks_info = decision.get("subtasks", [])
    if not tinfo.get("title") or not subtasks_info:
        store.add_chat("conan", decision.get("reply") or "Tôi chưa đủ thông tin để lập kế hoạch — bạn mô tả rõ hơn được không?")
        return

    # Cứng: loại subtask QA/Security khỏi plan — hệ thống tự chạy sau khi build xong
    subtasks_info = _filter_build_only_subtasks(subtasks_info)
    if not subtasks_info:
        store.add_chat(
            "conan",
            decision.get("reply")
            or "Kế hoạch chỉ toàn bước QA/review — cần ít nhất một subtask build (Kid/Agasa). Bạn mô tả lại yêu cầu?",
        )
        return

    # Ưu tiên project đang chọn trên UI; không tạo project mới mỗi lần chat
    from ..paths import is_plausible_fs_path

    planner_dir = (tinfo.get("project_dir") or "").strip()
    if planner_dir and not is_plausible_fs_path(planner_dir):
        planner_dir = ""
    msg_explicit = forced_dir or extract_target_dir(user_message) or planner_dir
    if active:
        proj = app_settings.get_project(active) or app_settings.upsert_project(active)
        project_slug = proj["slug"]
        project_dir, dir_reason = resolve_project_dir(
            slug=project_slug,
            explicit=msg_explicit,
            active_project_dir=proj.get("project_dir") or "",
            projects_root=app_settings.effective_projects_root(),
        )
    else:
        project_slug = tinfo.get("project") or _slug(tinfo["title"])
        project_dir, dir_reason = resolve_project_dir(
            slug=project_slug,
            explicit=msg_explicit,
            projects_root=app_settings.effective_projects_root(),
        )
        app_settings.upsert_project(project_slug, name=project_slug, project_dir=project_dir)

    try:
        Path(project_dir).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        fallback, dir_reason = resolve_project_dir(
            slug=project_slug,
            projects_root=app_settings.effective_projects_root(),
        )
        store.add_chat(
            "conan",
            f"Không tạo được thư mục `{project_dir}` ({e}). "
            f"Chuyển sang mặc định `{fallback}`.",
        )
        project_dir = fallback
        try:
            Path(project_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e2:
            store.add_chat("conan", f"Vẫn không tạo được thư mục project: {e2}")
            return
    app_settings.upsert_project(project_slug, project_dir=project_dir)

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
        store.add_chat(
            "conan",
            f"Đang clone `{git_url}` → `{project_dir}` ({dir_reason})…",
        )
        clone = git_ops.ensure_clone(git_url, project_dir)
        if not clone.get("ok"):
            store.add_chat(
                "conan",
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
            f"PIPELINE xong = install + build/start FE + start API (nếu có) + smoke http_get UI&API. "
            f"Không tự commit/push."
        )
        tinfo["description"] = (tinfo.get("description") or "") + git_note
    elif msg_explicit or not is_under_orchestrator(project_dir):
        store.add_chat("conan", f"Project dir: `{project_dir}` ({dir_reason}).")
    # Gắn steer từ từng link đã detect vào subtask
    for st in subtasks_info:
        agent = st.get("agent", "")
        tags = list(st.get("tags") or [])
        for t in extra_tags:
            if t not in tags:
                tags.append(t)
        steers = []
        for link in detected_links:
            if agent == "heiji" and link.get("steer_qa"):
                steers.append(link["steer_qa"])
            elif agent != "heiji" and link.get("steer_build"):
                steers.append(link["steer_build"])
        if steers:
            st["description"] = (st.get("description") or "") + "\n\n" + "\n".join(steers)
        st["tags"] = tags

    parent = store.create_task(
        title=tinfo["title"],
        description=tinfo.get("description", ""),
        project=project_slug,
        project_dir=project_dir,
        created_by="conan",
        tags=extra_tags,
    )
    store.set_status(parent.id, "in_progress", "conan")

    created: list[Task] = []
    for st in subtasks_info:
        agent = st.get("agent", "kid")
        if agent not in WORKER_KEYS:
            agent = "kid"
        sub = store.create_task(
            title=st.get("title", "Subtask"),
            description=st.get("description", ""),
            assignee=agent,
            project=project_slug,
            project_dir=project_dir,
            parent_id=parent.id,
            tags=st.get("tags", []),
            created_by="conan",
        )
        created.append(sub)
    for st, sub in zip(subtasks_info, created):
        for idx in st.get("depends_on", []):
            if isinstance(idx, int) and 0 <= idx < len(created) and created[idx].id != sub.id:
                store.add_dep(sub.id, created[idx].id, "blocks")

    store.add_event(
        parent.id, "conan", "comment",
        "Kế hoạch: " + "; ".join(f"Subtask #{i+1} ({s.id})→{s.assignee}" for i, s in enumerate(created)),
    )

    plan_lines = "\n".join(
        f"- Subtask #{i+1} ({s.id}) → {AGENTS[s.assignee].display}: {s.title}" for i, s in enumerate(created)
    )
    reply = decision.get("reply", "Đã lập kế hoạch.")
    store.add_chat("conan", f"{reply}\n\nKế hoạch ({parent.id} — project `{project_slug}`):\n{plan_lines}")


# ---------- Phase 5: closure ----------


def _collect_deliverables(subtasks: list[Task]) -> str:
    """Tổng hợp thông tin subtask và deliverable/comment mới nhất của từng subtask."""
    if not subtasks:
        return "(Không có subtask)"
    items = []
    for t in subtasks:
        events = store.list_events(t.id)
        comments = [ev.message for ev in events if ev.kind == "comment" and ev.message]
        latest = comments[-1] if comments else "(chưa có comment/báo cáo)"
        items.append(
            f"- Subtask {t.id} [{t.assignee or 'chưa gán'}] ({t.status}): {t.title}\n"
            f"  Deliverable / Báo cáo: {latest}"
        )
    return "\n\n".join(items)


def _qa_verdict(parent_id: str) -> tuple[str, str]:
    """Lấy verdict QA từ các comment của heiji (mới nhất trước). Trả về (PASS|FAIL|UNKNOWN, text)."""
    subtasks = store.list_tasks(parent_id=parent_id)
    qa_tasks = [t for t in subtasks if t.assignee == "heiji"]
    if not qa_tasks:
        # Nếu task không tạo Heiji subtask riêng -> cho phép Conan Final Review trực tiếp
        return "PASS", "(Không có Heiji subtask riêng)"

    newest_text = ""
    for qa in reversed(qa_tasks):
        for ev in reversed(store.list_events(qa.id)):
            if ev.agent != "heiji" or ev.kind != "comment":
                continue
            text = ev.message
            newest_text = newest_text or text
            up = text.upper()

            # Universal Safety Guard: Nếu báo cáo QA ghi nhận BẤT KỲ LỖI NÀO (UI, API, Console Error, 40x/50x, Lệch layout...) -> ÉP FAIL NGAY
            has_error = bool(re.search(
                r"(connection refused|502 bad|proxy failed|server not running|api error|port \d+ refused|"
                r"issues found|lỗi phát hiện|broken image|console error|404 not found|500 internal|"
                r"không chạy|chưa xong|bị lỗi|chưa khớp|mismatch|lệch layout|error:|exception:)",
                text, re.I
            ))
            if has_error and "NO ISSUES" not in up and "0 LỖI" not in up and "KHÔNG CÓ LỖI" not in up:
                return "FAIL", text

            if re.search(r"VERDICT:\s*PASS", up):
                return "PASS", text
            if re.search(r"VERDICT:\s*FAIL", up):
                return "FAIL", text
            if "FAIL" in up and "PASS" not in up and "NO FAIL" not in up and "WITHOUT FAIL" not in up:
                return "FAIL", text
            if any(k in up for k in ["PASS", "PASSED", "THÀNH CÔNG", "HOÀN THÀNH", "SUCCESS", "HOẠT ĐỘNG BÌNH THƯỜNG", "KHÔNG CÓ LỖI", "200 OK"]):
                return "PASS", text
    if newest_text:
        up_news = newest_text.upper()
        if "FAIL" not in up_news and any(k in up_news for k in ["OK", "SUCCESS", "CHECK", "200"]):
            return "PASS", newest_text
        return "UNKNOWN", newest_text
    return "UNKNOWN", "(chưa có báo cáo QA)"


def _critic_verdict(task_id: str, agent: str, heading: str) -> tuple[str, str]:
    """Parse PASS/FAIL từ comment của critic agent (Akai/Amuro). Trả về (PASS|FAIL|UNKNOWN, text)."""
    events = store.list_events(task_id)
    comments = [e for e in events if e.kind == "comment" and e.agent == agent]
    if not comments:
        return "UNKNOWN", ""
    text = comments[-1].message or ""
    up = text.upper()
    head = heading.upper()
    if f"{head} — PASS" in up or f"{head} - PASS" in up:
        return "PASS", text
    if f"{head} — FAIL" in up or f"{head} - FAIL" in up:
        return "FAIL", text
    if re.search(r"VERDICT:\s*PASS", up):
        return "PASS", text
    if re.search(r"VERDICT:\s*FAIL", up):
        return "FAIL", text
    return "UNKNOWN", text


def _ensure_parent_testing(parent: Task) -> None:
    if parent.status not in ("testing", "review", "done", "archived", "failed"):
        try:
            if parent.status == "in_progress":
                store.set_status(parent.id, "testing", "conan")
            elif parent.status == "backlog":
                store.set_status(parent.id, "in_progress", "conan")
                store.set_status(parent.id, "testing", "conan")
            parent.status = "testing"
        except Exception:
            pass


def _gate_critic_stage(
    parent: Task,
    *,
    agent: str,
    display: str,
    heading: str,
    task_title: str,
    task_description: str,
    task_tags: list[str],
    retry_tag: str,
    refail_tag_prefix: str,
    on_created_msg: str,
) -> str:
    """Một stage critic (Security/Pentest) dùng chung — tránh duplicate Akai/Amuro.

    Returns:
        "proceed" — stage này PASS
        "wait" — đã tạo/đang chờ subtask, requeue, hoặc đã giao bug
    """
    stage_tasks = [t for t in store.list_tasks(parent_id=parent.id) if t.assignee == agent]
    if not stage_tasks:
        created = store.create_task(
            title=task_title,
            description=task_description,
            assignee=agent,
            project=parent.project,
            project_dir=parent.project_dir,
            parent_id=parent.id,
            created_by="conan",
            tags=list(task_tags),
        )
        _ensure_parent_testing(parent)
        store.add_chat("conan", on_created_msg.format(id=created.id))
        return "wait"

    stage = stage_tasks[-1]
    if stage.status in ("backlog", "in_progress", "blocked"):
        return "wait"

    verdict, text = _critic_verdict(stage.id, agent, heading)
    if verdict == "UNKNOWN" and retry_tag not in (stage.tags or []):
        tags = list(stage.tags or [])
        tags.append(retry_tag)
        store.update_task_fields(stage.id, tags=tags)
        store.set_status(stage.id, "in_progress", "conan")
        store.set_status(stage.id, "backlog", "conan")
        store.add_event(
            stage.id, "conan", "system",
            f"Báo cáo {display} chưa có PASS/FAIL rõ — {display} chạy lại.",
        )
        store.add_chat("conan", f"{parent.id}: {display} chưa có verdict rõ — requeue.")
        return "wait"

    if verdict == "FAIL":
        open_bugs = _open_related_bugs(parent)
        if open_bugs:
            n = _assign_bugs_to_fixer(parent, open_bugs)
            if n < 0:
                store.set_status(parent.id, "blocked", "conan")
                store.add_chat(
                    "conan",
                    f"{parent.id}: {display} FAIL + còn bug sau {MAX_FIX_ROUNDS} round — cần bạn xem board.",
                )
                return "wait"
            store.add_chat(
                "conan",
                f"{parent.id}: {display} FAIL — giao fixer "
                f"{', '.join(b.id for b in open_bugs)} (round {n}).",
            )
            return "wait"
        tag = f"{refail_tag_prefix}-{_fix_rounds(parent) + 1}"
        if tag not in (stage.tags or []):
            tags = list(stage.tags or [])
            tags.append(tag)
            store.update_task_fields(stage.id, tags=tags)
            store.set_status(stage.id, "in_progress", "conan")
            store.set_status(stage.id, "backlog", "conan")
            store.add_event(
                stage.id, "conan", "system",
                f"{display} FAIL nhưng chưa có bug mở — {display} phải create_bug_ticket rồi FAIL lại.\n"
                f"{text[:2000]}",
            )
            store.add_chat("conan", f"{parent.id}: {display} FAIL — trả {display} tạo bug ticket.")
            return "wait"
        store.set_status(parent.id, "blocked", "conan")
        store.add_chat("conan", f"{parent.id}: {display} FAIL kéo dài — dừng, cần bạn xem board.")
        return "wait"

    if verdict != "PASS":
        return "wait"
    return "proceed"


def _gate_security_pentest(parent: Task, subtasks: list[Task]) -> str:
    """Gate tuần tự Akai → Amuro trước Final Review (2 lần gọi _gate_critic_stage)."""
    preview_url = f"{config.BASE_URL}/preview/{parent.project}/"

    sec = _gate_critic_stage(
        parent,
        agent="akai",
        display="Akai",
        heading="SECURITY REVIEW",
        task_title=f"Security Review — {parent.title}",
        task_description=(
            f"Review bảo mật cho {parent.id}. Không sửa code, chỉ báo cáo.\n"
            f"Preview URL: {preview_url}\n"
            "Kết thúc bằng post_message '## Security Review — PASS' hoặc "
            "'## Security Review — FAIL' (+ create_bug_ticket cho Critical/High)."
        ),
        task_tags=["security-review"],
        retry_tag="sec-retry",
        refail_tag_prefix="resec",
        on_created_msg=(
            f"{parent.id}: QA PASS — giao Akai Security Review ({{id}}) trước Final Review."
        ),
    )
    if sec != "proceed":
        return sec

    return _gate_critic_stage(
        parent,
        agent="amuro",
        display="Amuro",
        heading="PENETRATION TEST",
        task_title=f"Penetration Test — {parent.title}",
        task_description=(
            f"Pentest preview URL của {parent.id}.\n"
            f"Preview URL: {preview_url}\n"
            "CHỈ tấn công URL preview/staging được cấp. Không sửa source.\n"
            "Kết thúc bằng post_message '## Penetration Test — PASS' hoặc "
            "'## Penetration Test — FAIL' (+ create_bug_ticket)."
        ),
        task_tags=["penetration-test"],
        retry_tag="pen-retry",
        refail_tag_prefix="repen",
        on_created_msg=(
            f"{parent.id}: Security PASS — giao Amuro Pentest ({{id}}) trước Final Review."
        ),
    )


def _parse_conan_verdict(result: str) -> bool:
    """True nếu Final Review APPROVED. Ưu tiên dòng VERDICT:; REJECTED thắng nếu cùng có."""
    up = (result or "").upper()
    for line in up.splitlines()[:20]:
        if "VERDICT:" not in line:
            continue
        if "REJECTED" in line:
            return False
        if "APPROVED" in line:
            return True
    if re.search(r"VERDICT:\s*REJECTED", up):
        return False
    if re.search(r"VERDICT:\s*APPROVED", up):
        return True
    # Fallback: có APPROVED và không có REJECTED
    return "APPROVED" in up and "REJECTED" not in up


def _open_related_bugs(parent: Task) -> list[Task]:
    """Danh sách bug đang mở của task."""
    under = store.list_tasks(
        parent_id=parent.id,
        type="bug",
        status=["backlog", "in_progress", "blocked"],
    )
    if under:
        return under
    bugs = store.list_tasks(type="bug", status=["backlog", "in_progress", "blocked"])
    return [b for b in bugs if b.project == parent.project]


MAX_FIX_ROUNDS = 3


def _fix_rounds(parent: Task) -> int:
    return sum(1 for t in parent.tags if t.startswith("fix-round"))


def _has_bug_tickets(parent: Task) -> bool:
    return bool(store.list_tasks(parent_id=parent.id, type="bug"))


def _fixer_for_bug(bug: Task) -> str:
    """Chọn fixer theo tag area-*; bug cũ không có tag → kid (giữ hành vi lịch sử)."""
    tags = bug.tags or []
    if "area-backend" in tags:
        return "agasa"
    if "area-frontend" in tags:
        return "kid"
    return "kid"


def _assign_bugs_to_fixer(parent: Task, bugs: list[Task]) -> int:
    """Giao bug cho Kid (frontend) hoặc Agasa (backend) theo tag area-*."""
    rounds = _fix_rounds(parent)
    if rounds >= MAX_FIX_ROUNDS:
        return -1
    store.update_task_fields(parent.id, tags=[*parent.tags, f"fix-round-{rounds + 1}"])
    for bug in bugs:
        fixer = _fixer_for_bug(bug)
        store.update_task_fields(bug.id, assignee=fixer, parent_id=parent.id)
        if bug.status in ("blocked", "failed", "testing", "review", "done"):
            try:
                store.set_status(bug.id, "backlog", "conan")
            except Exception:
                store.set_status(bug.id, "in_progress", "conan")
                store.set_status(bug.id, "backlog", "conan")
        store.add_event(
            bug.id, "conan", "system",
            f"FAIL — giao {fixer} fix (round {rounds + 1}).",
        )
    if parent.status in ("blocked", "failed", "testing", "review", "backlog"):
        try:
            store.set_status(parent.id, "in_progress", "conan")
        except Exception:
            store.set_status(parent.id, "backlog", "conan")
            store.set_status(parent.id, "in_progress", "conan")
    return rounds + 1


def _return_to_qa_for_bugs(qa: Task, parent: Task, notes: str, mark_tag: str, chat: str) -> None:
    """Conan/ hệ thống không tạo bug — trả Heiji để create_bug_ticket rồi fixer xử lý."""
    detail = (notes or "")[:3500]
    store.add_event(
        qa.id, "conan", "system",
        f"{mark_tag}\nBẮT BUỘC: với mỗi lỗi bên dưới gọi create_bug_ticket "
        f"(area=frontend→Kid / area=backend→Agasa), "
        f"rồi VERDICT: FAIL. Không PASS khi còn lỗi.\n\n{detail}",
    )
    _requeue_qa(
        qa, mark_tag,
        "Trả về QA: phải create_bug_ticket cho từng lỗi (Conan không tạo bug).",
        chat,
    )


def _requeue_qa(qa: Task, mark_tag: str, reason: str, chat_msg: str) -> None:
    tags = list(qa.tags or [])
    if mark_tag not in tags:
        tags.append(mark_tag)
    store.update_task_fields(qa.id, tags=tags)
    store.set_status(qa.id, "in_progress", "conan")
    store.set_status(qa.id, "backlog", "conan")
    store.add_event(qa.id, "conan", "system", reason)
    store.add_chat("conan", chat_msg)


async def check_parent_progress(parent_id: str) -> None:
    """Conan Lifecycle Supervisor — Kiểm tra & cập nhật tiến độ toàn bộ vòng đời subtask -> parent task."""
    parent = store.get_task(parent_id)
    if not parent or parent.status in ("done", "archived"):
        return
    subtasks = store.list_tasks(parent_id=parent_id)
    if not subtasks:
        return

    # 1. Cập nhật real-time trạng thái task cha dựa vào tiến trình các subtask
    # Coder (Kid/Agasa) đang viết code / fix bug -> cột In Progress
    has_coder_working = any(
        (t.status == "in_progress" and t.assignee in ("kid", "agasa")) or
        (t.type == "bug" and t.status in ("backlog", "in_progress"))
        for t in subtasks
    )
    # Heiji/Akai/Amuro đang critic hoặc subtask ở bước testing -> cột In Testing / QA
    critic_agents = ("heiji", "akai", "amuro", "haibara")
    has_testing = any(
        t.status == "testing" or (t.status == "in_progress" and t.assignee in critic_agents)
        for t in subtasks
    )
    has_blocked = any(t.status == "blocked" for t in subtasks)

    if parent.status not in ("blocked", "failed"):
        if has_coder_working and parent.status != "in_progress":
            store.set_status(parent.id, "in_progress", "conan")
            parent.status = "in_progress"
        elif not has_coder_working and has_testing and parent.status != "testing":
            store.set_status(parent.id, "testing", "conan")
            parent.status = "testing"

    if has_blocked and parent.status != "blocked":
        store.set_status(parent.id, "blocked", "conan")
        parent.status = "blocked"

    # Tự động gỡ blocked cho parent khi không còn subtask blocked (trừ khi Operator chủ động block)
    if parent.status == "blocked":
        parent_events = store.list_events(parent.id)
        operator_blocked = any(
            e.agent == "operator"
            and ("blocked" in e.message.lower() or "dừng" in e.message.lower())
            for e in parent_events[-15:]
        )
        if operator_blocked:
            # Operator block → giữ blocked, không spam chat / không chạy closure
            for st in subtasks:
                if st.status not in ("done", "archived", "blocked"):
                    try:
                        store.set_status(st.id, "blocked", "operator")
                    except Exception:
                        pass
            return

        if not has_blocked:
            if has_coder_working:
                new_st = "in_progress"
            elif has_testing:
                new_st = "testing"
            else:
                new_st = "testing"
            store.set_status(parent.id, new_st, "conan")
            parent.status = new_st
            log.info("Auto-unblock: %s không còn subtask blocked — chuyển về %s", parent.id, new_st)

    # Parent đang blocked hoặc failed → giữ nguyên chờ can thiệp (không spam chat)
    if parent.status in ("blocked", "failed"):
        return

    # 2. Nếu còn subtask ở backlog, in_progress, hoặc blocked -> chưa đủ điều kiện closure
    if any(t.status in ("backlog", "in_progress", "blocked") for t in subtasks):
        return

    # Fix round: bug do QA tạo → giao fixer theo area (Conan không tạo bug)
    open_bugs = _open_related_bugs(parent)
    if open_bugs:
        n = _assign_bugs_to_fixer(parent, open_bugs)
        if n < 0:
            store.set_status(parent_id, "blocked", "conan")
            store.add_chat(
                "conan",
                f"{parent.id} vẫn còn {len(open_bugs)} bug mở sau {MAX_FIX_ROUNDS} fix round "
                f"({', '.join(b.id for b in open_bugs)}) — dừng tự động, cần bạn xem trên board.",
            )
            return
        store.add_chat(
            "conan",
            f"QA đã tạo {len(open_bugs)} bug ở {parent.id} — fix round {n}: "
            + ", ".join(f"{b.id}→{_fixer_for_bug(b)}" for b in open_bugs)
            + " → rồi Heiji QA lại (chưa tới Conan).",
        )
        return

    await _closure(parent, subtasks)


async def _closure(parent: Task, subtasks: list[Task]) -> None:
    """Phase 5: QA PASS → Haibara → Akai → Amuro → Conan Final Review. FAIL → bug/Kid."""
    verdict, qa_text = _qa_verdict(parent.id)

    qa_tasks = [t for t in subtasks if t.assignee == "heiji"]
    qa = qa_tasks[-1] if qa_tasks else None
    rounds = _fix_rounds(parent)

    # QA chưa có verdict rõ → bắt Heiji chạy lại (chưa tới Conan)
    if verdict == "UNKNOWN" and qa and qa.status == "testing" and "qa-retry" not in qa.tags:
        _requeue_qa(
            qa, "qa-retry",
            "Báo cáo QA chưa có verdict PASS/FAIL rõ ràng — requeue để Heiji chạy lại.",
            f"Báo cáo QA của {qa.id} chưa rõ — Heiji QA lại trước khi Conan review {parent.id}.",
        )
        return

    # ===== QA FAIL: không gọi Conan. Bug do QA tạo → fixer theo area; thiếu bug → trả QA =====
    if verdict == "FAIL":
        open_bugs = _open_related_bugs(parent)
        if open_bugs:
            n = _assign_bugs_to_fixer(parent, open_bugs)
            if n < 0:
                store.set_status(parent.id, "blocked", "conan")
                store.add_chat(
                    "conan",
                    f"{parent.id}: QA FAIL + còn bug mở sau {MAX_FIX_ROUNDS} round — cần bạn xem board.",
                )
                return
            store.add_chat(
                "conan",
                f"{parent.id}: QA FAIL — giao fixer "
                f"{', '.join(f'{b.id}→{_fixer_for_bug(b)}' for b in open_bugs)} "
                f"(round {n}). Conan chỉ review sau khi QA PASS.",
            )
            return

        if qa and not _has_bug_tickets(parent) and "qa-must-file-bugs" not in qa.tags:
            _return_to_qa_for_bugs(
                qa, parent, qa_text,
                "qa-must-file-bugs",
                f"{parent.id}: Heiji VERDICT FAIL nhưng chưa create_bug_ticket — "
                f"trả QA tạo bug (area frontend/backend) — Conan chưa vào.",
            )
            return

        # Đã có bug (đã fix xong) hoặc đã nhắc tạo bug → re-QA
        if qa and f"reqa-{max(rounds, 1)}" not in qa.tags:
            _requeue_qa(
                qa, f"reqa-{max(rounds, 1)}",
                "QA từng FAIL — requeue Heiji verify lại sau khi fixer xong (trước Conan).",
                f"Bug/fix ở {parent.id} xong — Heiji QA lại. Chỉ khi PASS mới tới Conan.",
            )
            return

        store.set_status(parent.id, "blocked", "conan")
        store.add_chat(
            "conan",
            f"{parent.id}: QA FAIL kéo dài sau {MAX_FIX_ROUNDS} vòng — dừng, cần bạn xem board.\n"
            f"QA: {qa_text[:500]}",
        )
        return

    # Chỉ PASS mới tới Conan
    if verdict != "PASS":
        tag = f"warn-no-pass-{verdict}"
        if tag not in parent.tags:
            store.add_chat(
                "conan",
                f"{parent.id}: chưa có QA PASS (verdict={verdict}) — chưa tới Final Review.",
            )
            store.update_task_fields(parent.id, tags=[*parent.tags, tag])
        return

    # Haibara tổng hợp (QA đã PASS) — chỉ chạy một lần
    events = store.list_events(parent.id)
    has_haibara_comment = any(e.agent == "haibara" and e.kind == "comment" for e in events)
    if not has_haibara_comment:
        try:
            haibara = AGENTS["haibara"]
            deliverables = _collect_deliverables(subtasks)
            haibara_res = await run_agent(
                "haibara",
                haibara.system_prompt(),
                f"Task cha {parent.id}: {parent.title}\n\nDeliverable các subtask:\n{deliverables}\n\n"
                f"QA verdict: PASS\n{qa_text[:2000]}\n\n"
                "Hãy post_message lên task hiện tại báo cáo QA Complete:\n"
                "- Tiêu đề: '## QA Complete — PASS'\n"
                "- Tóm tắt: deliverable build, Live URL, screenshot links từ Heiji, CSS checks.\n"
                "- Khuyến nghị: sẵn sàng Security (Akai) → Pentest (Amuro) → Conan Final Review.\n"
                "Rồi trả lời text ngắn.",
                parent,
                haibara.tools,
                max_iterations=6,
            )
            if haibara_res and not haibara_res.startswith("[Tiến trình"):
                events = store.list_events(parent.id)
                has_haibara_comment = any(e.agent == "haibara" and e.kind == "comment" for e in events)
                if not has_haibara_comment:
                    store.add_event(parent.id, "haibara", "comment", haibara_res)
        except Exception:
            log.exception("Haibara summary failed (non-blocking)")

    # Akai Security → Amuro Pentest (tuần tự) trước Conan Final Review
    if _gate_security_pentest(parent, subtasks) != "proceed":
        return

    # Conan Final Review (chỉ sau QA PASS + Security PASS + Pentest PASS)
    conan = AGENTS["conan"]
    preview_url = f"{config.BASE_URL}/preview/{parent.project}/"
    try:
        result = await run_agent(
            "conan",
            conan.system_prompt(),
            CLOSURE_VERIFY_PROMPT.format(
                title=parent.title,
                description=parent.description[:1500],
                deliverables=_collect_deliverables(subtasks),
                qa_verdict=f"PASS\n{qa_text[:1500]}",
                preview_url=preview_url,
            ),
            parent,
            conan.tools,
            max_iterations=16,
        )
    except Exception as e:
        log.exception("Conan closure verify failed")
        err_str = str(e)
        if "429" in err_str or "Rate limit" in err_str or "FreeUsageLimitError" in err_str or "LLMError" in str(type(e)):
            log.warning("Conan closure hit LLM Rate Limit / Network flake — keeping task for auto-retry without blocking")
            store.add_event(parent.id, "conan", "system", f"API LLM tạm nghẽn ({err_str[:150]}) — giữ task chờ auto-retry, không khóa blocked.")
            return
        store.set_status(parent.id, "blocked", "conan")
        store.add_chat("conan", f"Không thể verify {parent.id} do lỗi: {e}. Task chuyển sang blocked.")
        return

    approved = _parse_conan_verdict(result)
    store.add_event(parent.id, "conan", "comment", f"Final Review\n\n{result[:6000]}")

    if not approved:
        # Conan REJECT — Tự động tạo Bug Subtask cho Kid fix + trả Heiji re-QA
        head = "\n".join(result.strip().splitlines()[:12])[:900]
        if rounds >= MAX_FIX_ROUNDS:
            store.set_status(parent.id, "blocked", "conan")
            store.add_chat(
                "conan",
                f"Final review {parent.id}: REJECTED sau {rounds}/{MAX_FIX_ROUNDS} round — cần bạn xem board.\n\n{head}",
            )
            return

        if not qa:
            # Nếu chưa có Heiji QA subtask, tự tạo QA task
            qa = store.create_task(
                title=f"QA re-verify {parent.title}",
                description=f"Auto QA task for {parent.id} after Final Review REJECTED",
                type="task",
                assignee="heiji",
                project=parent.project,
                project_dir=parent.project_dir,
                parent_id=parent.id,
            )

        # Tự động tạo Bug ticket gắn cho Kid fix lỗi từ Final Review
        bug = store.create_task(
            title=f"Fix API/UI issue from Final Review: {parent.title}",
            description=f"Lỗi phát hiện trong Final Review:\n\n{result[:1500]}",
            type="bug",
            assignee="kid",
            project=parent.project,
            project_dir=parent.project_dir,
            parent_id=parent.id,
            status="backlog",
        )
        store.add_event(
            parent.id, "conan", "system",
            f"Tự động tạo Bug Task #{bug.id} cho Kid fix lỗi từ Final Review."
        )

        tag = f"reqa-after-reject-{rounds + 1}"
        if tag in (qa.tags or []):
            store.set_status(parent.id, "blocked", "conan")
            store.add_chat(
                "conan",
                f"Final review {parent.id}: REJECTED lặp lại — dừng.\n\n{head}",
            )
            return

        _return_to_qa_for_bugs(
            qa, parent, result, tag,
            f"Final review {parent.id}: REJECTED — Đã tự động tạo Bug #{bug.id} cho Kid fix → Heiji QA PASS rồi Conan review lại.\n\n{head}",
        )
        store.update_task_fields(parent.id, tags=[*parent.tags, f"fix-round-{rounds + 1}"])
        if parent.status != "in_progress":
            try:
                store.set_status(parent.id, "in_progress", "conan")
            except Exception:
                pass
        return

    # APPROVED — đóng
    for t in subtasks:
        if t.status == "testing":
            store.set_status(t.id, "done", "conan")
    # đóng luôn bug đã xong
    for b in store.list_tasks(parent_id=parent.id, type="bug"):
        if b.status == "testing":
            store.set_status(b.id, "done", "conan")

    # Tự động dọn dẹp các file .bak, .tmp, test script tạm tạo trong quá trình agent làm việc
    _cleanup_temp_bak_files(parent)

    if parent.review_type == "operator":
        store.set_status(parent.id, "testing", "conan")
        store.set_status(parent.id, "review", "conan")
        store.add_chat(
            "conan",
            f"{parent.id} QA PASS + Final Review APPROVED, chờ operator Approve.\n"
            f"🔗 {preview_url}",
        )
    else:
        store.set_status(parent.id, "testing", "conan")
        store.set_status(parent.id, "done", "conan")
        store.add_chat(
            "conan",
            f"Hoàn tất {parent.id} — {parent.title}.\n"
            f"🔗 Live URL: {preview_url}\n\n" + "\n".join(result.strip().splitlines()[:8])[:800],
        )

    await _phase6_memorize(parent, result)

def _cleanup_temp_bak_files(parent: Task) -> None:
    """Tự động dọn dẹp các file rác .bak, .tmp, test-script tạm tạo trong quá trình agent debug/fix bug."""
    import os
    from pathlib import Path
    from ..paths import is_plausible_fs_path

    dirs_to_clean = []
    if parent.project_dir and is_plausible_fs_path(parent.project_dir):
        dirs_to_clean.append(Path(parent.project_dir))

    # Dọn dẹp cả trong thư mục Orchestrator routes nếu có patch/bak tạm
    orch_routes = config.WORKSPACE_DIR / "orchestrator" / "routes"
    if orch_routes.exists():
        dirs_to_clean.append(orch_routes)

    for pdir in dirs_to_clean:
        if not pdir.is_dir():
            continue
        try:
            for file_path in pdir.rglob("*"):
                if not file_path.is_file():
                    continue
                name = file_path.name.lower()
                # Tự động dọn file .bak*, *.tmp, patch_*, verify_*
                if (
                    ".bak" in name
                    or name.endswith(".tmp")
                    or (name.startswith("patch_") and name.endswith(".py"))
                    or (name.startswith("verify_") and name.endswith(".py"))
                    or "diag.py" in name
                ):
                    try:
                        file_path.unlink(missing_ok=True)
                        log.info("Auto-cleaned temp backup file: %s", file_path)
                    except Exception as e:
                        log.warning("Could not auto-clean file %s: %s", file_path, e)
        except Exception as e:
            log.warning("Error scanning for cleanup in %s: %s", pdir, e)


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
        store.add_event(parent.id, "conan", "system", "Phase 6: đã cập nhật memory/wiki.")
    except Exception:
        log.exception("Phase 6 memorize failed (non-blocking)")
