"""FastAPI app: modular routers + background daemons."""
import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import bus, config, settings
from .core.patrol import patrol_loop
from .core.scheduler import scheduler_loop
from .routes import board, chat, git_routes, preview, projects, settings as settings_routes, mcp as mcp_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("api")

# ---------- Auto-start backend cho active project ----------

_backend_procs: dict[str, subprocess.Popen] = {}  # slug → Popen


def _is_backend_alive(slug: str) -> bool:
    proc = _backend_procs.get(slug)
    return bool(proc and proc.poll() is None)


async def _probe_port(port: int) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except Exception:
        return False


def _stop_backend(slug: str) -> None:
    proc = _backend_procs.pop(slug, None)
    if proc and proc.poll() is None:
        log.info("Stopping backend '%s' (pid=%s)", slug, proc.pid)
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


async def _start_backend(slug: str) -> bool:
    proj = settings.get_project(slug)
    if not proj:
        return False

    start_cmd = (proj.get("start_command") or "").strip()
    project_dir = Path(proj.get("project_dir", ""))
    if not start_cmd or not project_dir.exists():
        return False

    if _is_backend_alive(slug):
        log.info("Backend '%s' đã chạy (pid=%s), bỏ qua", slug, _backend_procs[slug].pid)
        return True

    api_base = (proj.get("api_base") or "").strip()
    if api_base:
        port_match = re.search(r":(\d+)", api_base)
        if port_match and await _probe_port(int(port_match.group(1))):
            log.info("Backend '%s' đã có service trên %s, bỏ qua", slug, api_base)
            return True

    log.info("Starting backend cho project '%s': %s (cwd=%s)", slug, start_cmd, project_dir)
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", start_cmd] if os.name == "nt"
            else ["sh", "-c", start_cmd],
            cwd=str(project_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        _backend_procs[slug] = proc
        log.info("Backend '%s' started (pid=%s) — %s", slug, proc.pid, start_cmd)
        return True
    except Exception as e:
        log.warning("Không thể start backend '%s': %s", slug, e)
        return False


async def switch_backend(new_slug: str) -> None:
    for slug in list(_backend_procs.keys()):
        if slug != new_slug:
            _stop_backend(slug)
    if new_slug:
        await _start_backend(new_slug)


def _shutdown_all_backends() -> None:
    for slug in list(_backend_procs.keys()):
        _stop_backend(slug)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.set_main_loop(asyncio.get_running_loop())
    try:
        from .workspace_cleanup import cleanup_orphan_artifacts, cleanup_stale_workspace
        cleanup_stale_workspace()
        n = cleanup_orphan_artifacts()
        if n:
            log.info("Startup: đã dọn %s thư mục artifacts cũ", n)
    except Exception:
        log.exception("Startup workspace cleanup failed (non-blocking)")
    asyncio.create_task(scheduler_loop())
    asyncio.create_task(patrol_loop())
    active = settings.active_project()
    if active:
        await _start_backend(active)
    yield
    _shutdown_all_backends()


app = FastAPI(title="AI Orchestrator", lifespan=lifespan)

# ---------- Register Routers ----------
app.include_router(chat.router)
app.include_router(board.router)
app.include_router(projects.router)
app.include_router(settings_routes.router)
app.include_router(git_routes.router)
app.include_router(preview.router)
app.include_router(mcp_routes.router)


# ---------- QA Artifacts ----------

@app.get("/artifacts/{task_id}/{filename}")
async def get_artifact(task_id: str, filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse({"error": "path không hợp lệ"}, status_code=400)
    path = (config.ARTIFACTS_DIR / task_id / filename).resolve()
    if not str(path).startswith(str(config.ARTIFACTS_DIR.resolve())):
        return JSONResponse({"error": "path không hợp lệ"}, status_code=400)
    if not path.is_file():
        return JSONResponse({"error": "file không tồn tại"}, status_code=404)
    return FileResponse(path)


# SVG placeholder khi upload đã bị xóa / không còn trên disk
_MISSING_UPLOAD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">'
    '<rect width="128" height="128" rx="12" fill="#1e293b"/>'
    '<rect x="8" y="8" width="112" height="112" rx="10" fill="none" '
    'stroke="#475569" stroke-width="2" stroke-dasharray="6 4"/>'
    '<path d="M36 84l18-22 14 16 12-10 20 24H36z" fill="#334155"/>'
    '<circle cx="52" cy="48" r="10" fill="#475569"/>'
    '<text x="64" y="112" text-anchor="middle" fill="#94a3b8" '
    'font-family="system-ui,sans-serif" font-size="11">ảnh đã xóa</text>'
    "</svg>"
)


@app.get("/uploads/{filename}")
async def get_upload(filename: str):
    """Serve ảnh chat upload — thiếu file thì trả thumbnail placeholder (tránh 404 vỡ UI)."""
    from fastapi.responses import Response

    if ".." in filename or "/" in filename or "\\" in filename:
        return Response(
            content=_MISSING_UPLOAD_SVG.encode("utf-8"),
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-cache", "X-Upload-Missing": "1"},
        )
    path = (config.UPLOADS_DIR / filename).resolve()
    if not str(path).startswith(str(config.UPLOADS_DIR.resolve())):
        return Response(
            content=_MISSING_UPLOAD_SVG.encode("utf-8"),
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-cache", "X-Upload-Missing": "1"},
        )
    if not path.is_file():
        return Response(
            content=_MISSING_UPLOAD_SVG.encode("utf-8"),
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-cache", "X-Upload-Missing": "1"},
        )
    return FileResponse(path)


# ---------- Static UI ----------

app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")

_ASSET_V_CACHE: tuple[float, str] | None = None


def _web_asset_version() -> str:
    """Một version chung cho CSS/JS — max mtime trong web/ (tự đổi khi sửa file)."""
    import time

    global _ASSET_V_CACHE
    now = time.monotonic()
    if _ASSET_V_CACHE and (now - _ASSET_V_CACHE[0]) < 2.0:
        return _ASSET_V_CACHE[1]

    latest = 0
    try:
        for path in config.WEB_DIR.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".js", ".css", ".html"}:
                continue
            try:
                latest = max(latest, int(path.stat().st_mtime))
            except OSError:
                continue
    except OSError:
        latest = int(time.time())
    ver = str(latest or int(time.time()))
    _ASSET_V_CACHE = (now, ver)
    return ver


@app.middleware("http")
async def _no_cache_ui_assets(request, call_next):
    """Tránh Chrome giữ JS/CSS cũ — ẩn danh được mà tab thường không thấy project."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/")
async def index():
    html_path = config.WEB_DIR / "index.html"
    text = html_path.read_text(encoding="utf-8")
    text = text.replace("__ASSET_V__", _web_asset_version())
    return HTMLResponse(text)


if __name__ == "__main__":
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
    uvicorn.run(
        "orchestrator.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,
    )
