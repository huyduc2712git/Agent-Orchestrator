"""Client OpenAI-compatible — hỗ trợ nhiều endpoint (base_url + api_key + model)."""
import asyncio
import json
import logging
import re
from typing import Any

import httpx

from . import config

log = logging.getLogger("llm")

_clients: dict[str, httpx.AsyncClient] = {}


def _client_key(base_url: str, api_key: str) -> str:
    return f"{base_url}|{api_key[:12]}"


def _reset_client(base_url: str | None = None, api_key: str | None = None) -> None:
    url = (base_url or config.LLM_BASE_URL).rstrip("/")
    key = api_key if api_key is not None else config.LLM_API_KEY
    ck = _client_key(url, key)
    client = _clients.pop(ck, None)
    if client:
        try:
            asyncio.create_task(client.aclose())
        except Exception:
            pass


def _get_client(base_url: str | None = None, api_key: str | None = None) -> httpx.AsyncClient:
    url = (base_url or config.LLM_BASE_URL).rstrip("/")
    key = api_key if api_key is not None else config.LLM_API_KEY
    ck = _client_key(url, key)
    if ck not in _clients or _clients[ck].is_closed:
        _clients[ck] = httpx.AsyncClient(
            base_url=url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(300.0, connect=30.0, write=60.0, pool=30.0),
        )
    return _clients[ck]


class LLMError(Exception):
    pass


def _record_usage(
    data: dict[str, Any],
    model: str,
    base_url: str,
    *,
    task_id: str = "",
) -> None:
    usage = data.get("usage") if isinstance(data, dict) else None
    if not usage:
        return
    try:
        from . import settings

        settings.record_llm_usage(model, base_url, usage, task_id=task_id)
    except Exception:
        log.debug("Không ghi được LLM usage", exc_info=True)


