"""FastAPI app: chat + board API + WebSocket realtime + background daemons."""
import asyncio
import json
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
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
log = logging.getLogger("api")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(scheduler_loop())
    asyncio.create_task(patrol_loop())
    yield


app = FastAPI(title="AI Orchestrator", lifespan=lifespan)


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
    async def _run_chat():
        try:
            await orchestrator.handle_chat(msg, project=body.project.strip() or None)
        except Exception as e:
            log.exception("handle_chat crashed")
            store.add_chat(
                "jarvis",
                f"Xin lỗi, xử lý tin nhắn bị lỗi không mong đợi: {e}. "
                "Thử gửi lại hoặc kiểm tra Settings / đường dẫn project.",
            )

    asyncio.create_task(_run_chat())
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
    project_dir: str = ""


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
        "projects_root": settings.effective_projects_root(),
        "projects_root_custom": settings.projects_root(),
    }


@app.post("/api/projects")
async def create_project(body: ProjectIn):
    name = body.name.strip()
    if not name:
        return JSONResponse({"error": "cần tên project"}, status_code=400)
    slug = (body.slug or name).strip()
    p = settings.upsert_project(slug, name=name, project_dir=body.project_dir.strip())
    return {"ok": True, "project": p, "active_project": p["slug"]}


class ProjectPatch(BaseModel):
    name: str = ""
    project_dir: str = ""
    api_base: str = ""


