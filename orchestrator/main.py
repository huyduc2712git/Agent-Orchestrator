"""FastAPI app: chat + board API + WebSocket realtime + background daemons."""
import asyncio
import json
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import bus, config, settings
from .board import store
from .board.models import STATUSES
from .core import orchestrator
from .core.patrol import patrol_loop
from .core.scheduler import scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

app = FastAPI(title="AI Orchestrator")


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(scheduler_loop())
    asyncio.create_task(patrol_loop())


# ---------- Chat ----------

class ChatIn(BaseModel):
    message: str
    project: str = ""  # slug project đang chọn — task mới gắn vào đây


@app.post("/api/chat")
async def post_chat(body: ChatIn):
    msg = body.message.strip()
    if not msg:
        return JSONResponse({"error": "empty message"}, status_code=400)
    store.add_chat("user", msg)
    # Phase 1-2 chạy nền — trả HTTP ngay, Jarvis reply qua WebSocket
    asyncio.create_task(orchestrator.handle_chat(msg, project=body.project.strip() or None))
    return {"ok": True}


@app.get("/api/chat")
async def get_chat():
    return {"messages": store.list_chat(limit=200)}


# ---------- Board ----------

@app.get("/api/board")
async def get_board():
    tasks = [t.to_dict() for t in store.list_tasks(include_archived=False)]
    # Đồng bộ project từ task vào settings
    seen: dict[str, str] = {}
    for t in tasks:
        if t["project"] and t["project"] not in seen:
            seen[t["project"]] = t.get("project_dir") or ""
    settings.ensure_project_from_tasks(list(seen.items()))
    return {"statuses": STATUSES, "tasks": tasks}


# ---------- Projects ----------

class ProjectIn(BaseModel):
    name: str
    slug: str = ""


@app.get("/api/projects")
async def list_projects():
    # Chỉ đồng bộ từ task chưa archived — project đã remove không bị hiện lại
    seen: dict[str, str] = {}
    for t in store.list_tasks(include_archived=False):
        if t.project and t.project not in seen:
            seen[t.project] = t.project_dir or ""
    settings.ensure_project_from_tasks(list(seen.items()))
    return {
        "projects": settings.projects(),
        "active_project": settings.active_project(),
    }


@app.post("/api/projects")
async def create_project(body: ProjectIn):
    name = body.name.strip()
    if not name:
        return JSONResponse({"error": "cần tên project"}, status_code=400)
    slug = (body.slug or name).strip()
    p = settings.upsert_project(slug, name=name)
    return {"ok": True, "project": p, "active_project": p["slug"]}


@app.post("/api/projects/{slug}/select")
async def select_project(slug: str):
    p = settings.get_project(slug)
    if not p:
        # Cho phép chọn project chỉ tồn tại trên board
        for t in store.list_tasks(include_archived=False):
            if t.project == slug:
                p = settings.upsert_project(slug, name=slug, project_dir=t.project_dir or "")
                break
    if not p:
        return JSONResponse({"error": "project không tồn tại"}, status_code=404)
    settings.set_active_project(slug)
    return {"ok": True, "active_project": slug, "project": p}


@app.delete("/api/projects/{slug}")
async def delete_project(slug: str):
    """Xóa project khỏi danh sách + archive toàn bộ task thuộc project đó."""
    p = settings.get_project(slug)
    tasks = [t for t in store.list_tasks(include_archived=False) if t.project == slug]
    if not p and not tasks:
        return JSONResponse({"error": "project không tồn tại"}, status_code=404)

    archived = 0
    for t in tasks:
        if t.status != "archived":
            store.update_task_fields(t.id, status="archived")
            store.add_event(t.id, "operator", "system", f"Project `{slug}` đã bị xóa — task được archive.")
            archived += 1

    settings.remove_project(slug)
    # Nếu chưa có trong settings nhưng vẫn có task → đã archive xong
    if p is None and slug:
        pass

    return {
        "ok": True,
        "archived_tasks": archived,
        "active_project": settings.active_project(),
        "projects": settings.projects(),
    }


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = store.get_task(task_id)
    if not task:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "task": task.to_dict(),
        "events": [e.to_dict() for e in store.list_events(task_id)],
        "deps": store.get_deps(task_id),
    }


class StatusIn(BaseModel):
    status: str


