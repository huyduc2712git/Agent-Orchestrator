"""Client OpenAI-compatible — hỗ trợ nhiều endpoint (base_url + api_key + model)."""
import asyncio
import json
import logging
from typing import Any

import httpx

from . import config

log = logging.getLogger("llm")

_clients: dict[str, httpx.AsyncClient] = {}


def _client_key(base_url: str, api_key: str) -> str:
    return f"{base_url}|{api_key[:12]}"


def _get_client(base_url: str | None = None, api_key: str | None = None) -> httpx.AsyncClient:
    url = (base_url or config.LLM_BASE_URL).rstrip("/")
    key = api_key if api_key is not None else config.LLM_API_KEY
    ck = _client_key(url, key)
    if ck not in _clients:
        _clients[ck] = httpx.AsyncClient(
            base_url=url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(180.0, connect=20.0),
        )
    return _clients[ck]


class LLMError(Exception):
    pass


async def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.3,
    max_retries: int = 3,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Gọi /chat/completions. Có thể chỉ định model + base_url + api_key theo từng tool."""
    payload: dict[str, Any] = {
        "model": model or config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    client = _get_client(base_url, api_key)
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = await client.post("/chat/completions", json=payload)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            return choice["message"]
        except (httpx.HTTPError, LLMError, KeyError, json.JSONDecodeError) as e:
            last_err = e
            log.warning(
                "LLM call failed [%s @ %s] (attempt %d/%d): %s",
                payload["model"],
                (base_url or config.LLM_BASE_URL),
                attempt,
                max_retries,
                e,
            )
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)
    raise LLMError(
        f"LLM call failed after {max_retries} attempts [{payload['model']}]: {last_err}"
    )


async def chat_text(messages: list[dict[str, Any]], **kw) -> str:
    """Gọi chat và chỉ lấy text content."""
    msg = await chat(messages, **kw)
    return msg.get("content") or ""


def extract_json(text: str) -> Any:
    """Rút khối JSON đầu tiên từ text trả về của model (chịu được ```json fence)."""
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.index("\n") if "\n" in text else len(text)
        text = text[first_nl + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        raise ValueError(f"No JSON found in: {text[:200]}")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text[start:])
    return obj
