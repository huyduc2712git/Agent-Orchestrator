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

_API_BASE_CACHE: dict[str, tuple[float, str]] = {}  # legacy; probe đã tắt — chỉ clear
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
    # FIX bug-7028: the public preview host serves ONLY the preview root
    # (dist/ for built projects, project dir otherwise). The old project_dir
    # fallback exposed raw source (src/**, vite.config.ts, tsconfig.json) and
    # QA artifacts (probe-*.txt, *.log) of the whole repo on the public host.
    for root in (serve_root,):
        try:
            root_res = root.resolve()
            cand = (root / rel).resolve()
        except (OSError, ValueError):
            continue
        if not str(cand).startswith(str(root_res)):
            continue
        if cand.is_dir():
            cand = cand / "index.html"
        if cand.is_file():
            return cand

    fname = Path(rel).name
    matches: list[Path] = []
    # FIX bug-7028: rglob fallback must stay inside the preview root only.
    for root in (serve_root,):
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


# FIX bug-2208: source disclosure - the static preview host used to serve
# EVERY file inside the project dir, so GET /preview/<project>/server.cjs
# returned the full backend source, and server*.log / verify*.txt leaked
# internal runtime info (ports, absolute Windows paths, past bug notes),
# package.json etc. Preview is meant for public static assets (index.html,
# dist, .css/.js/.png/...) only, so requests are checked against a
# deny-list of internal extensions/names BEFORE any file resolution.
# FIX bug-7028: the public host is for BUILD-OUTPUT assets only. Anything that
# is not a static browser asset (TypeScript source, configs, QA/probe
# artifacts, logs, secrets, manifests, dependency/VCS dirs) is refused.
_PREVIEW_ALLOW_EXT = frozenset({
    ".html", ".htm", ".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".avif", ".ico", ".bmp", ".woff", ".woff2", ".ttf", ".eot",
    ".otf", ".mp4", ".webm", ".mp3", ".ogg", ".wav", ".json", ".webmanifest",
})
_PREVIEW_DENY_EXT = frozenset({
    ".cjs", ".mjs", ".log", ".py", ".pyc", ".pem", ".key", ".p12", ".pfx",
    ".lock", ".bak", ".sql", ".sqlite", ".sqlite3", ".db", ".ts", ".tsx",
    ".jsx", ".mts", ".cts", ".map", ".txt", ".md", ".yml", ".yaml", ".toml",
    ".ini", ".cfg", ".conf", ".env", ".crt", ".cer", ".tsbuildinfo",
})
_PREVIEW_DENY_FILES = frozenset({
    "package.json", "package-lock.json", "npm-shrinkwrap.json",
    "yarn.lock", "pnpm-lock.yaml", "verify.txt", "ping_check.txt",
})
# raw source / QA-artifact dirs are NEVER public (only the dist/ copy of
# public/ assets is served via the preview root)
_PREVIEW_DENY_DIRS = ("node_modules", ".git", ".svn", ".hg", "src", "public", "qa-shots", "coverage")


def _is_public_preview_asset(rel_path: str) -> bool:
    """Allow-list for the public static preview host.

    FIX bug-7028 (source disclosure): the old deny-list only blocked a handful
    of extensions/names (.cjs/.log/package.json/...), so src/**, vite.config.ts,
    tsconfig.json and probe-*.txt leaked as 200 on the public host. Now a strict
    allow-list of BUILD-OUTPUT asset extensions is required, and raw-source /
    config / QA-artifact paths are refused with 403 even before file lookup.
    Returns False for anything that is not a public static asset: backend
    source (server.cjs), TypeScript source (src/**), configs (vite.config.ts,
    tsconfig*.json), QA/probe artifacts (probe-*.txt, qa-*, *.log), manifests
    (package.json), dotfiles/secrets (.env*) and dependency/VCS dirs
    (node_modules, .git). Returns True for index.html and ordinary static
    build-output assets only.
    """
    p = rel_path.strip("/") or ""
    if not p:
        return True
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or ".." in parts:
        return False
    if parts[0] in _PREVIEW_DENY_DIRS:
        return False
    name = parts[-1]
    if name.startswith("."):
        return False  # dotfile / secret (e.g. .env, .env.local)
    ext = Path(name).suffix.lower()
    if ext in _PREVIEW_DENY_EXT:
        return False
    if name in _PREVIEW_DENY_FILES:
        return False
    # FIX bug-7028: strict allow-list — only build-output asset extensions.
    if ext not in _PREVIEW_ALLOW_EXT:
        return False
    # config / QA artifacts must stay private even with an allowed extension
    low = name.lower()
    if low.startswith("probe") or low.startswith("qa-") or low.startswith("check-"):
        return False
    if low.startswith("server.") or low.startswith("verify"):
        return False
    if re.match(r"^(tsconfig|vite|webpack|rollup|babel|jest|vitest|postcss|tailwind|eslint|prettier|vercel|firebase|netlify)", low):
        return False
    if low.endswith((".config.json", ".config.js", ".config.ts", ".config.mjs")):
        return False
    return True


@router.get("/preview/{project}")
async def preview_project_noslash(project: str):
    return RedirectResponse(url=f"/preview/{project}/", status_code=307)


