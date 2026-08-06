"""Settings and AI model configuration API routes."""
import asyncio
import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import settings
from ..board import store

log = logging.getLogger("api.settings")
router = APIRouter(tags=["settings"])


def _mask(token: str) -> str:
    return token[:9] + "…" + token[-4:] if len(token) > 16 else "…"


@router.get("/api/settings")
async def get_settings():
    from ..agents.registry import roster_models

    active_tasks = store.list_tasks(status=["in_progress"])
    has_active_tasks = len(active_tasks) > 0

    tools = []
    for t in settings.llm_tools():
        usage = settings.llm_usage_for(t.get("base_url", ""), t.get("model", ""))
        tools.append({
            "id": t["id"],
            "model": t["model"],
            "base_url": t.get("base_url", ""),
            "enabled": t.get("enabled", True),
            "is_default": t.get("is_default", False) or (t.get("model") in settings.DEFAULT_SYSTEM_MODELS),
            "usage": usage,
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
        "active_project": settings.active_project(),
        "active_project_detail": (
            settings.get_project(settings.active_project())
            if settings.active_project()
            else None
        ),
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


@router.post("/api/settings/llm-tools")
async def add_llm_tool(body: LlmToolIn):
    base_url = body.base_url.strip().rstrip("/")
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

    import httpx
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
            {"error": "Lỗi HTTP 429 (Rate Limit / Hết Hạn Ngạch): Tài khoản API Key tại Provider này đã dùng hết lượt token/credit miễn phí. Vui lòng nạp thêm credit hoặc đổi sang Provider khác."},
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


@router.patch("/api/settings/llm-tools/{tool_id:path}")
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


@router.delete("/api/settings/llm-tools/{tool_id:path}")
async def delete_llm_tool(tool_id: str):
    try:
        ok = settings.delete_llm_tool(tool_id)
    except ValueError as err:
        return JSONResponse({"error": str(err)}, status_code=400)
    if not ok:
        return JSONResponse({"error": "không tìm thấy tool"}, status_code=404)
    return {"ok": True, "role_models": settings.role_models()}


@router.put("/api/settings/role-models")
async def update_role_model(body: RoleModelIn):
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
    from ..agents.registry import roster_models
    return {"ok": True, "role_models": settings.role_models(), "agents": roster_models()}


@router.post("/api/settings/figma-tokens")
async def add_figma_token(body: FigmaTokenIn):
    name = body.name.strip()
    token = body.token.strip()
    if not name or not token:
        return JSONResponse({"error": "cần đủ name và token"}, status_code=400)
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


@router.delete("/api/settings/figma-tokens/{name}")
async def delete_figma_token(name: str):
    removed = settings.remove_figma_token(name)
    if not removed:
        return JSONResponse({"error": "không tìm thấy token"}, status_code=404)
    return {"ok": True}


class GitTokenIn(BaseModel):
    name: str
    host: str = "github.com"
    token: str


@router.post("/api/settings/git-tokens")
async def add_git_token(body: GitTokenIn):
    name = body.name.strip()
    host = body.host.strip() or "github.com"
    token = body.token.strip()
    if not name or not token:
        return JSONResponse({"error": "cần đủ name và token"}, status_code=400)
    settings.add_git_token(name, host, token)
    return {"ok": True, "host": host.lower().removeprefix("https://").split("/")[0]}


@router.delete("/api/settings/git-tokens/{name}")
async def delete_git_token(name: str):
    if not settings.remove_git_token(name):
        return JSONResponse({"error": "không tìm thấy token"}, status_code=404)
    return {"ok": True}


class ProjectsRootIn(BaseModel):
    path: str = ""


@router.put("/api/settings/projects-root")
async def put_projects_root(body: ProjectsRootIn):
    try:
        root = settings.set_projects_root(body.path)
    except OSError as e:
        return JSONResponse({"error": f"không tạo được thư mục: {e}"}, status_code=400)
    return {
        "ok": True,
        "projects_root": root,
        "projects_root_custom": settings.projects_root(),
    }


class ProjectMcpIn(BaseModel):
    mcp_url: str = ""
    slug: str = ""  # mặc định = active_project


@router.put("/api/settings/project-mcp")
async def put_project_mcp(body: ProjectMcpIn):
    """Lưu link MCP cho project đang focus (hoặc slug chỉ định)."""
    slug = (body.slug or "").strip() or settings.active_project()
    if not slug:
        return JSONResponse(
            {"error": "Chưa có project đang focus — chọn project trên sidebar trước."},
            status_code=400,
        )
    if not settings.get_project(slug):
        return JSONResponse({"error": f"Project `{slug}` không tồn tại"}, status_code=404)
    p = settings.set_project_mcp_url(slug, body.mcp_url)
    return {"ok": True, "project": p, "active_project": settings.active_project()}


@router.post("/api/settings/project-mcp/test")
async def test_project_mcp(body: ProjectMcpIn):
    """Thử kết nối MCP (list tools)."""
    from .. import config
    from ..mcp import McpError, mcp_list_tools

    slug = (body.slug or "").strip() or settings.active_project()
    url = (body.mcp_url or "").strip()
    token = ""
    if not url and slug:
        proj = settings.get_project(slug) or {}
        url = (proj.get("mcp_url") or "").strip()
        token = (proj.get("mcp_token") or "").strip()
    if not url:
        url = f"{config.BASE_URL}/mcp/figma"
    try:
        tools = mcp_list_tools(url, token=token)
        return {
            "ok": True,
            "mcp_url": url,
            "tools": [t.get("name") for t in tools],
            "count": len(tools),
        }
    except McpError as e:
        return JSONResponse({"ok": False, "mcp_url": url, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse(
            {"ok": False, "mcp_url": url, "error": f"{type(e).__name__}: {e}"},
            status_code=400,
        )


@router.get("/api/settings/mcp-builtin-url")
async def mcp_builtin_url():
    from .. import config
    return {"ok": True, "mcp_url": f"{config.BASE_URL}/mcp/figma"}
