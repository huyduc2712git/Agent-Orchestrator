"""Kiểm tra 3 model: chat thường + tool calling."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import llm

MODELS = ["deepseek-v4-flash-free", "nemotron-3-ultra-free", "mimo-v2.5-free"]

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_status",
        "description": "Get build status of a project",
        "parameters": {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": ["project"],
        },
    },
}]


async def check(model: str):
    print(f"\n=== {model} ===")
    try:
        msg = await llm.chat(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            model=model, max_retries=1,
        )
        print("  chat     :", (msg.get("content") or "")[:60].replace("\n", " "))
    except Exception as e:
        print("  chat     : FAILED —", str(e)[:120])
        return

    try:
        msg2 = await llm.chat(
            [{"role": "user", "content": "Check build status of project 'demo'. Use the tool."}],
            tools=TOOLS, model=model, max_retries=1,
        )
        tc = msg2.get("tool_calls")
        print("  tools    :", "SUPPORTED " + json.dumps(tc[0]["function"], ensure_ascii=False)[:80] if tc else "NOT USED")
    except Exception as e:
        print("  tools    : FAILED —", str(e)[:120])


async def main():
    for m in MODELS:
        await check(m)


asyncio.run(main())
