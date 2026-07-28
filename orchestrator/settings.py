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
    # LLM tools: mỗi entry = 1 endpoint OpenAI-compatible (base_url + model + api_key)
    "llm_tools": [],
    # Gán tool_id cho từng vai trò: planner | coder | critic | summary
    "role_models": {},
    # Git tokens cho private repo: [{"name", "host", "token"}]
    "git_tokens": [],
}

ROLE_KEYS = ("planner", "coder", "critic", "summary")
ROLE_LABELS = {
    "planner": "Planner / Orchestrator",
    "coder": "Coding / Debug",
    "critic": "QA / Critic",
    "summary": "Summary / Memory",
}
AGENT_ROLE = {
    "jarvis": "planner",
    "stark": "coder",
    "banner": "coder",
    "hawkeye": "critic",
    "pepper": "summary",
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


def upsert_project(slug: str, name: str = "", project_dir: str = "") -> dict:
    """Tạo hoặc cập nhật project theo slug. Trả về project dict."""
    import re
    from pathlib import Path

    slug = re.sub(r"[^a-z0-9]+", "-", (slug or "").lower()).strip("-")[:40] or "project"
    data = load()
    existing = {p["slug"]: p for p in data.get("projects", [])}
    if slug in existing:
        p = existing[slug]
        if name:
            p["name"] = name
        if project_dir:
            p["project_dir"] = project_dir
    else:
        dir_path = project_dir or str(config.WORKSPACE_DIR / "projects" / slug)
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        p = {
            "slug": slug,
            "name": name or slug,
            "project_dir": dir_path,
        }
        data.setdefault("projects", []).append(p)
    data["active_project"] = slug
    save(data)
    return p


def get_project(slug: str) -> dict | None:
    for p in projects():
        if p["slug"] == slug:
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
    data = load()
    existing = {p["slug"] for p in data.get("projects", [])}
    changed = False
    for slug, project_dir in task_projects:
        if not slug or slug in existing:
            continue
        data.setdefault("projects", []).append({
            "slug": slug,
            "name": slug,
            "project_dir": project_dir or str(config.WORKSPACE_DIR / "projects" / slug),
        })
        existing.add(slug)
        changed = True
    if changed:
        save(data)


# ---------- LLM tools (multi-provider) ----------

def _seed_llm_from_env(data: dict) -> dict:
    """Lần đầu: seed llm_tools + role_models từ .env nếu chưa có."""
    tools = data.get("llm_tools") or []
    roles = data.get("role_models") or {}

    # Migrate: mọi tool cũ chưa có enabled → bật
    migrated = False
    for t in tools:
        if "enabled" not in t:
            t["enabled"] = True
            migrated = True

    if tools and all(roles.get(r) for r in ROLE_KEYS):
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
        tools.append({
            "id": tid,
            "name": model,
            "base_url": config.LLM_BASE_URL,
            "model": model,
            "api_key": config.LLM_API_KEY,
            "enabled": True,
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

    entry = {
        "id": tid,
        "name": (name or model).strip(),
        "base_url": base_url.rstrip("/"),
        "model": model.strip(),
        "api_key": api_key.strip(),
        "enabled": True,
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
    """Bật/tắt tool. Không xóa. Nếu tắt mà role đang dùng → chuyển sang tool khác còn bật."""
    data = _seed_llm_from_env(load())
    tools = data.get("llm_tools", [])
    tool = next((t for t in tools if t.get("id") == tool_id), None)
    if not tool:
        return None
    tool["enabled"] = bool(enabled)
    if not enabled:
        fallback = next((t["id"] for t in tools if t.get("enabled", True) and t["id"] != tool_id), "")
        roles = data.get("role_models", {})
        for r in ROLE_KEYS:
            if roles.get(r) == tool_id:
                roles[r] = fallback
        data["role_models"] = roles
    save(data)
    return tool


def set_role_model(role: str, tool_id: str) -> None:
    if role not in ROLE_KEYS:
        raise ValueError(f"role phải là một trong {ROLE_KEYS}")
    data = _seed_llm_from_env(load())
    tool = next((t for t in data.get("llm_tools", []) if t["id"] == tool_id), None)
    if tool_id and not tool:
        raise ValueError(f"llm tool không tồn tại: {tool_id}")
    if tool and not tool.get("enabled", True):
        raise ValueError(f"model đang tắt — hãy bật lại trước khi gán vai trò")
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
