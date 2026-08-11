"""Registry agent: metadata + tools; persona/system prompt từ skills/agents (Reasonix subagent)."""
from dataclasses import dataclass, field

from .. import settings as app_settings
from .tools import DEFAULT_WORKER_TOOLS, QA_TOOLS


@dataclass
class Agent:
    key: str
    display: str
    specialty: str
    role: str  # planner | coder | critic | summary
    tools: list[str] = field(default_factory=lambda: list(DEFAULT_WORKER_TOOLS))
    # Short fallback if skill missing (dev/broken install)
    persona_fallback: str = ""

    def system_prompt(self) -> str:
        """Reasonix-style: profile body + common rules + playbook index."""
        try:
            from ..skills.loader import compose_agent_system_prompt, get_agent_profile

            text = compose_agent_system_prompt(self.key)
            if text.strip():
                return text
            profile = get_agent_profile(self.key)
            if profile and profile.body.strip():
                return profile.body.strip()
        except Exception:
            pass
        return self.persona_fallback or f"Bạn là agent `{self.key}` của AI Orchestrator."

    def llm_config(self) -> dict:
        """Resolve base_url / model / api_key từ Settings (runtime)."""
        return app_settings.resolve_llm_for_agent(self.key)

    @property
    def model(self) -> str:
        return self.llm_config()["model"]

    @property
    def persona(self) -> str:
        """Compat: first lines of agent skill body (UI / debug)."""
        try:
            from ..skills.loader import get_agent_profile

            p = get_agent_profile(self.key)
            if p and p.body.strip():
                return p.body.strip().split("\n\n")[0][:500]
        except Exception:
            pass
        return self.persona_fallback


AGENTS: dict[str, Agent] = {
    "conan": Agent(
        key="conan",
        display="Conan",
        specialty="Orchestrator — phân tích, điều phối, lập kế hoạch, review cuối, không code",
        role="planner",
        tools=[
            "read_file", "list_dir", "ls", "glob", "grep", "search_files",
            "http_get", "web_fetch", "git_status", "todo_write", "run_skill",
            "search_tasks", "post_message",
        ],
        persona_fallback="Bạn là Conan — chat orchestrator. Không code, không tạo bug ticket.",
    ),
    "kid": Agent(
        key="kid",
        display="Kaito Kid",
        specialty="Frontend Builder — UI/UX, ảo thuật thị giác, scaffolding, viết code chính",
        role="coder",
        tools=list(DEFAULT_WORKER_TOOLS),
        persona_fallback="Bạn là Kaito Kid — frontend builder.",
    ),
    "agasa": Agent(
        key="agasa",
        display="Agasa",
        specialty="Backend Specialist — API, chế tạo công nghệ/gadget, data, logic phía server, script",
        role="coder",
        tools=[
            n for n in DEFAULT_WORKER_TOOLS
            if n not in ("figma_get", "mcp_list_tools", "mcp_call")
        ],
        persona_fallback="Bạn là Giáo sư Agasa — backend specialist.",
    ),
    "heiji": Agent(
        key="heiji",
        display="Heiji",
        specialty="Visual QA — quan sát sắc bén, chụp live, so sánh Figma/reference, CSS verify, KHÔNG sửa code",
        role="critic",
        tools=list(QA_TOOLS),
        persona_fallback="Bạn là Hattori Heiji — Visual QA. Không sửa code.",
    ),
    "haibara": Agent(
        key="haibara",
        display="Ai Haibara",
        specialty="Quality Reviewer — cẩn trọng, logic, tổng hợp báo cáo QA Complete, chỉ ra rủi ro",
        role="summary",
        tools=[
            "search_tasks", "post_message", "read_file", "list_dir", "ls", "glob", "grep",
            "http_get", "web_fetch", "todo_write", "run_skill",
        ],
        persona_fallback="Bạn là Ai Haibara — quality reviewer. Không code.",
    ),
    "akai": Agent(
        key="akai",
        display="Shuichi Akai",
        specialty="Security Reviewer — auth/authz, injection, secret leakage, dependency CVE",
        role="critic",
        tools=[
            "read_file", "list_dir", "ls", "glob", "grep", "search_files",
            "http_get", "web_fetch",
            "todo_write", "run_skill", "search_tasks", "post_message", "create_bug_ticket",
        ],
        persona_fallback="Bạn là Shuichi Akai — security reviewer. Không code.",
    ),
    "amuro": Agent(
        key="amuro",
        display="Rei Furuya (Amuro)",
        specialty="Penetration Tester — thử tấn công thật trên môi trường preview/staging",
        role="critic",
        tools=[
            "read_file", "list_dir", "ls", "glob", "grep", "search_files",
            "http_get", "web_fetch", "run_skill",
            "search_tasks", "post_message", "create_bug_ticket", "screenshot_url",
        ],
        persona_fallback="Bạn là Amuro — pentester trên preview/staging.",
    ),
}

# Agent được phép nhận subtask thực thi từ scheduler
WORKER_KEYS = ["kid", "agasa", "heiji", "haibara", "akai", "amuro"]


def roster_description() -> str:
    """Mô tả đội hình cho Conan dùng khi lập kế hoạch phân công."""
    return "\n".join(
        f"- {a.key}: {a.specialty}" for a in AGENTS.values() if a.key in WORKER_KEYS
    )


def roster_models() -> list[dict[str, str]]:
    """Danh sách agent ↔ model đang dùng (cho UI)."""
    out = []
    for a in AGENTS.values():
        cfg = a.llm_config()
        out.append({
            "key": a.key,
            "display": a.display,
            "specialty": a.specialty,
            "role": a.role,
            "model": cfg["model"],
            "tool_id": cfg.get("id", ""),
            "tool_name": cfg.get("name", ""),
        })
    return out
