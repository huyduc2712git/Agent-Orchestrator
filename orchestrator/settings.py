"""Settings runtime (workspace/settings.json) — hiện dùng cho danh sách Figma token.

Tách khỏi .env vì đây là cấu hình người dùng thêm/xóa lúc chạy qua UI,
có thể chứa nhiều token của nhiều tài khoản khác nhau.
"""
import json
import threading

from . import config

SETTINGS_PATH = config.WORKSPACE_DIR / "settings.json"
_lock = threading.Lock()

_DEFAULT = {
    "figma_tokens": [],
    "projects": [],  # [{"slug": "...", "name": "...", "project_dir": "..."}]
    "active_project": "",
    # Thư mục gốc clone repo — ngoài cây Orchestrator (tránh nặng workspace)
    "projects_root": "",
    # LLM tools: mỗi entry = 1 endpoint OpenAI-compatible (base_url + model + api_key)
    "llm_tools": [],
    # Gán tool_id cho từng vai trò: planner | coder | critic | summary | vision
    "role_models": {},
    # Git tokens cho private repo: [{"name", "host", "token"}]
    "git_tokens": [],
    # Chờ user chọn thư mục clone: {url, message, project, suggested_dir}
    "pending_clone": None,
}

ROLE_KEYS = ("planner", "coder", "critic", "summary", "vision")
ROLE_LABELS = {
    "planner": "Planner / Orchestrator",
    "coder": "Coding / Debug",
    "critic": "QA / Critic",
    "summary": "Summary / Memory",
    "vision": "Vision / Image (chat đính kèm ảnh)",
}
AGENT_ROLE = {
    "conan": "planner",
    "kid": "coder",
    "agasa": "coder",
    "heiji": "critic",
    "haibara": "summary",
}


def load() -> dict:
    if not SETTINGS_PATH.exists():
        return json.loads(json.dumps(_DEFAULT))
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(_DEFAULT))
    for k, v in _DEFAULT.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    return data


def save(data: dict) -> None:
    with _lock:
        SETTINGS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def figma_tokens() -> list[dict]:
    """[{"name": "...", "token": "figd_..."}]"""
    return load()["figma_tokens"]


def add_figma_token(name: str, token: str) -> None:
    data = load()
    data["figma_tokens"] = [t for t in data["figma_tokens"] if t["name"] != name]
    data["figma_tokens"].append({"name": name, "token": token})
    save(data)


def remove_figma_token(name: str) -> bool:
    data = load()
    before = len(data["figma_tokens"])
    data["figma_tokens"] = [t for t in data["figma_tokens"] if t["name"] != name]
    save(data)
    return len(data["figma_tokens"]) < before


def git_tokens() -> list[dict]:
    """[{"name", "host", "token"}] — host vd github.com / gitlab.com"""
    return load().get("git_tokens", [])


def add_git_token(name: str, host: str, token: str) -> None:
    host = host.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    data = load()
    tokens = [t for t in data.get("git_tokens", []) if t.get("name") != name]
    tokens.append({"name": name.strip(), "host": host, "token": token.strip()})
    data["git_tokens"] = tokens
    save(data)


def remove_git_token(name: str) -> bool:
    data = load()
    before = len(data.get("git_tokens", []))
    data["git_tokens"] = [t for t in data.get("git_tokens", []) if t.get("name") != name]
    save(data)
    return len(data["git_tokens"]) < before


def git_token_for_host(host: str) -> str:
    host = (host or "").lower().removeprefix("www.")
    for t in git_tokens():
        h = (t.get("host") or "").lower().removeprefix("www.")
        if h == host or host.endswith("." + h) or h.endswith("." + host):
            return t.get("token") or ""
    return ""


def projects() -> list[dict]:
    """[{"slug", "name", "project_dir"}]"""
    return load().get("projects", [])


def active_project() -> str:
    return load().get("active_project", "") or ""


def set_active_project(slug: str) -> None:
    data = load()
    data["active_project"] = slug
    save(data)


def projects_root() -> str:
    """Thư mục gốc để clone project mới. Rỗng = default ngoài Orchestrator."""
    return (load().get("projects_root") or "").strip()


def set_projects_root(path: str) -> str:
    from pathlib import Path
    from .paths import default_projects_root

    raw = (path or "").strip()
    if not raw:
        data = load()
        data["projects_root"] = ""
        save(data)
        return str(default_projects_root())
    p = Path(raw).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    data = load()
    data["projects_root"] = str(p)
    save(data)
    return str(p)


