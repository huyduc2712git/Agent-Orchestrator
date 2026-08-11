"""Test suite: Core Orchestrator Engine, Runtime Loop, Bus, Scheduler, Security Gates, Handoff & Image Chat."""
import asyncio
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8")

from orchestrator import bus, config
from orchestrator.agents.runtime import run_agent
from orchestrator.board import store
from orchestrator.core import handoff, scheduler
from orchestrator.core import orchestrator as o
from tests.test_helpers import isolate_test_workspace

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None  # type: ignore[assignment]
    HAS_PIL = False


def _make_test_image(path: str) -> None:
    if HAS_PIL and Image is not None:
        Image.new("RGB", (64, 64), color="red").save(path)
    else:
        Path(path).write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
                "53de0000000c4944415408d763f8ffff3f0005fe02fea7355a1000000049454e44ae426082"
            )
        )


def test_agent_runtime_loop():
    """Kiểm tra runtime loop: agent thực thi chuỗi tool call (write_file, post_message) trong sandbox."""
    async def _run():
        with tempfile.TemporaryDirectory() as tmp:
            task = store.create_task(
                "Tao file hello", "Tao file hello.txt", assignee="kid",
                project_dir=tmp, created_by="conan",
            )
            responses = [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"path": "hello.txt", "content": "Hello from Kid"}',
                            },
                        }
                    ],
                },
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "post_message",
                                "arguments": '{"message": "DONE: Đã tạo xong file hello.txt"}',
                            },
                        }
                    ],
                },
                {
                    "content": "Hoàn tất công việc.",
                    "tool_calls": [],
                },
            ]
            call_idx = 0

            async def fake_chat(*args, **kwargs):
                nonlocal call_idx
                if call_idx < len(responses):
                    resp = responses[call_idx]
                    call_idx += 1
                    return resp
                return {"content": "Hoàn tất.", "tool_calls": []}

            with patch("orchestrator.agents.runtime.llm.chat", side_effect=fake_chat):
                await run_agent(
                    agent_name="kid",
                    system_prompt="Bạn là Kid, builder agent.",
                    user_prompt="Tạo file hello.txt",
                    task=task,
                    tool_names=["read_file", "write_file", "list_dir", "post_message"],
                    max_iterations=10,
                )

            hello = Path(tmp) / "hello.txt"
            assert hello.is_file(), "hello.txt chưa được tạo"
            assert hello.read_text(encoding="utf-8") == "Hello from Kid"
            events = store.list_events(task.id)
            assert len(events) >= 1

    with isolate_test_workspace():
        asyncio.run(_run())


def test_bus_threadsafe_publishing():
    """Kiểm tra bus.publish từ worker thread an toàn tới subscriber trên event loop chính."""
    async def _run():
        bus.set_main_loop(asyncio.get_running_loop())
        q = bus.subscribe()
        try:
            done = threading.Event()

            def worker():
                bus.publish({"type": "probe", "ok": True})
                done.set()

            t = threading.Thread(target=worker)
            t.start()
            t.join(timeout=2)
            assert done.is_set(), "Worker thread không chạy xong"

            for _ in range(50):
                if not q.empty():
                    break
                await asyncio.sleep(0.02)

            assert not q.empty(), "Event không tới queue subscriber"
            ev = q.get_nowait()
            assert ev.get("type") == "probe"
        finally:
            bus.unsubscribe(q)

    asyncio.run(_run())


