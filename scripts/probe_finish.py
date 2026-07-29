"""Xem finish_reason + usage của planner để xác nhận response bị cắt."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from orchestrator import settings as app_settings  # noqa: E402


async def main() -> None:
    planner = app_settings.resolve_llm(role="planner")
    prompt = (
        "Trả về DUY NHẤT một JSON object mô tả kế hoạch 4 subtask cho việc chạy app "
        "VoxBeat, kiểm tra log và fix lỗi. Mỗi description dài ít nhất 80 từ tiếng Việt."
    )
    async with httpx.AsyncClient(
        base_url=planner["base_url"].rstrip("/"),
        headers={"Authorization": f"Bearer {planner['api_key']}"},
        timeout=300.0,
    ) as c:
        r = await c.post(
            "/chat/completions",
            json={
                "model": planner["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 4096,
            },
        )
        data = r.json()
    choice = data["choices"][0]
    msg = choice.get("message", {})
    print("finish_reason:", choice.get("finish_reason"), "|", choice.get("native_finish_reason"))
    print("usage:", json.dumps(data.get("usage", {})))
    print("content_len:", len(msg.get("content") or ""))
    print("message_keys:", list(msg.keys()))


asyncio.run(main())