def effective_projects_root() -> str:
    from .paths import default_projects_root

    custom = projects_root()
    return custom if custom else str(default_projects_root())


def pending_clone() -> dict | None:
    p = load().get("pending_clone")
    return p if isinstance(p, dict) and p.get("url") else None


def set_pending_clone(payload: dict | None) -> None:
    data = load()
    data["pending_clone"] = payload
    save(data)


def clear_pending_clone() -> None:
    set_pending_clone(None)


def upsert_project(slug: str, name: str = "", project_dir: str = "", api_base: str = "", start_command: str = "") -> dict:
    """Tạo hoặc cập nhật project theo slug. Trả về project dict."""
    import re
    from pathlib import Path
    from .paths import default_projects_root, is_plausible_fs_path

    slug = re.sub(r"[^a-z0-9]+", "-", (slug or "").lower()).strip("-")[:40] or "project"
    # Không lưu path giả từ URL (https:// → s:\github.com\...)
    if project_dir and not is_plausible_fs_path(project_dir):
        project_dir = ""
    api_base = (api_base or "").strip().rstrip("/")
    start_command = (start_command or "").strip()

    data = load()
    existing = {p["slug"]: p for p in data.get("projects", [])}
    if slug in existing:
        p = existing[slug]
        if name:
            p["name"] = name
        if project_dir:
            p["project_dir"] = project_dir
        # Sửa project_dir hỏng đã lưu trước đó
        elif p.get("project_dir") and not is_plausible_fs_path(p["project_dir"]):
            root = projects_root() or str(default_projects_root())
            p["project_dir"] = str(Path(root) / slug)
        if api_base:
            p["api_base"] = api_base
        if start_command:
            p["start_command"] = start_command
    else:
        if project_dir:
            dir_path = project_dir
        else:
            root = projects_root() or str(default_projects_root())
            dir_path = str(Path(root) / slug)
        try:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
        except OSError:
            root = projects_root() or str(default_projects_root())
            dir_path = str(Path(root) / slug)
            Path(dir_path).mkdir(parents=True, exist_ok=True)
        p = {
            "slug": slug,
            "name": name or slug,
            "project_dir": dir_path,
        }
        if api_base:
            p["api_base"] = api_base
        if start_command:
            p["start_command"] = start_command
        data.setdefault("projects", []).append(p)
    data["active_project"] = slug
    save(data)
    return p


def get_project(slug: str) -> dict | None:
    from pathlib import Path
    from .paths import is_under_orchestrator
    for p in projects():
        if p["slug"] == slug:
            p_dir = Path(p.get("project_dir", ""))
            eff_dir = Path(effective_projects_root()) / slug
            if eff_dir.exists() and (not p_dir.exists() or is_under_orchestrator(p_dir)):
                p["project_dir"] = str(eff_dir)
            return p
    return None


def remove_project(slug: str) -> bool:
    """Xóa project khỏi settings. Trả True nếu đã xóa."""
    data = load()
    before = len(data.get("projects", []))
    data["projects"] = [p for p in data.get("projects", []) if p.get("slug") != slug]
    if data.get("active_project") == slug:
        remaining = data["projects"]
        data["active_project"] = remaining[0]["slug"] if remaining else ""
    save(data)
    return len(data["projects"]) < before


def ensure_project_from_tasks(task_projects: list[tuple[str, str]]) -> None:
    """Đồng bộ project từ task board (slug, project_dir) vào settings nếu chưa có."""
    from pathlib import Path

    data = load()
    existing = {p["slug"] for p in data.get("projects", [])}
    changed = False
    for slug, project_dir in task_projects:
        if not slug or slug in existing:
            continue
        data.setdefault("projects", []).append({
            "slug": slug,
            "name": slug,
            "project_dir": project_dir or str(Path(effective_projects_root()) / slug),
        })
        existing.add(slug)
        changed = True
    if changed:
        save(data)


# ---------- LLM tools (multi-provider) ----------

DEFAULT_SYSTEM_MODELS = {"deepseek-v4-flash-free", "nemotron-3-ultra-free", "mimo-v2.5-free"}


