"""API catalog skills (native / reasonix / addy / workspace)."""
from fastapi import APIRouter, Query

from ..skills.loader import get_skill, list_skills, reload_catalog

router = APIRouter(prefix="/api", tags=["skills"])


@router.get("/skills")
async def api_list_skills(
    source: str | None = Query(None, description="agent|native|reasonix|addy|workspace"),
    agent: str | None = Query(None),
):
    reload_catalog()
    items = list_skills(source=source, agent=agent)
    by_source: dict[str, list] = {}
    for s in items:
        by_source.setdefault(s.source, []).append(s.to_public_dict())
    return {
        "skills": [s.to_public_dict() for s in items],
        "by_source": by_source,
        "count": len(items),
    }


@router.get("/skills/{name}")
async def api_get_skill(name: str):
    sk = get_skill(name)
    if not sk:
        return {"error": "not found", "name": name}
    d = sk.to_public_dict()
    d["body"] = sk.body
    return d