def test_scheduler_iteration_limit_handling():
    """Kiểm tra scheduler phân biệt chính xác chạm giới hạn lặp thật ([ITERATION_LIMIT_REACHED]) vs text tự nhiên."""
    cases = [
        dict(name="Hoàn tất bình thường", fake_result="Đã sửa xong, build pass.", expect_status="testing"),
        dict(name="Chạm giới hạn vòng lặp thật", fake_result="[ITERATION_LIMIT_REACHED] Đã sửa 1 phần.", expect_status="backlog"),
        dict(name="False-positive cũ", fake_result="Phần CSS xong, nhưng mobile chưa xong.", expect_status="testing"),
    ]

    async def _run():
        scheduler._semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_AGENTS)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("<!DOCTYPE html><html><body><h1>App</h1></body></html>", encoding="utf-8")
            (Path(tmp) / "package.json").write_text('{"name": "test-app", "scripts": {"dev": "vite"}}', encoding="utf-8")

            for i, case in enumerate(cases):
                t = store.create_task(f"test case {i}", description="fake", assignee="kid",
                                       project=f"sched-test-{i}", project_dir=tmp)
                store.set_status(t.id, "in_progress", "kid")
                with patch("orchestrator.core.scheduler.run_agent", return_value=case["fake_result"]):
                    task = store.get_task(t.id)
                    assert task is not None
                    await scheduler._run_worker(task)
                fresh = store.get_task(t.id)
                assert fresh is not None
                actual = fresh.status
                assert actual == case["expect_status"], f"{case['name']}: status={actual} (kỳ vọng {case['expect_status']})"

    with isolate_test_workspace():
        asyncio.run(_run())


def test_gate_critic_stage_flow():
    """Kiểm tra gate bảo mật: Akai (Security Review) -> Amuro (Pentest) -> Proceed hoặc Requeue."""
    with isolate_test_workspace():
        with tempfile.TemporaryDirectory() as tmp:
            parent = store.create_task(
                "parent for gate test", description="fake", assignee="conan",
                project="gate-test", project_dir=tmp,
            )

            # 1. Chưa có subtask akai -> tạo task akai và wait
            r1 = o._gate_security_pentest(parent, [])
            sec_tasks = [t for t in store.list_tasks(parent_id=parent.id) if t.assignee == "akai"]
            assert r1 == "wait" and len(sec_tasks) == 1 and sec_tasks[0].tags == ["security-review"]

            # 2. Akai PASS -> tạo task pentest cho amuro và tiếp tục wait
            sec = sec_tasks[0]
            store.set_status(sec.id, "in_progress", "conan")
            store.set_status(sec.id, "testing", "conan")
            store.add_event(sec.id, "akai", "comment", "## Security Review — PASS\nKhông phát hiện lỗi nghiêm trọng.")
            r2 = o._gate_security_pentest(parent, [])
            pen_tasks = [t for t in store.list_tasks(parent_id=parent.id) if t.assignee == "amuro"]
            assert r2 == "wait" and len(pen_tasks) == 1 and pen_tasks[0].tags == ["penetration-test"]

            # 3. Amuro PASS -> proceed
            pen = pen_tasks[0]
            store.set_status(pen.id, "in_progress", "conan")
            store.set_status(pen.id, "testing", "conan")
            store.add_event(pen.id, "amuro", "comment", "## Penetration Test — PASS\nKhông khai thác được lỗ hổng.")
            r3 = o._gate_security_pentest(parent, [])
            assert r3 == "proceed"

            # 4. Akai FAIL -> requeue với tag resec-1
            parent2 = store.create_task(
                "parent for gate fail test", description="fake", assignee="conan",
                project="gate-test-2", project_dir=tmp,
            )
            o._gate_security_pentest(parent2, [])
            sec2 = [t for t in store.list_tasks(parent_id=parent2.id) if t.assignee == "akai"][0]
            store.set_status(sec2.id, "in_progress", "conan")
            store.set_status(sec2.id, "testing", "conan")
            store.add_event(sec2.id, "akai", "comment", "## Security Review — FAIL\nKhông có bug ticket kèm theo.")
            r4 = o._gate_security_pentest(parent2, [])
            sec2_after = store.get_task(sec2.id)
            assert sec2_after is not None
            assert r4 == "wait" and "resec-1" in (sec2_after.tags or [])


