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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, settings
from .core.patrol import patrol_loop
from .core.scheduler import scheduler_loop
from .routes import board, chat, git_routes, preview, projects, settings as settings_routes

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


# ---------- Static UI ----------

app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(config.WEB_DIR / "index.html")


if __name__ == "__main__":
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
    uvicorn.run(
        "orchestrator.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
    )
