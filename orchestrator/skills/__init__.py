"""Skill catalog — Reasonix-style index + on-demand bodies + agent subagent profiles."""
from .loader import (
    Skill,
    compose_agent_system_prompt,
    format_skills_block,
    format_skills_index,
    get_agent_profile,
    get_skill,
    list_skills,
    load_prompt_skill,
    match_skills_for_task,
    resolve_skill_name,
)

__all__ = [
    "Skill",
    "compose_agent_system_prompt",
    "format_skills_block",
    "format_skills_index",
    "get_agent_profile",
    "get_skill",
    "list_skills",
    "load_prompt_skill",
    "match_skills_for_task",
    "resolve_skill_name",
]
