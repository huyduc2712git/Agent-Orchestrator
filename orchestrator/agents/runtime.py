"""Vòng lặp tool-calling: một agent LLM nhận task, dùng tool thực thi thật đến khi xong."""
import asyncio
import json
import logging

from .. import config, llm
from ..board import store
from ..board.models import Task
from .tools import ToolContext, schemas_for

log = logging.getLogger("runtime")


def _sanitize_assistant(msg: dict) -> dict:
    """Bỏ reasoning_content và tool_calls=null trước khi đưa lại vào history."""
    clean: dict = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        clean["tool_calls"] = msg["tool_calls"]
    return clean


async def run_agent(
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    task: Task,
    tool_names: list[str],
    max_iterations: int = config.MAX_AGENT_ITERATIONS,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Chạy agent trên một task. Trả về message tổng kết cuối cùng của agent."""
    from .. import settings as app_settings

    # Resolve LLM từ Settings theo agent role nếu chưa truyền tường minh
    if model is None or base_url is None or api_key is None:
        cfg = app_settings.resolve_llm_for_agent(agent_name)
        model = model or cfg["model"]
        base_url = base_url or cfg["base_url"]
        api_key = api_key if api_key is not None else cfg["api_key"]

    ctx = ToolContext(agent_name, task)
    tools = schemas_for(tool_names)
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    log.info("[%s/%s] model=%s url=%s", agent_name, task.id, model, base_url)

    for iteration in range(1, max_iterations + 1):
        # Kiểm tra real-time nếu task hoặc task cha đã bị operator dừng/blocked/archived
        curr_task = store.get_task(task.id)
        parent_task = store.get_task(curr_task.parent_id) if (curr_task and curr_task.parent_id) else None
        if (curr_task and curr_task.status in ("blocked", "failed", "archived")) or (parent_task and parent_task.status in ("blocked", "failed", "archived")):
            status_str = parent_task.status if (parent_task and parent_task.status in ("blocked", "failed", "archived")) else (curr_task.status if curr_task else "blocked")
            log.info("[%s/%s] Task hoặc Task cha status là '%s' — dừng agent loop lập tức.", agent_name, task.id, status_str)
            return f"[Tiến trình bị ngắt do task hoặc task cha chuyển sang {status_str}]"

        # Nhắc nhở Agent khi gần chạm giới hạn lượt (còn 5 lượt cuối)
        if iteration == max_iterations - 5:
            messages.append({
                "role": "user",
                "content": f"⚠️ CẢNH BÁO TIẾN ĐỘ: Bạn đã sử dụng {iteration}/{max_iterations} lượt gọi tool và chỉ còn 5 lượt cuối cùng! Hãy tập trung hoàn tất các bước chính, kiểm tra kết quả và tổng kết/báo cáo công việc ngay.",
            })

        msg = await llm.chat(
            messages, tools=tools, model=model, base_url=base_url, api_key=api_key
        )
        messages.append(_sanitize_assistant(msg))

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            final = (msg.get("content") or "").strip()
            if final:
                return final
            # model trả rỗng không tool call — nhắc nó tổng kết
            messages.append({
                "role": "user",
                "content": "Hãy tổng kết kết quả công việc của bạn (deliverable) bằng text.",
            })
            continue

        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            log.info("[%s/%s] tool %s(%s)", agent_name, task.id, name,
                     json.dumps(args, ensure_ascii=False)[:200])
            result = await asyncio.to_thread(ctx.execute, name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    # hết quota vòng lặp — ép tổng kết lần cuối, KHÔNG cho dùng tool nữa
    store.add_event(
        task.id, "system", "system",
        f"{agent_name} chạm giới hạn {max_iterations} vòng tool-calling — ép tổng kết cuối.",
    )
    messages.append({
        "role": "user",
        "content": (
            "Bạn đã hết lượt dùng tool. KHÔNG gọi tool nữa. Dựa trên toàn bộ kết quả "
            "đã kiểm tra ở trên, tổng kết ngay bằng text: đã làm/xác nhận được gì, còn gì "
            "chưa chắc chắn. Nếu nhiệm vụ yêu cầu verdict, bắt buộc chốt một dòng "
            "'VERDICT: ...' hoặc 'PASS'/'FAIL' dựa trên bằng chứng đã có."
        ),
    })
    try:
        final_msg = await llm.chat(
            messages, model=model, base_url=base_url, api_key=api_key
        )  # không truyền tools
        final = (final_msg.get("content") or "").strip()
        if final:
            return final
    except llm.LLMError:
        log.exception("Final summary call failed for %s/%s", agent_name, task.id)
    return "(agent dừng do chạm giới hạn vòng lặp — công việc có thể chưa hoàn tất)"