@app.post("/api/tasks/{task_id}/status")
async def operator_set_status(task_id: str, body: StatusIn):
    """Operator (người thật trên UI) đổi status — đi qua transition guard như mọi actor."""
    result = store.set_status(task_id, body.status, "operator")
    return {"accepted": result.accepted, "final_status": result.final_status, "note": result.note}


@app.post("/api/tasks/{task_id}/approve")
async def operator_approve(task_id: str):
    """Review gate: operator duyệt task đang ở trạng thái review."""
    result = store.set_status(task_id, "done", "operator")
    if result.accepted:
        store.add_event(task_id, "operator", "comment", "Operator đã duyệt (approve) task.")
        store.add_chat("system", f"✅ Operator đã approve {task_id}.")
    return {"accepted": result.accepted, "final_status": result.final_status, "note": result.note}


@app.post("/api/tasks/{task_id}/rerun")
async def operator_rerun(task_id: str):
    """Chạy lại task bị blocked: task cha -> re-run closure; subtask/bug -> về backlog cho scheduler."""
    task = store.get_task(task_id)
    if not task:
        return JSONResponse({"error": "not found"}, status_code=404)
    if task.status != "blocked":
        return JSONResponse({"error": "chỉ chạy lại được task đang blocked"}, status_code=400)

    is_parent = not task.parent_id and bool(store.list_tasks(parent_id=task.id))
    if is_parent:
        store.set_status(task.id, "in_progress", "operator")
        store.add_event(task.id, "operator", "system", "Operator yêu cầu chạy lại final review (closure).")
        asyncio.create_task(orchestrator.check_parent_progress(task.id))
        return {"ok": True, "mode": "closure"}

    result = store.set_status(task.id, "backlog", "operator")
    store.add_event(task.id, "operator", "system", "Operator đưa task về backlog để agent chạy lại.")
    return {"ok": result.accepted, "mode": "requeue", "note": result.note}


# ---------- Settings ----------

def _mask(token: str) -> str:
    return token[:9] + "…" + token[-4:] if len(token) > 16 else "…"


@app.get("/api/settings")
async def get_settings():
    from .agents.registry import roster_models

    tools = []
    for t in settings.llm_tools():
        tools.append({
            "id": t["id"],
            "model": t["model"],
            "enabled": t.get("enabled", True),
        })
    return {
        "figma_tokens": [
            {"name": t["name"], "token_masked": _mask(t["token"])}
            for t in settings.figma_tokens()
        ],
        "git_tokens": [
            {
                "name": t["name"],
                "host": t.get("host", ""),
                "token_masked": _mask(t.get("token", "")),
            }
            for t in settings.git_tokens()
        ],
        "llm_tools": tools,
        "role_models": settings.role_models(),
        "role_labels": settings.ROLE_LABELS,
        "agents": roster_models(),
    }


class FigmaTokenIn(BaseModel):
    name: str
    token: str


class LlmToolIn(BaseModel):
    name: str = ""
    base_url: str
    model: str
    api_key: str
    id: str = ""


class RoleModelIn(BaseModel):
    role: str
    tool_id: str


@app.post("/api/settings/llm-tools")
async def add_llm_tool(body: LlmToolIn):
    base_url = body.base_url.strip().rstrip("/")
    model = body.model.strip()
    api_key = body.api_key.strip()
    name = (body.name or model).strip()
    if not base_url or not model or not api_key:
        return JSONResponse({"error": "cần đủ base_url, model, api_key"}, status_code=400)
    # Smoke test endpoint
    import httpx
    try:
        resp = await asyncio.to_thread(
            lambda: httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply OK"}],
                    "max_tokens": 8,
                    "temperature": 0,
                },
                timeout=40,
            )
        )
    except httpx.HTTPError as e:
        return JSONResponse({"error": f"không gọi được endpoint: {e}"}, status_code=502)
    if resp.status_code >= 400:
        return JSONResponse(
            {"error": f"endpoint/model lỗi HTTP {resp.status_code}: {resp.text[:200]}"},
            status_code=400,
        )
    entry = settings.add_llm_tool(name, base_url, model, api_key, tool_id=body.id)
    return {"ok": True, "tool": {"id": entry["id"], "model": entry["model"], "enabled": True}}


class LlmToggleIn(BaseModel):
    enabled: bool


