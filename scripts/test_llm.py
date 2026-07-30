"""Smoke test endpoint LLM: chat thường + tool calling."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import llm


async def main():
    print("=== Test 1: chat thuong ===")
    msg = await llm.chat([{"role": "user", "content": "Reply with exactly: OK"}])
    print(json.dumps(msg, ensure_ascii=False)[:500])

    print("\n=== Test 2: tool calling ===")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    msg2 = await llm.chat(
        [{"role": "user", "content": "What's the weather in Hanoi? Use the tool."}],
        tools=tools,
    )
    print(json.dumps(msg2, ensure_ascii=False)[:800])
    if msg2.get("tool_calls"):
        print("\nTOOL CALLING: SUPPORTED")
    else:
        print("\nTOOL CALLING: NOT USED (may need text fallback)")



if __name__ == "__main__":
    asyncio.run(main())