async def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.3,
    max_retries: int = 4,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Gọi /chat/completions. Có thể chỉ định model + base_url + api_key theo từng tool."""
    payload: dict[str, Any] = {
        "model": model or config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    usage_task_id = (task_id or "").strip()

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        client = _get_client(base_url, api_key)
        curr_model = payload["model"]
        curr_base_url = base_url or config.LLM_BASE_URL
        try:
            resp = await client.post("/chat/completions", json=payload)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            # 413: ảnh/payload quá lớn — không retry (cần nén phía caller)
            if resp.status_code == 413:
                raise LLMError(
                    "HTTP 413 Payload Too Large — ảnh/request vượt giới hạn provider."
                )
            # 400 với ảnh: thường model text-only — không retry vô ích
            if resp.status_code == 400:
                body = resp.text[:500]
                has_image = any(
                    isinstance(m.get("content"), list)
                    and any(
                        isinstance(p, dict) and p.get("type") == "image_url"
                        for p in m["content"]
                    )
                    for m in messages
                    if isinstance(m, dict)
                )
                if has_image:
                    raise LLMError(
                        f"HTTP 400 Bad Request (model có thể không hỗ trợ ảnh): {body}"
                    )
            resp.raise_for_status()
            data = resp.json()
            # OpenCode đôi khi trả HTTP 200 kèm {"error":{...}} thay vì choices
            if isinstance(data, dict) and data.get("error") and "choices" not in data:
                err = data["error"]
                if isinstance(err, dict):
                    msg = err.get("message") or err.get("type") or str(err)
                else:
                    msg = str(err)
                raise LLMError(f"Provider error: {msg}")
            if "choices" not in data:
                raise LLMError(f"Missing 'choices' in response: {resp.text[:1000]}")
            choice = data["choices"][0]
            message = choice.get("message") or {}
            finish = choice.get("finish_reason") or choice.get("native_finish_reason")
            # Một số model (thinking) để trống content, nhét text vào reasoning*
            if not (message.get("content") or "").strip():
                for alt in ("reasoning_content", "reasoning", "refusal"):
                    alt_val = message.get(alt)
                    if isinstance(alt_val, str) and alt_val.strip():
                        message = {**message, "content": alt_val}
                        break
            content = (message.get("content") or "").strip()
            has_tools = bool(message.get("tool_calls"))
            # Model thinking đốt hết budget vào reasoning -> content rỗng/cụt.
            # Nới max_tokens rồi gọi lại thay vì trả về JSON dở dang.
            # Ghi usage cả khi retry (token vẫn bị trừ ở provider)
            _record_usage(data, curr_model, curr_base_url, task_id=usage_task_id)
            if finish == "length" and payload["max_tokens"] < config.LLM_MAX_TOKENS_CEILING:
                grown = min(payload["max_tokens"] * 2, config.LLM_MAX_TOKENS_CEILING)
                usage = data.get("usage") or {}
                log.warning(
                    "finish_reason=length (max_tokens=%s, reasoning=%s) -> retry với %s",
                    payload["max_tokens"],
                    (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                    grown,
                )
                payload["max_tokens"] = grown
                last_err = LLMError("truncated (finish_reason=length)")
                continue
            if not content and not has_tools:
                raise LLMError(
                    f"Empty model content (finish_reason={finish}, keys={list(message.keys())})"
                )
            return message
        except (httpx.HTTPError, LLMError, KeyError, json.JSONDecodeError) as e:
            last_err = e
            # Nếu là timeout hoặc network error, xóa client đệm để mở TCP socket mới
            if isinstance(e, (httpx.TimeoutException, httpx.NetworkError)):
                _reset_client(base_url, api_key)

            log.warning(
                "LLM call failed [%s @ %s] (attempt %d/%d): %s",
                curr_model,
                curr_base_url,
                attempt,
                max_retries,
                e,
            )

            # Model có giới hạn output nhỏ hơn -> hạ max_tokens thay vì retry vô ích
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 400:
                body = e.response.text[:500].lower()
                if "max_tokens" in body or "max output" in body or "too large" in body:
                    reduced = max(4096, payload["max_tokens"] // 2)
                    if reduced < payload["max_tokens"]:
                        log.warning("Provider từ chối max_tokens=%s -> hạ xuống %s", payload["max_tokens"], reduced)
                        payload["max_tokens"] = reduced
                        continue

            # Fallback model mặc định khi 403 (forbidden/hết token), 401, 429, 5xx, hoặc upstream provider error
            err_s = str(e).lower()
            status_code = getattr(getattr(e, "response", None), "status_code", None)

            is_auth_or_quota = (
                status_code in (401, 402, 403, 429)
                or any(k in err_s for k in ("403", "401", "429", "forbidden", "unauthorized", "quota", "credit", "balance", "insufficient"))
            )
            is_upstream = (
                (status_code is not None and status_code >= 500)
                or any(k in err_s for k in ("upstream", "server_error", "provider error", "missing 'choices'", "overloaded"))
            )
            is_custom = (payload["model"] != config.LLM_MODEL) or (base_url and base_url != config.LLM_BASE_URL)

            if (is_auth_or_quota or is_upstream) and is_custom:
                reason = "401/403 (hết token/quota/forbidden)" if is_auth_or_quota else "rate-limit/upstream error"
                # Reset old client before switching base_url
                _reset_client(base_url, api_key)

                payload["model"] = config.LLM_MODEL
                base_url = config.LLM_BASE_URL
                api_key = config.LLM_API_KEY

                log.warning(
                    "%s trên [%s @ %s] -> Chuyển ngay lập tức sang model mặc định [%s @ %s]",
                    reason,
                    curr_model,
                    curr_base_url,
                    payload["model"],
                    base_url,
                )
                continue

            # 413 / payload quá lớn: retry vô ích
            if "413" in str(e) or "payload too large" in str(e).lower():
                break

            if attempt < max_retries:
                await asyncio.sleep(3 * attempt)
    raise LLMError(
        f"LLM call failed after {max_retries} attempts [{payload['model']}]: {last_err}"
    )


async def chat_text(messages: list[dict[str, Any]], **kw) -> str:
    """Gọi chat và chỉ lấy text content."""
    msg = await chat(messages, **kw)
    return (msg.get("content") or "").strip()


def extract_json(text: str) -> Any:
    """Rút khối JSON đầu tiên từ text trả về của model (chịu được ```json fence)."""
    text = (text or "").strip()
    # BOM / zero-width
    text = text.lstrip("\ufeff\u200b\u200c\u200d")
    if not text:
        raise ValueError("No JSON found in: (empty response)")
    if text.startswith("```"):
        first_nl = text.index("\n") if "\n" in text else len(text)
        text = text[first_nl + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    # Đôi khi model bọc JSON trong prose — lấy từ { hoặc [
    # Ưu tiên object { } nếu có (planner cần dict, không phải list)
    brace = text.find("{")
    bracket = text.find("[")
    if brace >= 0 and (bracket < 0 or brace < bracket):
        start = brace
    elif bracket >= 0:
        start = bracket
    else:
        start = None
    if start is None:
        for i, ch in enumerate(text):
            if ch in "{[":
                start = i
                break
    if start is None:
        raise ValueError(f"No JSON found in: {text[:200]}")
    chunk = text[start:]
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(chunk)
        return normalize_json_object(obj)
    except json.JSONDecodeError:
        repaired = _repair_truncated_json(chunk)
        if repaired is not None:
            log.warning("JSON bị cắt giữa chừng — đã vá lại (%d ký tự)", len(chunk))
            return normalize_json_object(repaired)
        raise


def _scan_json(prefix: str) -> tuple[list[str] | None, bool]:
    """Quét prefix JSON -> (stack ngoặc còn mở, có đang ở giữa string không)."""
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in prefix:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack[-1] != ch:
                return None, False
            stack.pop()
    return stack, in_string


def _repair_truncated_json(chunk: str) -> Any | None:
    """Vá JSON bị cắt giữa chừng (finish_reason=length).

    Cắt lùi về mốc an toàn gần nhất (`,` `}` `]` ngoài string) rồi đóng ngoặc còn mở.
    Không dùng cách "cắt tới } cuối cùng" vì với planner nó hay ra mảng subtasks
    thay vì object gốc.
    """
    stack, in_string = _scan_json(chunk)
    if stack is not None and not stack and not in_string:
        return None  # JSON đủ ngoặc — lỗi khác, không phải truncate

    marks: list[int] = []
    in_string = False
    escaped = False
    for i, ch in enumerate(chunk):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in ",}]":
            marks.append(i)

    for cut in reversed(marks[-80:]):
        prefix = chunk[:cut] if chunk[cut] == "," else chunk[: cut + 1]
        prefix = prefix.rstrip().rstrip(",")
        # Bỏ key dở dang:  "title":
        prefix = re.sub(r',?\s*"(?:[^"\\]|\\.)*"\s*:\s*$', "", prefix).rstrip().rstrip(",")
        open_stack, unterminated = _scan_json(prefix)
        if open_stack is None or unterminated:
            continue
        try:
            return json.loads(prefix + "".join(reversed(open_stack)))
        except json.JSONDecodeError:
            continue
    return None


def normalize_json_object(obj: Any) -> Any:
    """Planner đôi khi trả [{...}] hoặc [[ {...} ]] — lấy dict đầu tiên tìm được."""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                return item
            if isinstance(item, list):
                nested = normalize_json_object(item)
                if isinstance(nested, dict):
                    return nested
            if isinstance(item, str):
                s = item.strip()
                if s.startswith("{") or s.startswith("["):
                    try:
                        nested = normalize_json_object(json.loads(s))
                        if isinstance(nested, dict):
                            return nested
                    except (json.JSONDecodeError, TypeError):
                        pass
        if len(obj) == 1:
            return normalize_json_object(obj[0])
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                return normalize_json_object(json.loads(s))
            except (json.JSONDecodeError, TypeError):
                pass
    return obj


async def chat_json(
    messages: list[dict[str, Any]],
    *,
    max_attempts: int = 3,
    expect_object: bool = False,
    **kw,
) -> Any:
    """Gọi chat và parse JSON; retry kèm nhắc nếu model trả rỗng / không phải JSON.

    `expect_object`: bắt buộc kết quả là dict — model trả array/scalar sẽ được retry.
    """
    msgs = list(messages)
    last_err: Exception | None = None
    last_raw = ""
    for attempt in range(1, max_attempts + 1):
        try:
            raw = await chat_text(msgs, **kw)
            last_raw = raw
            result = extract_json(raw)
            if expect_object and not isinstance(result, dict):
                raise ValueError(
                    f"cần JSON object nhưng nhận {type(result).__name__}: {str(result)[:200]}"
                )
            return result
        except (ValueError, LLMError, json.JSONDecodeError) as e:
            last_err = e
            log.warning(
                "chat_json attempt %d/%d failed: %s | raw=%r",
                attempt,
                max_attempts,
                e,
                last_raw[:400],
            )
            if attempt >= max_attempts:
                break
            msgs = msgs + [
                {"role": "assistant", "content": last_raw[:1500] or "(rỗng)"},
                {
                    "role": "user",
                    "content": (
                        "Phản hồi trên không hợp lệ. Trả về DUY NHẤT một JSON OBJECT "
                        '(bắt đầu bằng "{" và kết thúc bằng "}"), KHÔNG phải mảng, '
                        "không markdown, không giải thích thêm."
                    ),
                },
            ]
            await asyncio.sleep(1.5 * attempt)
    raise LLMError(
        f"Không parse được JSON từ model: {last_err} | raw={last_raw[:300]!r}"
    )
