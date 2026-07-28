"""Scheduler — Phase 3+4: chạy subtask khi dependency đã xong, không chờ đồng bộ."""
import asyncio
import logging

from .. import config
from ..agents.registry import AGENTS, WORKER_KEYS
from ..agents.runtime import run_agent
from ..board import store
from ..board.models import Task
from . import orchestrator

log = logging.getLogger("scheduler")

_in_flight: set[str] = set()
_semaphore: asyncio.Semaphore | None = None


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
            "2. figma_get nếu description có link Figma — lấy màu/font/layout spec.",
            "3. screenshot_url: desktop top + mobile top + ít nhất 1 interaction shot (tab click).",
            "4. inspect_render: chạy CSS/RENDER VERIFICATION table (brand_hex, body_bg_hex từ Figma nếu có).",
            "5. compare_image nếu có file reference PNG trong project (vd mockup/, reference/).",
            "6. post_message 'Visual QA Report' với screenshot view_url links + bảng checks.",
            "7. VERDICT: PASS hoặc VERDICT: FAIL — kèm evidence, không khẳng định suông.",
        ]
    if "git-repo" in (task.tags or []) or "github" in (task.tags or []) or "gitlab" in (task.tags or []):
        parts += [
            "",
            "=== GIT WORKSPACE ===",
            "Project này gắn với GitHub/GitLab. Dùng git_status trước khi sửa code.",
            "Code trên repo đã clone — không tạo tree file song song ngoài repo.",
            "Commit: run_command git add / git commit. Push chỉ khi user yêu cầu.",
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


async def scheduler_loop() -> None:
    """Quét board định kỳ, spawn agent cho task đủ điều kiện chạy."""
    global _semaphore
    _semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_AGENTS)
    log.info("Scheduler started")
    while True:
        try:
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
