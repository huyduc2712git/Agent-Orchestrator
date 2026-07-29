"""Scheduler — Phase 3+4: chạy subtask khi dependency đã xong, không chờ đồng bộ."""
import asyncio
import logging
from datetime import datetime, timezone

from .. import config
from ..agents.registry import AGENTS, WORKER_KEYS
from ..agents.runtime import run_agent
from ..board import store
from ..board.models import Task
from . import orchestrator

log = logging.getLogger("scheduler")

_in_flight: set[str] = set()
_semaphore: asyncio.Semaphore | None = None
_task_retry_counts: dict[str, int] = {}
_last_auto_check_time: float = 0.0


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

    if task.assignee == "hawkeye":
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
            "create_bug_ticket kèm repro + hướng fix (bắt buộc khi FAIL) — KHÔNG PASS khi còn lỗi. "
            "Jarvis không tạo bug; chỉ Final Review sau khi bạn PASS.",
            "2. figma_get nếu description có link Figma — lấy màu/font/layout spec.",
            "3. screenshot_url: desktop top + mobile top + ít nhất 1 interaction shot (tab click).",
            "4. inspect_render: chạy CSS/RENDER VERIFICATION table (brand_hex, body_bg_hex từ Figma nếu có).",
            "5. compare_image nếu có file reference PNG trong project (vd mockup/, reference/).",
            "6. post_message 'Visual QA Report' với screenshot view_url links + bảng checks "
            "+ bảng API checks (URL → status) gồm cả same-origin.",
            "7. VERDICT: PASS hoặc VERDICT: FAIL — kèm evidence, không khẳng định suông.",
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

    if task.assignee in ("stark", "banner"):
        parts += [
            "",
            "=== KHI PHÁT HIỆN LỖI (Stark/Banner) ===",
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
            store.set_status(task.id, "in_progress", task.assignee)
            log.info("Start %s -> %s (%s)", task.id, task.assignee, task.title)
            result = await run_agent(
                task.assignee,
                agent.system_prompt(),
                _build_worker_prompt(task),
                task,
                agent.tools,
            )
            store.add_event(task.id, task.assignee, "comment", result[:4000])
            store.set_status(task.id, "testing", task.assignee)
        except Exception as e:
            log.exception("Worker %s failed on %s", task.assignee, task.id)
            store.set_status(task.id, "blocked", task.assignee)
            store.add_event(task.id, "system", "system", f"Agent gặp lỗi: {e}")
            store.add_chat("jarvis", f"⚠️ {task.id} ({task.title}) bị blocked do lỗi: {str(e)[:200]}")
        finally:
            _in_flight.discard(task.id)

    if task.parent_id:
        try:
            await orchestrator.check_parent_progress(task.parent_id)
        except Exception:
            log.exception("check_parent_progress failed for %s", task.parent_id)


def auto_recover_stuck_and_blocked_tasks() -> None:
    """Jarvis Auto-Recovery Patrol — Quét định kỳ mỗi 2 phút:
    1. Reset subtask/task bị in_progress mà không nằm trong _in_flight (bị kẹt tiến trình).
    2. Tự động rerun subtask/task bị blocked (tối đa 3 lần retry).
    """
    now_utc = datetime.now(timezone.utc)

    # 1. Quét toàn bộ task/subtask in_progress bị kẹt không có worker thread thực thi
    in_prog = store.list_tasks(status=["in_progress"])
    for t in in_prog:
        # Task cha có subtasks -> chỉ là container chờ subtask chạy xong, không có worker riêng trong _in_flight
        is_parent = not t.parent_id and bool(store.list_tasks(parent_id=t.id))
        if is_parent:
            continue

        if t.id not in _in_flight:
            try:
                updated_dt = datetime.fromisoformat(t.updated_at)
                if (now_utc - updated_dt).total_seconds() > 120:
                    log.info("Jarvis Auto-Recovery: Resetting stuck in_progress task %s (%s) -> backlog", t.id, t.title)
                    store.add_event(t.id, "jarvis", "system", "Jarvis Auto-Recovery: Phát hiện task bị kẹt tiến trình -> Tự động khôi phục chạy lại.")
                    store.set_status(t.id, "backlog", "jarvis")
                    store.add_chat("jarvis", f"🔄 Jarvis Auto-Recovery: Tự động kích hoạt lại {t.id} ({t.title}) do bị dừng tiến trình.")
            except Exception:
                pass

    # 2. Quét task/subtask bị blocked để tự động rerun (tối đa 3 lần)
    # Parent bị REJECTED do QA FAIL: KHÔNG auto-rerun closure — cần fix code trước.
    blocked_tasks = store.list_tasks(status=["blocked"])
    for t in blocked_tasks:
        is_parent = not t.parent_id and bool(store.list_tasks(parent_id=t.id))
        if is_parent:
            # Parent blocked: nếu Final Review mới nhất đã APPROVED → đóng luôn (đừng kẹt vì QA FAIL cũ)
            events = store.list_events(t.id)
            final_blobs = [
                e.message.upper()
                for e in events[-30:]
                if e.agent == "jarvis" and "FINAL REVIEW" in e.message.upper()
            ]
            if any(orchestrator._parse_jarvis_verdict(m) for m in final_blobs):
                log.info("Auto-Recovery: %s có Final Review APPROVED — đóng task thay vì giữ blocked", t.id)
                for st in store.list_tasks(parent_id=t.id):
                    if st.status in ("testing", "review"):
                        store.set_status(st.id, "done", "jarvis")
                    elif st.status in ("blocked", "failed", "backlog", "in_progress"):
                        # về testing rồi done (state machine không cho blocked→done trực tiếp)
                        if st.status in ("blocked", "failed"):
                            store.set_status(st.id, "backlog", "jarvis")
                        if store.get_task(st.id).status == "backlog":
                            store.set_status(st.id, "in_progress", "jarvis")
                        cur = store.get_task(st.id)
                        if cur and cur.status == "in_progress":
                            store.set_status(st.id, "testing", "jarvis")
                        store.set_status(st.id, "done", "jarvis")
                # Parent: blocked → backlog → in_progress → testing → done
                store.set_status(t.id, "backlog", "jarvis")
                store.set_status(t.id, "in_progress", "jarvis")
                store.set_status(t.id, "testing", "jarvis")
                store.set_status(t.id, "done", "jarvis")
                store.add_event(
                    t.id, "jarvis", "system",
                    "Auto-Recovery: Final Review đã APPROVED — đóng task (bỏ qua QA FAIL cũ).",
                )
                store.add_chat(
                    "jarvis",
                    f"✅ {t.id}: Final Review đã APPROVED nhưng task bị kẹt blocked do QA FAIL cũ — đã đóng task.",
                )
                continue

            blobs = [e.message.upper() for e in events[-20:]]
            # Hawkeye FAIL nằm trên subtask testing — check luôn children
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
                if _task_retry_counts.get(t.id, 0) < 3:
                    _task_retry_counts[t.id] = 3  # chặn vòng auto-retry vô ích
                    store.add_event(
                        t.id, "jarvis", "system",
                        "Auto-Recovery: bỏ qua auto-retry — QA/Final review đã FAIL. "
                        "Cần builder fix rồi bấm '↺ Chạy lại'.",
                    )
                    store.add_chat(
                        "jarvis",
                        f"⛔ {t.id} bị blocked vì QA/Review FAIL — không tự chạy lại closure. "
                        f"Sửa code (hoặc giao lại fix), rồi bấm '↺ Chạy lại' trên board.",
                    )
                continue

        retries = _task_retry_counts.get(t.id, 0)
        if retries < 3:
            _task_retry_counts[t.id] = retries + 1
            log.info("Jarvis Auto-Recovery: Rerunning blocked task %s (%s) — Retry %s/3", t.id, t.title, retries + 1)
            store.add_event(t.id, "jarvis", "system", f"Jarvis Auto-Recovery: Tự động chạy lại task bị blocked (Lần retry {retries + 1}/3).")
            store.set_status(t.id, "backlog", "jarvis")
            store.add_chat("jarvis", f"🔄 Jarvis Auto-Recovery: Task {t.id} ({t.title}) bị kẹt/lỗi -> Tự động chạy lại lần {retries + 1}/3.")
        elif retries == 3:
            _task_retry_counts[t.id] = 4  # Đánh dấu đã thông báo
            store.set_status(t.id, "failed", "jarvis")
            store.add_chat("jarvis", f"⛔ Task {t.id} ({t.title}) đã fail 3 lần. Dừng tự động chạy lại. Task được đưa vào trạng thái Failed (thất bại).")
            log.warning("Task %s reached max retries (3) and is failed.", t.id)

            # Nếu là task cha, huỷ luôn các task con chưa hoàn thành
            if not t.parent_id:
                subtasks = store.list_tasks(parent_id=t.id)
                for st in subtasks:
                    if st.status not in ("done", "archived", "failed"):
                        store.set_status(st.id, "failed", "jarvis")
                        store.add_event(st.id, "jarvis", "system", f"Task cha {t.id} đã thất bại, subtask tự động bị huỷ.")

    # 3. Jarvis kiểm tra toàn bộ tiến độ vòng đời task cha & tự động trigger closure khi subtasks xong
    parent_tasks = [t for t in store.list_tasks(include_archived=False) if not t.parent_id and t.status not in ("done", "archived", "failed")]
    for pt in parent_tasks:
        try:
            asyncio.create_task(orchestrator.check_parent_progress(pt.id))
        except Exception:
            pass


async def scheduler_loop() -> None:
    """Quét board định kỳ, spawn agent cho task đủ điều kiện chạy."""
    global _semaphore, _last_auto_check_time
    _semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_AGENTS)
    log.info("Scheduler started")

    # Khôi phục các subtask in_progress bị mồ côi do server restart
    try:
        orphaned = [t for t in store.list_tasks(status=["in_progress"])]
        for ot in orphaned:
            log.info("Resetting orphaned in_progress task %s -> backlog for auto-resumption", ot.id)
            store.set_status(ot.id, "backlog", "system")
    except Exception:
        log.exception("Failed to reset orphaned in_progress tasks")

    while True:
        try:
            current_time = asyncio.get_event_loop().time()
            if current_time - _last_auto_check_time > 120:  # Quét mỗi 2 phút
                _last_auto_check_time = current_time
                auto_recover_stuck_and_blocked_tasks()

            candidates = store.list_tasks(status=["backlog"])
            for t in candidates:
                if t.assignee not in WORKER_KEYS or t.id in _in_flight:
                    continue
                if not store.deps_satisfied(t.id):
                    continue
                _in_flight.add(t.id)
                asyncio.create_task(_run_worker(t))
        except Exception:
            log.exception("Scheduler tick failed")
        await asyncio.sleep(config.SCHEDULER_INTERVAL_SECONDS)