@app.patch("/api/projects/{slug}")
async def patch_project(slug: str, body: ProjectPatch):
    p = settings.get_project(slug)
    if not p:
        return JSONResponse({"error": "project không tồn tại"}, status_code=404)
    from pathlib import Path

    name = body.name.strip()
    pdir = body.project_dir.strip()
    api_base = body.api_base.strip()
    if pdir:
        Path(pdir).mkdir(parents=True, exist_ok=True)
    p = settings.upsert_project(
        slug,
        name=name or p.get("name", ""),
        project_dir=pdir,
        api_base=api_base,
    )
    return {"ok": True, "project": p}


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
    """Xóa project khỏi danh sách + archive task + xóa thư mục project trên đĩa."""
    from .paths import safe_remove_project_dir

    p = settings.get_project(slug)
    # Lấy cả task archived để biết project_dir cũ
    all_tasks = [t for t in store.list_tasks(include_archived=True) if t.project == slug]
    tasks = [t for t in all_tasks if t.status != "archived"]
    if not p and not all_tasks:
        return JSONResponse({"error": "project không tồn tại"}, status_code=404)

    # Thu thập mọi project_dir liên quan
    dirs: list[str] = []
    if p and p.get("project_dir"):
        dirs.append(p["project_dir"])
    for t in all_tasks:
        if t.project_dir and t.project_dir not in dirs:
            dirs.append(t.project_dir)
    # Legacy: workspace/projects/<slug> trong Orchestrator
    legacy = config.WORKSPACE_DIR / "projects" / slug
    if legacy.is_dir() and str(legacy) not in dirs:
        dirs.append(str(legacy))

    archived = 0
    for t in tasks:
        result = store.archive_task(t.id, "operator")
        if result.accepted and result.final_status == "archived":
            store.add_event(t.id, "operator", "system", f"Project `{slug}` đã bị xóa — task được archive.")
            archived += 1
        else:
            store.add_event(
                t.id, "operator", "system",
                f"Project `{slug}` xóa — không archive được {t.id} "
                f"(status={result.final_status}: {result.note or 'transition bị từ chối'}).",
            )

    settings.remove_project(slug)

    removed_dirs: list[str] = []
    dir_errors: list[str] = []
    killed: list[str] = []
    for d in dirs:
        result = safe_remove_project_dir(d, slug=slug)
        killed.extend(result.get("killed_processes") or [])
        if result.get("ok"):
            removed_dirs.append(result["path"])
        elif result.get("error") and result["error"] != "không tồn tại":
            dir_errors.append(f"{d}: {result['error']}")

    note = f"Đã xóa project `{slug}`"
    if removed_dirs:
        note += f" — đã gỡ thư mục: {', '.join(removed_dirs)}"
    if killed:
        note += f" — đã dừng process giữ lock: {', '.join(killed)}"
    if dir_errors:
        note += f" — không xóa được: {'; '.join(dir_errors)}"
    if archived:
        note += f" — archive {archived} task"
    store.add_chat("jarvis", note)

    return {
        "ok": True,
        "archived_tasks": archived,
        "removed_dirs": removed_dirs,
        "dir_errors": dir_errors,
        "killed_processes": killed,
        "active_project": settings.active_project(),
        "projects": settings.projects(),
    }


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = store.get_task(task_id)
    if not task:
        return JSONResponse({"error": "not found"}, status_code=404)
    children = store.list_tasks(parent_id=task_id)
    return {
        "task": task.to_dict(),
        "subtasks": [c.to_dict() for c in children],
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
    if task.status not in ("blocked", "failed"):
        return JSONResponse({"error": "chỉ chạy lại được task đang blocked hoặc failed"}, status_code=400)

    is_parent = not task.parent_id and bool(store.list_tasks(parent_id=task.id))
    if is_parent:
        from .core.scheduler import _task_retry_counts
        _task_retry_counts.pop(task.id, None)
        store.set_status(task.id, "backlog", "operator")
        store.add_event(task.id, "operator", "system", "Operator yêu cầu chạy lại task cha và toàn bộ subtask.")
        subtasks = store.list_tasks(parent_id=task.id)
        for st in subtasks:
            _task_retry_counts.pop(st.id, None)
            store.set_status(st.id, "backlog", "operator")
        return {"ok": True, "mode": "requeue"}

    from .core.scheduler import _task_retry_counts
    _task_retry_counts.pop(task.id, None)
    result = store.set_status(task.id, "backlog", "operator")
    store.add_event(task.id, "operator", "system", "Operator đưa task về backlog để agent chạy lại.")
    return {"ok": result.accepted, "mode": "requeue", "note": result.note}


# ---------- Settings ----------

def _mask(token: str) -> str:
    return token[:9] + "…" + token[-4:] if len(token) > 16 else "…"


@app.get("/api/settings")
async def get_settings():
    from .agents.registry import roster_models
    from .board import store

    active_tasks = store.list_tasks(status=["in_progress"])
    has_active_tasks = len(active_tasks) > 0

    tools = []
    for t in settings.llm_tools():
        tools.append({
            "id": t["id"],
            "model": t["model"],
            "base_url": t.get("base_url", ""),
            "enabled": t.get("enabled", True),
            "is_default": t.get("is_default", False) or (t.get("model") in settings.DEFAULT_SYSTEM_MODELS),
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
        "projects_root": settings.effective_projects_root(),
        "projects_root_custom": settings.projects_root(),
        "llm_tools": tools,
        "role_models": settings.role_models(),
        "role_labels": settings.ROLE_LABELS,
        "agents": roster_models(),
        "has_active_tasks": has_active_tasks,
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
    # Tự động loại bỏ trùng lặp /chat/completions, /text/chatcompletion_v2, /chat nếu người dùng dán URL đầy đủ
    suffixes = ["/chat/completions", "/text/chatcompletion_v2", "/text/chatcompletion", "/chat"]
    for suf in suffixes:
        if base_url.endswith(suf):
            base_url = base_url[:-len(suf)].rstrip("/")
            break

    model = body.model.strip()
    api_key = body.api_key.strip()
    name = (body.name or model).strip()
    if not base_url or not model or not api_key:
        return JSONResponse({"error": "cần đủ base_url, model, api_key"}, status_code=400)
    
    # BẮT BUỘC THỬ NGHIỆM ĐỊNH TUYẾN ỔN ĐỊNH (Strict Smoke Verification — 3 Lần Thử)
    import httpx, time
    clean_key = api_key.encode("latin-1", "ignore").decode("latin-1")
    
    last_err_msg = ""
    resp = None

    def _do_post():
        return httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {clean_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply OK"}],
                "max_tokens": 8,
                "temperature": 0,
            },
            timeout=30.0,
        )

    for attempt in range(1, 4):
        try:
            resp = await asyncio.to_thread(_do_post)
            if resp.status_code == 200:
                break
        except httpx.TimeoutException:
            last_err_msg = f"Lần {attempt}/3: Timeout quá 30s không nhận được phản hồi"
            await asyncio.sleep(1.5)
        except httpx.HTTPError as e:
            last_err_msg = f"Lần {attempt}/3: Lỗi kết nối mạng ({e})"
            await asyncio.sleep(1.5)
        except Exception as e:
            last_err_msg = str(e)
            break

    if resp is None:
        return JSONResponse(
            {"error": f"Endpoint/Model không ổn định — Thử kết nối 3 lần thất bại ({last_err_msg}). Vui lòng kiểm tra lại URL/Mạng trước khi thêm!"},
            status_code=400,
        )

    if resp.status_code in (401, 403):
        return JSONResponse(
            {"error": f"Lỗi HTTP {resp.status_code} (Xác thực thất bại / Invalid Token): API Key nhập vào bị từ chối hoặc không hợp lệ đối với Base URL '{base_url}'. Chi tiết từ Server: {resp.text[:200]}"},
            status_code=400,
        )
    elif resp.status_code == 404:
        return JSONResponse(
            {"error": f"Lỗi HTTP 404 (Not Found): Không tìm thấy tên model '{model}' hoặc sai Base URL '{base_url}'."},
            status_code=400,
        )
    elif resp.status_code == 429:
        return JSONResponse(
            {"error": "Lỗi HTTP 429 (Rate Limit / Hết Hạn Ngạch): Tài khoản API Key tại Provider này đã dùng hết lượt token/credit miễn phí (Token Plan usage limit reached). Vui lòng nạp thêm credit hoặc đổi sang Provider khác."},
            status_code=400,
        )
    elif resp.status_code >= 400:
        return JSONResponse(
            {"error": f"Endpoint/Model lỗi HTTP {resp.status_code}: {resp.text[:250]}"},
            status_code=400,
        )
    entry = settings.add_llm_tool(name, base_url, model, api_key, tool_id=body.id)
    return {"ok": True, "tool": {"id": entry["id"], "model": entry["model"], "base_url": entry["base_url"], "enabled": True, "is_default": entry.get("is_default", False)}}


class LlmToggleIn(BaseModel):
    enabled: bool


@app.patch("/api/settings/llm-tools/{tool_id}")
async def toggle_llm_tool(tool_id: str, body: LlmToggleIn):
    try:
        tool = settings.set_llm_tool_enabled(tool_id, body.enabled)
    except ValueError as err:
        return JSONResponse({"error": str(err)}, status_code=400)
    if not tool:
        return JSONResponse({"error": "không tìm thấy tool"}, status_code=404)
    return {
        "ok": True,
        "tool": {"id": tool["id"], "model": tool["model"], "base_url": tool.get("base_url", ""), "enabled": tool.get("enabled", True), "is_default": tool.get("is_default", False)},
        "role_models": settings.role_models(),
    }


@app.delete("/api/settings/llm-tools/{tool_id}")
async def delete_llm_tool(tool_id: str):
    try:
        ok = settings.delete_llm_tool(tool_id)
    except ValueError as err:
        return JSONResponse({"error": str(err)}, status_code=400)
    if not ok:
        return JSONResponse({"error": "không tìm thấy tool"}, status_code=404)
    return {"ok": True, "role_models": settings.role_models()}


@app.put("/api/settings/role-models")
async def update_role_model(body: RoleModelIn):
    from .board import store
    active_tasks = store.list_tasks(status=["in_progress"])
    if active_tasks:
        return JSONResponse(
            {"error": "Không thể thay đổi Model khi Agent đang thực thi Task! Hãy chờ Task hoàn thành."},
            status_code=400,
        )
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


class ProjectsRootIn(BaseModel):
    path: str = ""


@app.put("/api/settings/projects-root")
async def put_projects_root(body: ProjectsRootIn):
    """Đặt thư mục gốc clone project (ngoài Orchestrator). Rỗng = reset default."""
    try:
        root = settings.set_projects_root(body.path)
    except OSError as e:
        return JSONResponse({"error": f"không tạo được thư mục: {e}"}, status_code=400)
    return {
        "ok": True,
        "projects_root": root,
        "projects_root_custom": settings.projects_root(),
    }


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

def _resolve_preview_project_dir(project: str) -> Path | None:
    """Tìm thư mục serve preview — ưu tiên settings + task còn sống, bỏ path cũ đã mất."""
    candidates: list[Path] = []

    sp = settings.get_project(project)
    if sp and sp.get("project_dir"):
        candidates.append(Path(sp["project_dir"]))

    # Task chưa archive trước, archive sau; cùng nhóm thì mới hơn trước
    live = [t for t in store.list_tasks(include_archived=False) if t.project == project and t.project_dir]
    archived = [
        t for t in store.list_tasks(include_archived=True)
        if t.project == project and t.project_dir and t.status == "archived"
    ]
    for t in sorted(live, key=lambda x: x.updated_at or "", reverse=True):
        candidates.append(Path(t.project_dir))
    for t in sorted(archived, key=lambda x: x.updated_at or "", reverse=True):
        candidates.append(Path(t.project_dir))

    # Fallback: projects_root / slug
    candidates.append(Path(settings.effective_projects_root()) / project)
    candidates.append(config.WORKSPACE_DIR / "projects" / project)

    seen: set[str] = set()
    for p in candidates:
        try:
            key = str(p.resolve()) if p.exists() else str(p)
        except OSError:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_dir():
            return p
    return None


def _preview_serve_root(project_dir: Path) -> Path:
    """Vite/React đã build → serve từ dist/; không thì project root."""
    dist = project_dir / "dist"
    if (dist / "index.html").is_file():
        return dist
    return project_dir


def _rewrite_preview_html(html: str, project: str) -> str:
    """Đổi absolute path /assets /manifest → /preview/{project}/... để không 404 ở root Orchestrator."""
    import re

    base = f"/preview/{project}/"
    # href="/x" src="/x" content="/x" action="/x" — bỏ qua //cdn và đã có /preview/
    html = re.sub(
        r"""((?:href|src|content|action)\s*=\s*["'])/(?!/|preview/)""",
        rf"\1{base}",
        html,
        flags=re.I,
    )
    # url(/assets/...) trong inline style / CSS-in-HTML
    html = re.sub(
        r"""(url\(\s*["']?)/(?!/|preview/)""",
        rf"\1{base}",
        html,
        flags=re.I,
    )
    # serviceWorker.register('/sw.js')
    html = re.sub(
        r"""(serviceWorker\.register\(\s*["'])/(?!/|preview/)""",
        rf"\1{base}",
        html,
    )
    return html


def _find_preview_file(serve_root: Path, project_dir: Path, rel_path: str) -> Path | None:
    """Tìm file trong serve_root (dist) rồi fallback project_dir."""
    rel = rel_path.strip("/") or "index.html"
    for root in (serve_root, project_dir):
        try:
            root_res = root.resolve()
            cand = (root / rel).resolve()
        except OSError:
            continue
        if not str(cand).startswith(str(root_res)):
            continue
        if cand.is_dir():
            cand = cand / "index.html"
        if cand.is_file():
            return cand

    fname = Path(rel).name
    matches: list[Path] = []
    for root in (serve_root, project_dir):
        if root.is_dir():
            matches.extend(root.rglob(fname))
    if matches:
        # unique + ưu tiên dist
        uniq: list[Path] = []
        seen: set[str] = set()
        for m in matches:
            k = str(m.resolve())
            if k in seen:
                continue
            seen.add(k)
            uniq.append(m)
        uniq.sort(key=lambda m: (0 if "dist" in m.parts else 1, len(m.parts)))
        return uniq[0]
    return None


@app.get("/preview/{project}")
async def preview_project_noslash(project: str):
    """Bắt buộc trailing slash — không thì Vite absolute /src /assets resolve sai."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/preview/{project}/", status_code=307)


@app.get("/preview/{project}/")
async def preview_project_index(project: str):
    return await preview(project, "index.html")


@app.get("/preview/{project}/{file_path:path}")
async def preview(project: str, file_path: str = ""):
    """Serve file tĩnh từ project (ưu tiên dist) + rewrite base path cho Vite absolute URLs."""
    project_dir = _resolve_preview_project_dir(project)
    if project_dir is None:
        return JSONResponse(
            {"error": f"project '{project}' không tìm thấy thư mục (settings/task path)"},
            status_code=404,
        )

    serve_root = _preview_serve_root(project_dir)
    rel_path = file_path.strip("/") or "index.html"
    target = _find_preview_file(serve_root, project_dir, rel_path)

    # Không bao giờ serve Vite source index (có /src/main.tsx) nếu đã có dist
    if target and target.suffix.lower() in (".html", ".htm"):
        try:
            peek = target.read_text(encoding="utf-8", errors="ignore")[:2000]
        except OSError:
            peek = ""
        dist_index = project_dir / "dist" / "index.html"
        if ("/src/main." in peek or 'src="/src/' in peek) and dist_index.is_file():
            target = dist_index
            serve_root = project_dir / "dist"

    if target is None or not target.is_file():
        return JSONResponse({"error": f"file không tồn tại: {file_path or 'index.html'}"}, status_code=404)

    # HTML: rewrite absolute /paths → /preview/{project}/paths
    if target.suffix.lower() in (".html", ".htm"):
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        return HTMLResponse(
            _rewrite_preview_html(raw, project),
            headers={"Cache-Control": "no-store"},
        )

    # CSS cũng có thể chứa url(/assets/...)
    if target.suffix.lower() == ".css":
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError:
            return FileResponse(target)
        return Response(
            content=_rewrite_preview_html(raw, project),
            media_type="text/css; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    return FileResponse(target)


# ---------- Preview API proxy: FE gọi /api/* trên :8600 → backend project (:3000…) ----------

import re
import time

import httpx
from fastapi import Request
from starlette.responses import StreamingResponse

_API_BASE_CACHE: dict[str, tuple[float, str]] = {}  # slug -> (expires_at, base)
_API_PROBE_PORTS = (3000, 3001, 8000, 8080, 5000, 5173)
_HOP_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade",
}


def _project_from_referer(referer: str) -> str:
    m = re.search(r"/preview/([^/?#]+)/?", referer or "")
    return m.group(1) if m else ""


async def _resolve_project_api_base(slug: str) -> str | None:
    """Lấy api_base của project: settings → cache probe health → None."""
    if not slug:
        return None
    sp = settings.get_project(slug) or {}
    configured = (sp.get("api_base") or "").strip().rstrip("/")
    if configured:
        return configured

    now = time.time()
    hit = _API_BASE_CACHE.get(slug)
    if hit and hit[0] > now:
        return hit[1] or None

    base_found = ""
    async with httpx.AsyncClient(timeout=1.2) as client:
        for port in _API_PROBE_PORTS:
            base = f"http://127.0.0.1:{port}"
            try:
                r = await client.get(f"{base}/api/health")
                if r.status_code < 500:
                    base_found = base
                    break
            except Exception:
                continue

    _API_BASE_CACHE[slug] = (now + 60.0, base_found)  # cache 60s kể cả miss
    return base_found or None


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_project_api(path: str, request: Request):
    """Proxy các /api/* không thuộc Orchestrator sang backend của project đang preview."""
    slug = _project_from_referer(request.headers.get("referer", ""))
    if not slug:
        slug = settings.active_project() or ""
    api_base = await _resolve_project_api_base(slug)
    if not api_base:
        return JSONResponse(
            {
                "error": "không có backend API để proxy",
                "hint": "Start app backend (vd :3000) hoặc set api_base cho project",
                "project": slug or None,
            },
            status_code=502,
        )

    url = f"{api_base}/api/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_HEADERS
    }
    body = await request.body()

    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
    try:
        upstream = client.build_request(request.method, url, headers=headers, content=body or None)
        resp = await client.send(upstream, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        log.warning("API proxy %s -> %s failed: %s", path, api_base, e)
        return JSONResponse({"error": f"proxy failed: {e}", "target": url}, status_code=502)

    out_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in _HOP_HEADERS and k.lower() != "content-encoding"
    }

    async def _stream():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _stream(),
        status_code=resp.status_code,
        headers=out_headers,
        media_type=resp.headers.get("content-type"),
    )


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