@router.get("/preview/{project}/")
async def preview_project_index(project: str):
    return await preview(project, "index.html")


@router.get("/preview/{project}/{file_path:path}")
async def preview(project: str, file_path: str = ""):
    # FIX bug-8991: reject null byte in URL path BEFORE any pathlib operation.
    # Starlette decodes %00 -> "\x00"; (root / rel).resolve() then raises
    # ValueError("embedded null character in path"), which is NOT an OSError,
    # so it escaped the try/except below and uvicorn replied 500.
    if "\x00" in file_path or "\x00" in project:
        return JSONResponse({"error": "bad request: null byte in path"}, status_code=400)
    project_dir = _resolve_preview_project_dir(project)
    if project_dir is None:
        return JSONResponse(
            {"error": f"project '{project}' không tìm thấy thư mục (settings/task path)"},
            status_code=404,
        )

    serve_root = _preview_serve_root(project_dir)
    rel_path = file_path.strip("/") or "index.html"
    # FIX bug-2208: deny-list before resolving/serving - backend source, logs
    # and verify artifacts must never be exposed by the public preview host.
    if not _is_public_preview_asset(rel_path):
        return JSONResponse(
            {"error": "forbidden: not a public preview asset"},
            status_code=403,
        )
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
    """Chỉ dùng api_base đã cấu hình cho đúng project.

    Không còn auto-probe cổng 3000/8000/… — probe hay gắn nhầm backend của
    app khác (vd voxbeat \"Giai Điệu Việt\") vào preview ocr-dashboard →
    /api/* trả HTML/JSON foreign → agent tạo bug cross-app giả (bug-5686).
    Project SPA tĩnh không có backend: để trống api_base → proxy trả 502 JSON.
    """
    if not slug:
        return None
    sp = settings.get_project(slug) or {}
    configured = (sp.get("api_base") or "").strip().rstrip("/")
    if configured:
        return configured
    # Xóa cache probe cũ (nếu còn từ bản trước) để không tái dùng port nhầm
    _API_BASE_CACHE.pop(slug, None)
    return None


# Prefix thuộc Orchestrator — không proxy sang project api_base
_ORCH_API_PREFIXES = (
    "skills", "board", "chat", "settings", "projects", "tasks",
    "git", "mcp", "agents", "uploads",
)


@router.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_project_api(path: str, request: Request):
    # FIX bug-8991: reject null byte in URL path BEFORE building the upstream
    # URL. httpx.build_request() raises httpx.InvalidURL for "\x00" in the URL;
    # InvalidURL is NOT an httpx.HTTPError subclass, so it escaped the
    # except below and uvicorn replied 500.
    if "\x00" in path:
        return JSONResponse({"error": "bad request: null byte in path"}, status_code=400)
    head = (path or "").split("/", 1)[0].lower()
    if head in _ORCH_API_PREFIXES:
        return JSONResponse(
            {"error": f"/api/{path} là API Orchestrator — không proxy"},
            status_code=404,
        )
    slug = _project_from_referer(request.headers.get("referer", ""))
    if not slug:
        # Agent http_get thường không gửi Referer — dùng Active Project.
        # An toàn vì không còn auto-probe port của app khác.
        slug = settings.active_project() or ""
    api_base = await _resolve_project_api_base(slug)
    if not api_base:
        return JSONResponse(
            {
                "error": "project chưa cấu hình api_base — không proxy /api/* (tránh gắn nhầm backend app khác)",
                "hint": "Settings → Projects → api_base (vd http://127.0.0.1:3000). SPA tĩnh không cần API thì để trống.",
                "project": slug or None,
            },
            status_code=502,
        )

    sp = settings.get_project(slug) or {}
    # bug-9462: mock spec (Prism basePath '/') has no /api prefix in routes --
    # forwarding /api/{path} as-is caused NO_PATH_MATCHED 404. Per-project
    # opt-in 'api_strip_prefix': true forwards /api/{path} -> {api_base}/{path}.
    strip_prefix = bool(sp.get('api_strip_prefix'))
    url = f"{api_base}/{path}" if strip_prefix else f"{api_base}/api/{path}"
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
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as e:
        await client.aclose()
        log.warning("API proxy %s -> %s failed: %s", path, api_base, e)
        return JSONResponse({"error": f"proxy failed: {e}", "target": url}, status_code=502)

    # FIX bug-5686: API contract — /api/* must never return HTML to the
    # browser. A text/html upstream response means we hit an SPA fallback
    # (Vite dev server or an Express `app.get('*')` catch-all), i.e. the
    # proxy selected the wrong target. Reject as 502 JSON instead of
    # streaming a foreign app's index.html to the client.
    upstream_ct = (resp.headers.get("content-type") or "").lower()
    if "html" in upstream_ct:
        await resp.aclose()
        await client.aclose()
        log.warning(
            "API proxy /api/%s -> %s returned text/html (SPA fallback), rejecting",
            path, api_base,
        )
        return JSONResponse(
            {
                "error": "backend returned HTML for API path (SPA fallback) - not a JSON API",
                "path": f"/api/{path}",
                "target": api_base,
            },
            status_code=502,
        )

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
