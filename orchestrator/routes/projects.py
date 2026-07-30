"""Projects management API routes."""
import os
import subprocess
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import config, settings
from ..board import store

router = APIRouter(tags=["projects"])


class ProjectIn(BaseModel):
    name: str
    slug: str = ""
    project_dir: str = ""


class ProjectPatch(BaseModel):
    name: str = ""
    project_dir: str = ""
    api_base: str = ""


def get_git_info(project_dir: str) -> dict:
    if not project_dir or not os.path.exists(os.path.join(project_dir, ".git")):
        return {"is_git_repo": False, "has_uncommitted_changes": False, "provider": "none", "remote_url": ""}
    try:
        res = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_dir, capture_output=True, text=True, check=False, timeout=3
        )
        remote_url = res.stdout.strip()
        url_lower = remote_url.lower()
        if "github" in url_lower:
            provider = "github"
        elif "gitlab" in url_lower:
            provider = "gitlab"
        elif "bitbucket" in url_lower:
            provider = "bitbucket"
        else:
            provider = "git"

        st_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir, capture_output=True, text=True, check=False, timeout=3
        )
        has_uncommitted_changes = bool(st_res.stdout.strip())

        return {
            "is_git_repo": True,
            "has_uncommitted_changes": has_uncommitted_changes,
            "provider": provider,
            "remote_url": remote_url
        }
    except Exception:
        return {"is_git_repo": True, "has_uncommitted_changes": False, "provider": "git", "remote_url": ""}


@router.get("/api/projects")
async def list_projects():
    seen: dict[str, str] = {}
    for t in store.list_tasks(include_archived=False):
        if t.project and t.project not in seen:
            seen[t.project] = t.project_dir or ""
    settings.ensure_project_from_tasks(list(seen.items()))
    projs = settings.projects()
    for p in projs:
        p["git_info"] = get_git_info(p.get("project_dir") or "")
    return {
        "projects": projs,
        "active_project": settings.active_project(),
        "projects_root": settings.effective_projects_root(),
        "projects_root_custom": settings.projects_root(),
    }


@router.post("/api/projects")
async def create_project(body: ProjectIn):
    name = body.name.strip()
    if not name:
        return JSONResponse({"error": "cần tên project"}, status_code=400)
    slug = (body.slug or name).strip()
    p = settings.upsert_project(slug, name=name, project_dir=body.project_dir.strip())
    return {"ok": True, "project": p, "active_project": p["slug"]}


@router.patch("/api/projects/{slug}")
async def patch_project(slug: str, body: ProjectPatch):
    p = settings.get_project(slug)
    if not p:
        return JSONResponse({"error": "project không tồn tại"}, status_code=404)

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


@router.post("/api/projects/{slug}/select")
async def select_project(slug: str):
    from ..main import switch_backend
    p = settings.get_project(slug)
    if not p:
        for t in store.list_tasks(include_archived=False):
            if t.project == slug:
                p = settings.upsert_project(slug, name=slug, project_dir=t.project_dir or "")
                break
    if not p:
        return JSONResponse({"error": "project không tồn tại"}, status_code=404)
    settings.set_active_project(slug)
    await switch_backend(slug)
    return {"ok": True, "active_project": slug, "project": p}


@router.post("/api/projects/{slug}/restart-backend")
async def restart_project_backend(slug: str):
    from ..main import _stop_backend, _start_backend
    p = settings.get_project(slug)
    if not p:
        return JSONResponse({"error": "project không tồn tại"}, status_code=404)
    _stop_backend(slug)
    started = await _start_backend(slug)
    return {"ok": True, "project": slug, "backend_started": started}


@router.delete("/api/projects/{slug}")
async def delete_project(slug: str):
    from ..paths import safe_remove_project_dir
    from ..main import _stop_backend

    p = settings.get_project(slug)
    all_tasks = [t for t in store.list_tasks(include_archived=True) if t.project == slug]
    tasks = [t for t in all_tasks if t.status != "archived"]
    if not p and not all_tasks:
        return JSONResponse({"error": "project không tồn tại"}, status_code=404)

    _stop_backend(slug)

    dirs: list[str] = []
    if p and p.get("project_dir"):
        dirs.append(p["project_dir"])
    for t in all_tasks:
        if t.project_dir and t.project_dir not in dirs:
            dirs.append(t.project_dir)
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
    store.add_chat("conan", note)

    return {
        "ok": True,
        "archived_tasks": archived,
        "removed_dirs": removed_dirs,
        "dir_errors": dir_errors,
        "killed_processes": killed,
        "active_project": settings.active_project(),
        "projects": settings.projects(),
    }