@app.patch("/api/settings/llm-tools/{tool_id}")
async def toggle_llm_tool(tool_id: str, body: LlmToggleIn):
    tool = settings.set_llm_tool_enabled(tool_id, body.enabled)
    if not tool:
        return JSONResponse({"error": "không tìm thấy tool"}, status_code=404)
    return {
        "ok": True,
        "tool": {"id": tool["id"], "model": tool["model"], "enabled": tool.get("enabled", True)},
        "role_models": settings.role_models(),
    }


@app.put("/api/settings/role-models")
async def update_role_model(body: RoleModelIn):
    try:
        settings.set_role_model(body.role.strip(), body.tool_id.strip())
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    from .agents.registry import roster_models
    return {"ok": True, "role_models": settings.role_models(), "agents": roster_models()}


@app.post("/api/settings/figma-tokens")
async def add_figma_token(body: FigmaTokenIn):
    name = body.name.strip()
    token = body.token.strip()
    if not name or not token:
        return JSONResponse({"error": "cần đủ name và token"}, status_code=400)
    # validate token với Figma trước khi lưu
    import httpx
    try:
        resp = await asyncio.to_thread(
            lambda: httpx.get("https://api.figma.com/v1/me",
                              headers={"X-Figma-Token": token}, timeout=15)
        )
    except httpx.HTTPError as e:
        return JSONResponse({"error": f"không gọi được Figma API: {e}"}, status_code=502)
    if resp.status_code != 200:
        return JSONResponse({"error": f"token không hợp lệ (HTTP {resp.status_code})"}, status_code=400)
    email = resp.json().get("email", "")
    settings.add_figma_token(name, token)
    return {"ok": True, "account_email": email}


@app.delete("/api/settings/figma-tokens/{name}")
async def delete_figma_token(name: str):
    removed = settings.remove_figma_token(name)
    if not removed:
        return JSONResponse({"error": "không tìm thấy token"}, status_code=404)
    return {"ok": True}


class GitTokenIn(BaseModel):
    name: str
    host: str = "github.com"
    token: str


@app.post("/api/settings/git-tokens")
async def add_git_token(body: GitTokenIn):
    name = body.name.strip()
    host = body.host.strip() or "github.com"
    token = body.token.strip()
    if not name or not token:
        return JSONResponse({"error": "cần đủ name và token"}, status_code=400)
    settings.add_git_token(name, host, token)
    return {"ok": True, "host": host.lower().removeprefix("https://").split("/")[0]}


@app.delete("/api/settings/git-tokens/{name}")
async def delete_git_token(name: str):
    if not settings.remove_git_token(name):
        return JSONResponse({"error": "không tìm thấy token"}, status_code=404)
    return {"ok": True}


# ---------- WebSocket realtime ----------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q = bus.subscribe()
    try:
        while True:
            event = await q.get()
            await ws.send_text(json.dumps(event, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)


# ---------- Preview: serve tĩnh project directory để có Live URL ----------

@app.get("/preview/{project}/{file_path:path}")
async def preview(project: str, file_path: str = ""):
    """Serve file tĩnh từ project_dir của một project bất kỳ trên board."""
    project_dir = None
    for t in store.list_tasks(include_archived=True):
        if t.project == project and t.project_dir:
            project_dir = Path(t.project_dir)
            break
    if project_dir is None or not project_dir.is_dir():
        return JSONResponse({"error": f"project '{project}' không tồn tại"}, status_code=404)

    target = (project_dir / (file_path or "index.html")).resolve()
    if not str(target).startswith(str(project_dir.resolve())):
        return JSONResponse({"error": "path không hợp lệ"}, status_code=400)
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        return JSONResponse({"error": f"file không tồn tại: {file_path}"}, status_code=404)
    return FileResponse(target)


# ---------- QA Artifacts: screenshot / diff images ----------

@app.get("/artifacts/{task_id}/{filename}")
async def get_artifact(task_id: str, filename: str):
    """Serve screenshot/diff PNG từ Visual QA của Hawkeye."""
    if ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse({"error": "path không hợp lệ"}, status_code=400)
    path = (config.ARTIFACTS_DIR / task_id / filename).resolve()
    if not str(path).startswith(str(config.ARTIFACTS_DIR.resolve())):
        return JSONResponse({"error": "path không hợp lệ"}, status_code=400)
    if not path.is_file():
        return JSONResponse({"error": "file không tồn tại"}, status_code=404)
    return FileResponse(path)


# ---------- Static UI ----------

app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(config.WEB_DIR / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")