def _seed_llm_from_env(data: dict) -> dict:
    """Lần đầu: seed llm_tools + role_models từ .env nếu chưa có."""
    tools = data.get("llm_tools") or []
    roles = data.get("role_models") or {}

    migrated = False
    for t in tools:
        is_def = (t.get("model") in DEFAULT_SYSTEM_MODELS) or t.get("is_default", False)
        if t.get("is_default") != is_def:
            t["is_default"] = is_def
            migrated = True
        if is_def and not t.get("enabled", True):
            t["enabled"] = True
            migrated = True
        elif "enabled" not in t:
            t["enabled"] = True
            migrated = True

    # vision không bắt buộc seed — operator tự gán model hỗ trợ ảnh
    _core_roles = tuple(r for r in ROLE_KEYS if r != "vision")
    if tools and all(roles.get(r) for r in _core_roles):
        if migrated:
            data["llm_tools"] = tools
            save(data)
        return data

    changed = migrated
    by_model: dict[str, str] = {t["model"]: t["id"] for t in tools if t.get("model")}

    def _ensure(model: str, label: str) -> str:
        nonlocal changed
        if model in by_model:
            return by_model[model]
        tid = _slug_id(model)
        existing_ids = {t["id"] for t in tools}
        base, n = tid, 2
        while tid in existing_ids:
            tid = f"{base}-{n}"
            n += 1
        is_def = model in DEFAULT_SYSTEM_MODELS
        tools.append({
            "id": tid,
            "name": model,
            "base_url": config.LLM_BASE_URL,
            "model": model,
            "api_key": config.LLM_API_KEY,
            "enabled": True,
            "is_default": is_def,
        })
        by_model[model] = tid
        changed = True
        return tid

    defaults = {
        "planner": (config.MODEL_PLANNER, "Planner (env)"),
        "coder": (config.MODEL_CODER, "Coder (env)"),
        "critic": (config.MODEL_CRITIC, "Critic (env)"),
        "summary": (config.MODEL_SUMMARY, "Summary (env)"),
    }
    if not tools and config.LLM_MODEL:
        _ensure(config.LLM_MODEL, config.LLM_MODEL)

    for role, (model, label) in defaults.items():
        if not roles.get(role):
            roles[role] = _ensure(model, label)
            changed = True

    data["llm_tools"] = tools
    data["role_models"] = roles
    if changed:
        save(data)
    return data


def _slug_id(text: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40]
    return s or "llm-tool"


def llm_tools() -> list[dict]:
    data = _seed_llm_from_env(load())
    return data.get("llm_tools", [])


def enabled_llm_tools() -> list[dict]:
    return [t for t in llm_tools() if t.get("enabled", True)]


def role_models() -> dict[str, str]:
    data = _seed_llm_from_env(load())
    return data.get("role_models", {})


def get_llm_tool(tool_id: str) -> dict | None:
    for t in llm_tools():
        if t.get("id") == tool_id:
            return t
    return None


def add_llm_tool(name: str, base_url: str, model: str, api_key: str, tool_id: str = "") -> dict:
    data = _seed_llm_from_env(load())
    tid = tool_id.strip() or _slug_id(model)
    existing_ids = {t["id"] for t in data.get("llm_tools", [])}
    base, n = tid, 2
    while tid in existing_ids:
        if tool_id.strip() == tid:
            break
        tid = f"{base}-{n}"
        n += 1

    is_def = model.strip() in DEFAULT_SYSTEM_MODELS
    entry = {
        "id": tid,
        "name": (name or model).strip(),
        "base_url": base_url.rstrip("/"),
        "model": model.strip(),
        "api_key": api_key.strip(),
        "enabled": True,
        "is_default": is_def,
    }
    tools = [t for t in data.get("llm_tools", []) if t["id"] != tid]
    tools.append(entry)
    data["llm_tools"] = tools
    roles = data.setdefault("role_models", {})
    for r in ROLE_KEYS:
        if not roles.get(r):
            roles[r] = tid
    save(data)
    return entry


