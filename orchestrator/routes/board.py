"""Board & Tasks CRUD API routes."""
import asyncio
import os
import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import bus, config, settings
from ..board import store
from ..board.models import STATUSES
from .projects import get_git_info

log = logging.getLogger("api.board")
router = APIRouter(tags=["board"])


class StatusIn(BaseModel):
    status: str


def _enrich_token_usage(task_objs: list) -> list[dict]:
    """Gắn token_usage: parent = tổng parent + mọi sub/bug; child = chỉ chính nó."""
    children: dict[str, list[str]] = {}
    for t in task_objs:
        if t.parent_id:
            children.setdefault(t.parent_id, []).append(t.id)
    out: list[dict] = []
    for t in task_objs:
        d = t.to_dict()
        ids = [t.id]
        if not t.parent_id:
            ids.extend(children.get(t.id, []))
        d["token_usage"] = settings.llm_usage_sum(ids)
        out.append(d)
    return out


def _build_board_payload() -> dict:
    task_objs = store.list_tasks(include_archived=False)
    tasks = _enrich_token_usage(task_objs)
    seen: dict[str, str] = {}
    for t in tasks:
        if t["project"] and t["project"] not in seen:
            seen[t["project"]] = t.get("project_dir") or ""
    settings.ensure_project_from_tasks(list(seen.items()))
    return {"statuses": STATUSES, "tasks": tasks}


@router.get("/api/board")
async def get_board():
    # Off event-loop: tránh chặn WS/API khác khi SQLite đang bị tool thread ghi
    return await asyncio.to_thread(_build_board_payload)


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = store.get_task(task_id)
    if not task:
        return JSONResponse({"error": "not found"}, status_code=404)
    children = store.list_tasks(parent_id=task_id)
    child_ids = [c.id for c in children]
    t_dict = task.to_dict()
    t_dict["token_usage"] = settings.llm_usage_sum([task.id, *child_ids])
    p_dir = task.project_dir or os.path.join(config.PROJECTS_DIR, task.project)
    t_dict["git_info"] = get_git_info(p_dir)
    return {
        "task": t_dict,
        "subtasks": [
            {**c.to_dict(), "token_usage": settings.llm_usage_for_task(c.id)}
            for c in children
        ],
        "events": [e.to_dict() for e in store.list_events(task_id)],
        "deps": store.get_deps(task_id),
    }


@router.post("/api/tasks/{task_id}/status")
async def operator_set_status(task_id: str, body: StatusIn):
    result = store.set_status(task_id, body.status, "operator")
    if result.accepted and body.status == "blocked":
        subtasks = store.list_tasks(parent_id=task_id)
        for st in subtasks:
            if st.status not in ("done", "archived"):
                try:
                    store.set_status(st.id, "blocked", "operator")
                    store.add_event(st.id, "operator", "system", f"Task cha `{task_id}` bị Operator chuyển sang Blocked -> Subtask bị dừng theo.")
                except Exception:
                    pass
    return {"accepted": result.accepted, "final_status": result.final_status, "note": result.note}


@router.post("/api/tasks/{task_id}/approve")
async def operator_approve(task_id: str):
    result = store.set_status(task_id, "done", "operator")
    if result.accepted:
        store.add_event(task_id, "operator", "comment", "Operator đã duyệt (approve) task.")
        store.add_chat("system", f"✅ Operator đã approve {task_id}.")
    return {"accepted": result.accepted, "final_status": result.final_status, "note": result.note}


@router.post("/api/tasks/{task_id}/block")
async def operator_block_task(task_id: str):
    task = store.get_task(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)
    result = store.set_status(task_id, "blocked", "operator")
    if result.accepted:
        subtasks = store.list_tasks(parent_id=task_id)
        for st in subtasks:
            if st.status not in ("done", "archived"):
                try:
                    store.set_status(st.id, "blocked", "operator")
                    store.add_event(st.id, "operator", "system", f"Task cha `{task_id}` bị Operator dừng -> Subtask bị dừng theo.")
                except Exception:
                    pass
        store.add_event(task_id, "operator", "system", "Operator chủ động dừng task và chuyển sang Blocked.")
        store.add_chat("system", f"🛑 Operator đã dừng {task_id} và tất cả subtask con chuyển sang Blocked.")
        bus.publish({
            "type": "status_changed",
            "task_id": task_id,
            "status": "blocked",
            "actor": "operator"
        })
    return {"accepted": result.accepted, "final_status": result.final_status, "note": result.note}


@router.post("/api/tasks/{task_id}/rerun")
async def operator_rerun(task_id: str):
    task = store.get_task(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)

    if not task.parent_id:
        store.reset_blocked_children_for_rerun(task_id)
        result = store.set_status(task_id, "in_progress", "operator")
        if result.accepted:
            store.add_event(task_id, "operator", "system", "Operator chạy lại (re-run) task.")
            store.add_chat("system", f"↺ Operator đã cho chạy lại task `{task_id}`.")
            from ..core import orchestrator
            import asyncio
            asyncio.create_task(orchestrator.re_run_task_closure(task_id))
        return {"accepted": result.accepted, "final_status": result.final_status, "note": result.note}

    res = store.set_status(task_id, "backlog", "operator")
    if res.accepted:
        store.add_event(task_id, "operator", "system", "Operator reset subtask/bug về Backlog.")
    return {"accepted": res.accepted, "final_status": res.final_status, "note": res.note}