def test_handoff_snapshot_generation():
    """Kiểm tra sinh snapshot workspace/handoff.md phản ánh đúng trạng thái task."""
    with isolate_test_workspace():
        with tempfile.TemporaryDirectory() as tmp:
            marker = "handoff-snapshot-test-marker"
            t_running = store.create_task(f"{marker} đang chạy", description="fake", assignee="kid",
                                           project="handoff-test", project_dir=tmp)
            store.set_status(t_running.id, "in_progress", "kid")

            t_blocked = store.create_task(f"{marker} bị block", description="fake", assignee="agasa",
                                           project="handoff-test", project_dir=tmp)
            store.set_status(t_blocked.id, "blocked", "conan")

            path = handoff.write_handoff_snapshot()
            content = path.read_text(encoding="utf-8")

            assert path.name == "handoff.md" and path.is_file()
            assert t_running.id in content and "Đang chạy" in content
            assert t_blocked.id in content and "block" in content.lower()
            assert "KHÔNG phải nguồn sự thật" in content


def test_image_chat_attachment_flow():
    """Kiểm tra plumbing đính kèm ảnh trong chat (analyze_image_and_chat) với các kịch bản lỗi & payload."""
    fake_vision_config = {
        "model": "fake-vision-model",
        "base_url": "https://example.com/v1",
        "api_key": "fake-key",
        "name": "Fake Vision",
    }

    async def _run():
        # Case 1: Không cấu hình vision
        old_vision = config.MODEL_VISION
        config.MODEL_VISION = ""
        try:
            with tempfile.TemporaryDirectory() as tmp:
                img_path = str(Path(tmp) / "img.png")
                _make_test_image(img_path)
                with patch("orchestrator.settings.resolve_llm", return_value={}), \
                     patch("orchestrator.settings.role_models", return_value={}), \
                     patch("orchestrator.core.orchestrator.llm.chat", new_callable=AsyncMock) as mock_llm:
                    await o.analyze_image_and_chat("test", img_path, project=None)
                    assert not mock_llm.called
                chats = store.list_chat(limit=1)
                assert "Chưa cấu hình model đọc ảnh" in (chats[0]["message"] if chats else "")
        finally:
            config.MODEL_VISION = old_vision

        # Case 2: File không tồn tại
        with patch("orchestrator.settings.resolve_llm", return_value=fake_vision_config):
            await o.analyze_image_and_chat("test", "/khong/ton/tai/anh.png", project=None)
            chats = store.list_chat(limit=1)
            assert "Không tìm thấy file ảnh" in (chats[0]["message"] if chats else "")

        # Case 3: Happy path payload
        with tempfile.TemporaryDirectory() as tmp:
            img_path = str(Path(tmp) / "mockup.png")
            _make_test_image(img_path)
            fake_response = {"content": "Mô tả ảnh: nút đỏ 64x64px."}
            fake_handle_chat = AsyncMock()

            with patch("orchestrator.settings.resolve_llm", return_value=fake_vision_config), \
                 patch("orchestrator.core.orchestrator.llm.chat", new_callable=AsyncMock, return_value=fake_response) as mock_llm, \
                 patch("orchestrator.core.orchestrator.handle_chat", fake_handle_chat):
                await o.analyze_image_and_chat("làm giống ảnh này", img_path, project="p1")

            assert mock_llm.called
            sent_messages = mock_llm.call_args[0][0]
            content_blocks = sent_messages[0]["content"]
            assert any(c.get("type") == "text" for c in content_blocks)
            assert any(c.get("type") == "image_url" for c in content_blocks)
            assert fake_handle_chat.called

    with isolate_test_workspace():
        asyncio.run(_run())


def main():
    test_agent_runtime_loop()
    test_bus_threadsafe_publishing()
    test_scheduler_iteration_limit_handling()
    test_gate_critic_stage_flow()
    test_handoff_snapshot_generation()
    test_image_chat_attachment_flow()
    print("PASS test_core (Runtime, bus, scheduler, gate critic, handoff & image chat OK)")


if __name__ == "__main__":
    main()
