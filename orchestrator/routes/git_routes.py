"""Git operation API routes."""
import os
import asyncio
import subprocess
import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import config
from ..board import store

log = logging.getLogger("api.git")
router = APIRouter(tags=["git"])


class GitPushIn(BaseModel):
    message: str = ""


@router.post("/api/tasks/{task_id}/git-push")
async def operator_git_push(task_id: str, body: GitPushIn | None = None):
    task = store.get_task(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)

    project_dir = task.project_dir
    if not project_dir or not os.path.exists(project_dir):
        project_dir = os.path.join(config.PROJECTS_DIR, task.project)

    if not os.path.exists(project_dir):
        return JSONResponse({"error": f"Không tìm thấy thư mục làm việc: {project_dir}"}, status_code=400)

    commit_msg = (body.message.strip() if body and body.message else "") or f"feat: {task.title} ({task.id})"

    try:
        status_res = await asyncio.to_thread(
            subprocess.run, ["git", "status", "--porcelain"], cwd=project_dir, capture_output=True, text=True, check=False
        )
        if not status_res.stdout.strip():
            return JSONResponse({"error": "Không có file code nào bị chỉnh sửa để commit & push (Working tree clean)."}, status_code=400)

        add_res = await asyncio.to_thread(
            subprocess.run, ["git", "add", "."], cwd=project_dir, capture_output=True, text=True, check=False
        )
        if add_res.returncode != 0:
            err = ((add_res.stdout or "") + "\n" + (add_res.stderr or "")).strip()
            store.add_event(task.id, "operator", "system", f"Git add thất bại:\n{err[:500]}")
            return JSONResponse({"error": f"Git add thất bại: {err}"}, status_code=500)

        commit_res = await asyncio.to_thread(
            subprocess.run, ["git", "commit", "-m", commit_msg], cwd=project_dir, capture_output=True, text=True, check=False
        )
        commit_out = ((commit_res.stdout or "") + "\n" + (commit_res.stderr or "")).strip()
        nothing_to_commit = "nothing to commit" in commit_out.lower()
        if commit_res.returncode != 0 and not nothing_to_commit:
            store.add_event(task.id, "operator", "system", f"Git commit thất bại:\n{commit_out[:500]}")
            return JSONResponse({"error": f"Git commit thất bại: {commit_out}"}, status_code=500)

        push_res = await asyncio.to_thread(
            subprocess.run, ["git", "push"], cwd=project_dir, capture_output=True, text=True, check=False
        )
        push_out = (push_res.stdout + "\n" + push_res.stderr).strip()

        if push_res.returncode != 0:
            store.add_event(task.id, "operator", "system", f"Git push thất bại:\n{push_out[:500]}")
            return JSONResponse({"error": f"Git push thất bại: {push_out}"}, status_code=500)

        store.add_event(task.id, "operator", "system", f"Git Commit & Push thành công: {commit_msg}")
        store.add_chat("operator", f"🚀 {task.id}: Đã Commit & Push code thành công lên Git repository!\nCommit: {commit_msg}")

        return {
            "ok": True,
            "message": f"Push thành công: {commit_msg}",
            "output": push_out
        }
    except Exception as err:
        return JSONResponse({"error": f"Lỗi thực thi Git: {err}"}, status_code=500)


@router.post("/api/tasks/{task_id}/reject-rollback")
async def operator_reject_and_rollback(task_id: str):
    from ..main import switch_backend
    task = store.get_task(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)

    p_dir = task.project_dir or os.path.join(config.PROJECTS_DIR, task.project)
    git_note = ""
    if os.path.exists(os.path.join(p_dir, ".git")):
        try:
            subprocess.run(["git", "restore", "."], cwd=p_dir, capture_output=True, text=True, timeout=15)
            subprocess.run(["git", "clean", "-fd"], cwd=p_dir, capture_output=True, text=True, timeout=15)
            git_note = "Đã restore & clean git code thành công."
        except Exception as e:
            git_note = f"Lỗi rollback git: {e}"
    else:
        git_note = "Không phải git repository."

    result = store.set_status(task_id, "blocked", "operator")
    subtasks = store.list_tasks(parent_id=task_id)
    for st in subtasks:
        try:
            store.set_status(st.id, "blocked", "operator")
        except Exception:
            pass

    store.add_event(task_id, "operator", "system", f"Operator từ chối thay đổi & đã Rollback git code. Task chuyển về Blocked. ({git_note})")
    store.add_chat("system", f"🛑 Operator đã từ chối task `{task_id}`, rollback git code và chuyển task sang Blocked.")
    if task.project:
        try:
            await switch_backend(task.project)
        except Exception as e:
            log.warning("Không thể auto-restart backend %s sau rollback: %s", task.project, e)

    return {"accepted": True, "final_status": "blocked", "note": git_note}
