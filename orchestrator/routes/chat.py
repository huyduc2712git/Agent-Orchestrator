"""Chat and WebSocket routes."""
import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import bus, config
from ..board import store
from ..core import orchestrator

log = logging.getLogger("api.chat")
router = APIRouter(tags=["chat"])

_ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


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


@router.post("/api/chat/upload-image")
async def upload_chat_image(
    file: UploadFile = File(...),
    message: str = Form(""),
    project: str = Form(""),
):
    """Nhận ảnh đính kèm chat → lưu uploads → analyze_image_and_chat."""
    raw_name = (file.filename or "image.png").strip()
    ext = Path(raw_name).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXT:
        return JSONResponse(
            {"error": f"Chỉ chấp nhận ảnh: {', '.join(sorted(_ALLOWED_IMAGE_EXT))}"},
            status_code=400,
        )

    data = await file.read()
    if not data:
        return JSONResponse({"error": "file rỗng"}, status_code=400)
    if len(data) > config.CHAT_IMAGE_MAX_BYTES:
        return JSONResponse(
            {"error": f"Ảnh vượt quá {config.CHAT_IMAGE_MAX_BYTES // (1024 * 1024)}MB"},
            status_code=400,
        )

    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = (config.UPLOADS_DIR / filename).resolve()
    if not str(dest).startswith(str(config.UPLOADS_DIR.resolve())):
        return JSONResponse({"error": "path không hợp lệ"}, status_code=400)
    dest.write_bytes(data)

    msg = (message or "").strip()
    display = msg or f"(đính kèm ảnh `{raw_name}`)"
    # Dùng path tương đối /uploads/... để UI render thumbnail ổn định
    store.add_chat("user", f"{display}\n🖼 /uploads/{filename}")

    async def _run():
        try:
            await orchestrator.analyze_image_and_chat(
                msg, str(dest), project=(project or "").strip() or None
            )
        except Exception as e:
            log.exception("analyze_image_and_chat crashed")
            store.add_chat(
                "conan",
                f"Xin lỗi, xử lý ảnh bị lỗi: {e}. "
                "Kiểm tra Settings → role Vision đã gán model hỗ trợ ảnh chưa.",
            )
        finally:
            # Đã vision xong → không giữ file upload trên disk
            from ..workspace_cleanup import cleanup_upload_file
            cleanup_upload_file(dest)

    asyncio.create_task(_run())
    return {"ok": True, "image_url": f"/uploads/{filename}", "filename": filename}


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
