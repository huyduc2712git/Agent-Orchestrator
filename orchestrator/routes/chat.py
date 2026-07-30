"""Chat and WebSocket routes."""
import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import bus
from ..board import store
from ..core import orchestrator

log = logging.getLogger("api.chat")
router = APIRouter(tags=["chat"])


class ChatIn(BaseModel):
    message: str
    project: str = ""


@router.post("/api/chat")
async def post_chat(body: ChatIn):
    msg = body.message.strip()
    if not msg:
        return JSONResponse({"error": "empty message"}, status_code=400)
    store.add_chat("user", msg)

    async def _run_chat():
        try:
            await orchestrator.handle_chat(msg, project=body.project.strip() or None)
        except Exception as e:
            log.exception("handle_chat crashed")
            store.add_chat(
                "conan",
                f"Xin lỗi, xử lý tin nhắn bị lỗi không mong đợi: {e}. "
                "Thử gửi lại hoặc kiểm tra Settings / đường dẫn project.",
            )

    asyncio.create_task(_run_chat())
    return {"ok": True}


@router.get("/api/chat")
async def get_chat():
    return {"messages": store.list_chat(limit=200)}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    q = bus.subscribe()
    try:
        while True:
            event = await q.get()
            await ws.send_text(json.dumps(event, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)