def set_llm_tool_enabled(tool_id: str, enabled: bool) -> dict | None:
    """Bật/tắt tool."""
    data = _seed_llm_from_env(load())
    tools = data.get("llm_tools", [])
    tool = next((t for t in tools if t.get("id") == tool_id or t.get("model") == tool_id or t.get("name") == tool_id), None)
    if not tool:
        return None
    tid = tool["id"]
    is_def = tool.get("model") in DEFAULT_SYSTEM_MODELS or tool.get("is_default", False)
    if is_def and not enabled:
        raise ValueError(f"Model mặc định {tool['model']} luôn ở trạng thái bật")
    tool["enabled"] = bool(enabled)
    if not enabled:
        fallback = next((t["id"] for t in tools if t.get("enabled", True) and t.get("id") != tid), "")
        roles = data.get("role_models", {})
        for r in ROLE_KEYS:
            if roles.get(r) in (tid, tool.get("model"), tool_id):
                roles[r] = fallback
        data["role_models"] = roles
    save(data)
    return tool


def _role_default_tool_id(role: str, tools: list[dict]) -> str:
    defaults = {
        "planner": config.MODEL_PLANNER,
        "coder": config.MODEL_CODER,
        "critic": config.MODEL_CRITIC,
        "summary": config.MODEL_SUMMARY,
        "vision": config.MODEL_VISION,
    }
    # Vision không có default free — không fallback sang model text
    if role == "vision" and not defaults.get("vision"):
        return ""
    target_model = defaults.get(role, "")
    matched = next((t["id"] for t in tools if t.get("model") == target_model and t.get("enabled", True)), "")
    if matched:
        return matched
    if role == "vision":
        return ""
    return next((t["id"] for t in tools if t.get("enabled", True)), "")


def delete_llm_tool(tool_id: str) -> bool:
    """Xóa LLM tool khỏi hệ thống (chỉ cho phép xóa user-added tool)."""
    data = _seed_llm_from_env(load())
    tools = data.get("llm_tools", [])
    tool = next((t for t in tools if t.get("id") == tool_id or t.get("model") == tool_id or t.get("name") == tool_id), None)
    if not tool:
        return False
    is_def = tool.get("model") in DEFAULT_SYSTEM_MODELS or tool.get("is_default", False)
    if is_def:
        raise ValueError(f"Không thể xóa model mặc định hệ thống ({tool['model']})")
    
    tid = tool["id"]
    tmodel = tool.get("model", "")
    data["llm_tools"] = [t for t in tools if t.get("id") != tid]
    
    roles = data.get("role_models", {})
    for r in ROLE_KEYS:
        if roles.get(r) in (tid, tmodel, tool_id):
            roles[r] = _role_default_tool_id(r, data["llm_tools"])
    data["role_models"] = roles
    save(data)
    return True


def set_role_model(role: str, tool_id: str) -> None:
    if role not in ROLE_KEYS:
        raise ValueError(f"role phải là một trong {ROLE_KEYS}")
    data = _seed_llm_from_env(load())
    tool = next((t for t in data.get("llm_tools", []) if t["id"] == tool_id), None)
    if tool_id and not tool:
        raise ValueError(f"llm tool không tồn tại: {tool_id}")
    if tool and not tool.get("enabled", True):
        raise ValueError("model đang tắt — hãy bật lại trước khi gán vai trò")
    data.setdefault("role_models", {})[role] = tool_id
    save(data)


def resolve_llm(role: str | None = None, tool_id: str | None = None) -> dict:
    """Trả về {id, name, base_url, model, api_key} cho role hoặc tool_id.

    Ưu tiên tool đang bật. Fallback: .env LLM_*.
    """
    tools = llm_tools()
    roles = role_models()
    tid = tool_id
    if not tid and role:
        tid = roles.get(role, "")
    tool = next((t for t in tools if t.get("id") == tid), None) if tid else None
    # Nếu tool gán đang tắt → lấy tool enabled đầu tiên
    if tool and not tool.get("enabled", True):
        tool = next((t for t in tools if t.get("enabled", True)), None)
    if not tool:
        tool = next((t for t in tools if t.get("enabled", True)), None)
    if tool:
        return {
            "id": tool["id"],
            "name": tool.get("model") or tool.get("name", ""),
            "base_url": tool["base_url"].rstrip("/"),
            "model": tool["model"],
            "api_key": tool.get("api_key") or config.LLM_API_KEY,
            "enabled": tool.get("enabled", True),
        }
    return {
        "id": "",
        "name": config.LLM_MODEL,
        "base_url": config.LLM_BASE_URL,
        "model": config.LLM_MODEL,
        "api_key": config.LLM_API_KEY,
        "enabled": True,
    }


def resolve_llm_for_agent(agent_key: str) -> dict:
    role = AGENT_ROLE.get(agent_key, "planner")
    return resolve_llm(role=role)
