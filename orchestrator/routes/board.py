"""Board & Tasks CRUD API routes."""
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


@router.get("/api/board")
async def get_board():
    tasks = [t.to_dict() for t in store.list_tasks(include_archived=False)]
    seen: dict[str, str] = {}
    for t in tasks:
        if t["project"] and t["project"] not in seen:
            seen[t["project"]] = t.get("project_dir") or ""
    settings.ensure_project_from_tasks(list(seen.items()))
    return {"statuses": STATUSES, "tasks": tasks}


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = store.get_task(task_id)
    if not task:
        return JSONResponse({"error": "not found"}, status_code=404)
    children = store.list_tasks(parent_id=task_id)
    t_dict = task.to_dict()
    p_dir = task.project_dir or os.path.join(config.PROJECTS_DIR, task.project)
    t_dict["git_info"] = get_git_info(p_dir)
    return {
        "task": t_dict,
        "subtasks": [c.to_dict() for c in children],
        "events": [e.to_dict() for e in store.list_events(task_id)],
        "deps": store.get_deps(task_id),
    }


@router.post("/api/tasks/{task_id}/status")
async def operator_set_status(task_id: str, body: StatusIn):
    result = store.set_status(task_id, body.status, "operator")
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
                except Exception:
                    pass
        store.add_event(task_id, "operator", "system", "Operator chủ động dừng task và chuyển sang Blocked.")
        store.add_chat("system", f"🛑 Operator đã dừng {task_id} và chuyển sang Blocked (Needs Attention) để kiểm tra.")
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
