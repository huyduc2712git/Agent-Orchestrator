"""Live Preview and Reverse Proxy API routes."""
import re
import time
import logging
from pathlib import Path
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.responses import StreamingResponse

from .. import config, settings
from ..board import store

log = logging.getLogger("api.preview")
router = APIRouter(tags=["preview"])

_API_BASE_CACHE: dict[str, tuple[float, str]] = {}
_API_PROBE_PORTS = (3000, 3001, 8000, 8080, 5000, 5173)
_HOP_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade",
}


def _resolve_preview_project_dir(project: str) -> Path | None:
    candidates: list[Path] = []
    sp = settings.get_project(project)
    if sp and sp.get("project_dir"):
        candidates.append(Path(sp["project_dir"]))

    live = [t for t in store.list_tasks(include_archived=False) if t.project == project and t.project_dir]
    archived = [
        t for t in store.list_tasks(include_archived=True)
        if t.project == project and t.project_dir and t.status == "archived"
    ]
    for t in sorted(live, key=lambda x: x.updated_at or "", reverse=True):
        candidates.append(Path(t.project_dir))
    for t in sorted(archived, key=lambda x: x.updated_at or "", reverse=True):
        candidates.append(Path(t.project_dir))

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
    dist = project_dir / "dist"
    if (dist / "index.html").is_file():
        return dist
    return project_dir


def _rewrite_preview_html(html: str, project: str) -> str:
    base = f"/preview/{project}/"
    html = re.sub(
        r"""((?:href|src|content|action)\s*=\s*["'])/(?!/|preview/)""",
        rf"\1{base}",
        html,
        flags=re.I,
    )
    html = re.sub(
        r"""(url\(\s*["']?)/(?!/|preview/)""",
        rf"\1{base}",
        html,
        flags=re.I,
    )
    html = re.sub(
        r"""(serviceWorker\.register\(\s*["'])/(?!/|preview/)""",
        rf"\1{base}",
        html,
    )
    return html


def _find_preview_file(serve_root: Path, project_dir: Path, rel_path: str) -> Path | None:
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


@router.get("/preview/{project}")
async def preview_project_noslash(project: str):
    return RedirectResponse(url=f"/preview/{project}/", status_code=307)


@router.get("/preview/{project}/")
async def preview_project_index(project: str):
    return await preview(project, "index.html")


@router.get("/preview/{project}/{file_path:path}")
async def preview(project: str, file_path: str = ""):
    project_dir = _resolve_preview_project_dir(project)
    if project_dir is None:
        return JSONResponse(
            {"error": f"project '{project}' không tìm thấy thư mục (settings/task path)"},
            status_code=404,
        )

    serve_root = _preview_serve_root(project_dir)
    rel_path = file_path.strip("/") or "index.html"
    target = _find_preview_file(serve_root, project_dir, rel_path)

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

    if target.suffix.lower() in (".html", ".htm"):
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        return HTMLResponse(
            _rewrite_preview_html(raw, project),
            headers={"Cache-Control": "no-store"},
        )

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


def _project_from_referer(referer: str) -> str:
    m = re.search(r"/preview/([^/?#]+)/?", referer or "")
    return m.group(1) if m else ""


async def _resolve_project_api_base(slug: str) -> str | None:
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

    _API_BASE_CACHE[slug] = (now + 60.0, base_found)
    return base_found or None


@router.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_project_api(path: str, request: Request):
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
