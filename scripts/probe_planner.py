"""Gọi planner với đúng prompt thật để xem raw output — không tạo task."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator import llm, settings as app_settings  # noqa: E402
from orchestrator.agents.registry import roster_description  # noqa: E402
from orchestrator.board import store  # noqa: E402
from orchestrator.core.orchestrator import PLANNING_PROMPT, _board_snapshot  # noqa: E402
from orchestrator.links import default_registry, detect_links  # noqa: E402
from orchestrator.memory import store as memory  # noqa: E402


async def main(message: str) -> None:
    history = store.list_chat(limit=10)
    history_text = "\n".join(f"{m['role']}: {m['message'][:300]}" for m in history) or "(chưa có)"
    link_hints = default_registry.planning_hints(detect_links(message))
    prompt = PLANNING_PROMPT.format(
        roster=roster_description(),
        memory=memory.read_memory()[-4000:],
        wiki=memory.read_wiki_summary(3000),
        board=_board_snapshot(),
        history=history_text,
        message=message.replace('"', "'"),
        active_project=app_settings.active_project() or "(chưa chọn)",
        link_hints=link_hints,
        projects_root=app_settings.effective_projects_root(),
    )
    planner = app_settings.resolve_llm(role="planner")
    print(f"--- model: {planner['model']} @ {planner['base_url']}")
    raw = await llm.chat_text(
        [{"role": "user", "content": prompt}],
        model=planner["model"],
        base_url=planner["base_url"],
        api_key=planner["api_key"],
    )
    print(f"--- raw len={len(raw)}\n{raw[:3000]}\n--- end raw")
    parsed = llm.extract_json(raw)
    print(f"--- parsed type: {type(parsed).__name__}")
    print(f"--- normalized type: {type(llm.normalize_json_object(parsed)).__name__}")


if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "chạy VoxBeat lên và xem log bên trong có lỗi gì thì tạo task fix giúp tôi"
    asyncio.run(main(msg))
