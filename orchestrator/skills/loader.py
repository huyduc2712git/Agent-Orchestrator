"""Load SKILL.md catalogs (native / reasonix / vendor/addy / workspace)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("skills")

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)
_MAX_AUTO = 2
_MAX_RUN_SKILL_PER_TASK = 3
_DESC_INDEX_LEN = 110

# Native heuristics (title+description) — only these auto-match without tags
_NATIVE_HEURISTICS: list[tuple[str, re.Pattern[str]]] = [
    ("replace-brand-assets", re.compile(
        r"(logo|favicon|apple-touch|pwa\s*icon|user-uploads|Ảnh đã lưu|brand\s*asset)",
        re.I,
    )),
    ("figma-mcp", re.compile(r"figma\.com|figma\s*link", re.I)),
    ("same-origin-api", re.compile(r"\b/api/|same-origin|api_base|proxy", re.I)),
    ("vite-fe-smoke", re.compile(
        r"\b(vite|npm\s+run\s+build|live\s*url|smoke|preview/)",
        re.I,
    )),
    ("extend-existing-app", re.compile(
        r"(không\s*scaffold|khong\s*scaffold|extend|đã có sẵn|da co san|existing\s*app)",
        re.I,
    )),
]

# Pipeline tags are board modifiers — not workflow skills
_PIPELINE_TAGS = frozenset({
    "skip-security", "scope-ui", "force-security", "deploy-prod", "db-migration",
    "no-app-chat",
})


@dataclass
class Skill:
    name: str
    description: str
    body: str
    source: str  # native | reasonix | addy | agent | workspace
    path: str
    run_as: str = "inline"
    invocation: str = "auto"
    allowed_tools: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    agent_key: str = ""  # maps profile → registry agent (kid/conan/…)

    def to_public_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "runAs": self.run_as,
            "invocation": self.invocation,
            "allowed_tools": list(self.allowed_tools),
            "agents": list(self.agents),
            "agent_key": self.agent_key,
            "invoke": f"@{self.name}",
            "path": self.path,
        }

    @property
    def is_agent_profile(self) -> bool:
        return self.run_as == "subagent" or self.source == "agent"


def _skills_pkg_root() -> Path:
    return Path(__file__).resolve().parent


def _workspace_skills_root() -> Path | None:
    try:
        from .. import config
        root = Path(getattr(config, "WORKSPACE_DIR", "") or "")
        if root.is_dir():
            p = root / "skills"
            return p if p.is_dir() else None
    except Exception:
        pass
    # fallback relative to repo
    p = _skills_pkg_root().parents[1] / "workspace" / "skills"
    return p if p.is_dir() else None


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = _FRONTMATTER_RE.match(text.strip())
    if not m:
        return {}, text.strip()
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip().lower()] = val.strip().strip("\"'")
    return meta, m.group(2).strip()


def _parse_list(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
    return [x.strip() for x in raw.split(",") if x.strip()]


def _source_from_path(path: Path, pkg: Path) -> str:
    try:
        rel = path.relative_to(pkg).as_posix()
    except ValueError:
        return "workspace"
    if rel.startswith("native/"):
        return "native"
    if rel.startswith("reasonix/"):
        return "reasonix"
    if rel.startswith("vendor/addy/"):
        return "addy"
    if rel.startswith("agents/"):
        return "agent"
    return "builtin"


def _load_skill_file(path: Path, source: str | None = None) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        log.warning("Cannot read skill %s: %s", path, e)
        return None
    meta, body = _parse_frontmatter(text)
    name = (meta.get("name") or path.parent.name or path.stem).strip().lower()
    name = re.sub(r"[^a-z0-9._-]+", "-", name).strip("-")
    if not name or not body:
        return None
    desc = meta.get("description") or body.splitlines()[0][:_DESC_INDEX_LEN]
    src = (meta.get("source") or source or "builtin").lower()
    agent_key = (meta.get("agent-key") or meta.get("agent_key") or "").strip().lower()
    return Skill(
        name=name,
        description=desc.strip(),
        body=body,
        source=src,
        path=str(path),
        run_as=(meta.get("runas") or meta.get("run_as") or "inline").lower(),
        invocation=(meta.get("invocation") or "auto").lower(),
        allowed_tools=_parse_list(meta.get("allowed-tools") or meta.get("allowed_tools") or ""),
        agents=[a.lower() for a in _parse_list(meta.get("agents") or "")],
        agent_key=agent_key,
    )


def _iter_skill_md(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in root.rglob("SKILL.md"):
        # skip nested references noise
        if "node_modules" in p.parts:
            continue
        out.append(p)
    return out


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Skill]:
    """name → Skill. Priority: workspace > agents > native > reasonix > addy."""
    pkg = _skills_pkg_root()
    layers: list[tuple[str, list[Path]]] = [
        ("addy", _iter_skill_md(pkg / "vendor" / "addy")),
        ("reasonix", _iter_skill_md(pkg / "reasonix")),
        ("native", _iter_skill_md(pkg / "native")),
        ("agent", _iter_skill_md(pkg / "agents")),
    ]
    ws = _workspace_skills_root()
    if ws:
        layers.append(("workspace", _iter_skill_md(ws)))

    catalog: dict[str, Skill] = {}
    for source, paths in layers:
        for path in sorted(paths):
            sk = _load_skill_file(path, source=source)
            if not sk:
                continue
            catalog[sk.name] = sk
    return catalog


def reload_catalog() -> None:
    _catalog.cache_clear()


def list_skills(
    *,
    source: str | None = None,
    agent: str | None = None,
    include_manual: bool = True,
    playbooks_only: bool = False,
) -> list[Skill]:
    items = list(_catalog().values())
    if source:
        items = [s for s in items if s.source == source.lower()]
    if agent:
        ag = agent.lower()
        items = [s for s in items if not s.agents or ag in s.agents]
    if not include_manual:
        items = [s for s in items if s.invocation != "manual"]
    if playbooks_only:
        # Reasonix: manual subagent profiles không vào pinned index
        items = [
            s for s in items
            if s.invocation != "manual" and s.source not in ("agent",)
        ]
    return sorted(items, key=lambda s: (s.source, s.name))


def get_skill(name: str) -> Skill | None:
    return _catalog().get(resolve_skill_name(name) or "")


def resolve_skill_name(name: str) -> str | None:
    key = (name or "").strip().lstrip("@").lower()
    if not key or key in _PIPELINE_TAGS:
        return None
    if key in _catalog():
        return key
    # allow underscore/hyphen swap
    alt = key.replace("_", "-")
    if alt in _catalog():
        return alt
    return None


def format_skills_index(*, agent: str | None = None, max_desc: int = _DESC_INDEX_LEN) -> str:
    """Reasonix-style one-liner index — playbooks only (không gồm agent profiles manual)."""
    skills = list_skills(agent=agent, playbooks_only=True)
    if not skills:
        return ""
    lines = [
        "# Skills — playbooks you can invoke",
        "",
        "One-liner index. Before non-trivial work, if a skill is relevant call "
        "`run_skill` with `{ \"name\": \"<id>\" }` (bare name, no @). "
        "Bodies load on demand — do not invent playbook steps. "
        "User may also attach `@skill-name` on the task.",
        "",
        "```",
    ]
    for s in skills:
        desc = s.description.replace("\n", " ").strip()
        if len(desc) > max_desc:
            desc = desc[: max_desc - 1] + "…"
        tag = f" [{s.source}]" if s.source in ("reasonix", "addy", "native") else ""
        lines.append(f"- {s.name}{tag} — {desc}")
    lines.append("```")
    return "\n".join(lines)


def get_agent_profile(agent_key: str) -> Skill | None:
    """Primary subagent profile for registry key (kid, heiji, …) — not conan-plan/final."""
    key = (agent_key or "").strip().lower()
    if not key:
        return None
    sk = get_skill(key)
    if sk and sk.source == "agent" and sk.name == key:
        return sk
    for s in list_skills(source="agent", include_manual=True):
        if s.name == key:
            return s
    for s in list_skills(source="agent", include_manual=True):
        if (
            s.agent_key == key
            and not s.name.startswith("conan-")
            and s.name != "memory-summarize"
            and s.name != "common-agent-rules"
        ):
            return s
    return None


def compose_agent_system_prompt(agent_key: str, *, include_playbook_index: bool = True) -> str:
    """Reasonix: profile body = full child system prompt (+ common rules + playbook index)."""
    parts: list[str] = []
    profile = get_agent_profile(agent_key)
    if profile and profile.body.strip():
        parts.append(profile.body.strip())
    else:
        parts.append(f"Bạn là agent `{agent_key}` của AI Orchestrator.")

    common = get_skill("common-agent-rules")
    if common and common.body.strip():
        parts.append(common.body.strip())

    if "create_bug_ticket" in (profile.allowed_tools if profile else []):
        parts.append(
            "Bug ngoài phạm vi: search_tasks rồi create_bug_ticket "
            "(frontend→Kid, backend→Agasa). Không chôn bug trong comment."
        )

    if include_playbook_index:
        idx = format_skills_index(agent=agent_key)
        if idx:
            parts.append(idx)
    return "\n\n".join(parts)


def load_prompt_skill(name: str, **fmt: str) -> str:
    """Load a prompt skill body and format placeholders."""
    sk = get_skill(name)
    if not sk:
        return ""
    body = sk.body
    if fmt:
        try:
            body = body.format(**fmt)
        except (KeyError, ValueError):
            # leave unformatted braces if partial
            for k, v in fmt.items():
                body = body.replace("{" + k + "}", str(v))
    return body


def format_skills_block(skills: list[Skill]) -> str:
    if not skills:
        return ""
    parts = ["## Active Skills (follow checklists)", ""]
    for s in skills:
        parts.append(f"### Skill `{s.name}` ({s.source})")
        parts.append(s.body.strip())
        parts.append("")
    return "\n".join(parts).rstrip()


def _is_playbook(sk: Skill) -> bool:
    """Agent subagent profiles không auto-load / không gắn tag playbook."""
    if sk.invocation == "manual" and sk.source == "agent":
        return False
    if sk.run_as == "subagent" and sk.source == "agent":
        return False
    return True


def match_skills_for_task(
    *,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
    assignee: str = "",
    max_skills: int = _MAX_AUTO,
) -> list[Skill]:
    """Explicit tags first, then native heuristics. Cap max_skills."""
    chosen: list[Skill] = []
    seen: set[str] = set()

    for raw in tags or []:
        key = resolve_skill_name(str(raw))
        if not key or key in seen:
            continue
        sk = get_skill(key)
        if not sk or not _is_playbook(sk):
            continue
        if assignee and sk.agents and assignee.lower() not in sk.agents:
            continue
        chosen.append(sk)
        seen.add(key)
        if len(chosen) >= max_skills:
            return chosen

    blob = f"{title}\n{description}"
    for name, pat in _NATIVE_HEURISTICS:
        if name in seen:
            continue
        if not pat.search(blob):
            continue
        sk = get_skill(name)
        if not sk or not _is_playbook(sk):
            continue
        if assignee and sk.agents and assignee.lower() not in sk.agents:
            continue
        chosen.append(sk)
        seen.add(name)
        if len(chosen) >= max_skills:
            break
    return chosen


# Per-task run_skill budget (in-memory; process lifetime)
_run_skill_counts: dict[str, int] = {}


def run_skill_allowed(task_id: str) -> bool:
    tid = task_id or "_"
    return _run_skill_counts.get(tid, 0) < _MAX_RUN_SKILL_PER_TASK


def note_run_skill(task_id: str) -> int:
    tid = task_id or "_"
    _run_skill_counts[tid] = _run_skill_counts.get(tid, 0) + 1
    return _run_skill_counts[tid]
