"""
Test: luồng "đính kèm ảnh trong chat" (analyze_image_and_chat) — vì sandbox không có
API key thật cho model vision, các test này mock orchestrator.llm.chat() để verify
đúng PLUMBING (điều kiện chặn, format payload gửi đi, cách ghép text) chứ KHÔNG verify
được độ chính xác nhận diện ảnh thật — phần đó cần bạn tự test với model vision thật.

Cách chạy:
    python scripts/test_image_chat_flow.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import config  # noqa: E402
from orchestrator.board import store  # noqa: E402
from orchestrator.core import orchestrator as o  # noqa: E402

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _make_test_image(path: str) -> None:
    if HAS_PIL:
        Image.new("RGB", (64, 64), color="red").save(path)
    else:
        # Fallback: PNG 1x1 tối thiểu hợp lệ nếu không có Pillow
        Path(path).write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
                "53de0000000c4944415408d763f8ffff3f0005fe02fea7355a1000000049454e44ae426082"
            )
        )


async def case_no_vision_configured() -> bool:
    """Chưa cấu hình role vision -> phải báo lỗi rõ, KHÔNG gọi LLM."""
    old_vision = config.MODEL_VISION
    config.MODEL_VISION = ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            img_path = str(Path(tmp) / "img.png")
            _make_test_image(img_path)
            with patch("orchestrator.llm.chat", new_callable=AsyncMock) as mock_llm:
                await o.analyze_image_and_chat("test", img_path, project=None)
                not_called = not mock_llm.called
            last_msg = store.list_chat(limit=1)[0]["message"]
            has_warning = "Chưa cấu hình model đọc ảnh" in last_msg
            ok = not_called and has_warning
            print(f'  {"OK  " if ok else "FAIL"}  Chưa cấu hình vision -> báo lỗi rõ, không gọi LLM')
            return ok
    finally:
        config.MODEL_VISION = old_vision


async def case_file_not_found() -> bool:
    """Đường dẫn ảnh không tồn tại -> báo lỗi rõ, không crash."""
    old_vision = config.MODEL_VISION
    config.MODEL_VISION = "fake-vision-model"
    try:
        await o.analyze_image_and_chat("test", "/khong/ton/tai/anh.png", project=None)
        last_msg = store.list_chat(limit=1)[0]["message"]
        ok = "Không tìm thấy file ảnh" in last_msg
        print(f'  {"OK  " if ok else "FAIL"}  File ảnh không tồn tại -> báo lỗi rõ, không crash')
        return ok
    finally:
        config.MODEL_VISION = old_vision


async def case_happy_path_payload_format() -> bool:
    """Mock LLM trả mô tả -> verify payload multi-modal đúng format + text được ghép đúng."""
    old_vision = config.MODEL_VISION
    config.MODEL_VISION = "fake-vision-model"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            img_path = str(Path(tmp) / "mockup.png")
            _make_test_image(img_path)

            fake_response = {"content": "Mô tả ảnh giả lập: nút đỏ 64x64px."}
            fake_handle_chat = AsyncMock()

            with patch("orchestrator.llm.chat", new_callable=AsyncMock, return_value=fake_response) as mock_llm, \
                 patch("orchestrator.core.orchestrator.handle_chat", fake_handle_chat):
                await o.analyze_image_and_chat("làm giống ảnh này", img_path, project="p1")

            sent_messages = mock_llm.call_args[0][0]
            content_blocks = sent_messages[0]["content"]
            has_text_block = any(c.get("type") == "text" for c in content_blocks)
            has_image_block = any(
                c.get("type") == "image_url" and c.get("image_url", {}).get("url", "").startswith("data:image/")
                for c in content_blocks
            )

            enriched = fake_handle_chat.call_args[0][0]
            has_original_msg = "làm giống ảnh này" in enriched
            has_description = "Mô tả ảnh giả lập" in enriched

            ok = has_text_block and has_image_block and has_original_msg and has_description
            print(f'  {"OK  " if ok else "FAIL"}  Payload gửi vision model đúng format (text+image_url base64), '
                  f'text ghép đúng cho handle_chat()')
            return ok
    finally:
        config.MODEL_VISION = old_vision


async def case_llm_error_handled() -> bool:
    """Model vision lỗi (LLMError) -> báo lỗi rõ, không crash, không tạo task rác."""
    from orchestrator import llm as llm_module
    old_vision = config.MODEL_VISION
    config.MODEL_VISION = "fake-vision-model"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            img_path = str(Path(tmp) / "img.png")
            _make_test_image(img_path)
            with patch("orchestrator.llm.chat", new_callable=AsyncMock,
                       side_effect=llm_module.LLMError("model không hỗ trợ vision")):
                await o.analyze_image_and_chat("test", img_path, project=None)
            last_msg = store.list_chat(limit=1)[0]["message"]
            ok = "Gọi model đọc ảnh thất bại" in last_msg
            print(f'  {"OK  " if ok else "FAIL"}  Model vision lỗi -> báo lỗi rõ ràng, không crash')
            return ok
    finally:
        config.MODEL_VISION = old_vision


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    results = [
        await case_no_vision_configured(),
        await case_file_not_found(),
        await case_happy_path_payload_format(),
        await case_llm_error_handled(),
    ]

    print()
    print("⚠️  LƯU Ý: các test trên chỉ verify PLUMBING (điều kiện chặn, format payload, "
          "ghép text) bằng cách mock LLM — KHÔNG verify được độ chính xác nhận diện ảnh "
          "thật vì sandbox không có API key model vision thật.")
    print()
    if not all(results):
        print("KẾT QUẢ: FAIL")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — plumbing tính năng đính kèm ảnh hoạt động đúng.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
