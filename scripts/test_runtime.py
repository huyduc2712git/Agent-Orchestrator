"""Test agent runtime: agent thật ghi file thật qua tool calling."""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import config
from orchestrator.agents.runtime import run_agent
from orchestrator.board import store

config.DB_PATH = config.WORKSPACE_DIR / "test_rt.db"
config.DB_PATH.unlink(missing_ok=True)

sandbox = config.WORKSPACE_DIR / "test_sandbox"
shutil.rmtree(sandbox, ignore_errors=True)


async def main():
    task = store.create_task(
        "Tao file hello",
        "Tao file hello.txt",
        assignee="stark",
        project_dir=str(sandbox),
        created_by="jarvis",
    )
    result = await run_agent(
        agent_name="stark",
        system_prompt=(
            "Bạn là Stark, builder agent. Bạn có tool thao tác file thật. "
            "Làm xong việc thì post_message deliverable rồi trả lời tổng kết ngắn."
        ),
        user_prompt=(
            "Tạo file hello.txt với nội dung chính xác là 'Hello from Stark' "
            "và file info.txt chứa danh sách file trong thư mục sau khi tạo."
        ),
        task=task,
        tool_names=["read_file", "write_file", "list_dir", "post_message"],
        max_iterations=10,
    )
    print("FINAL:", result[:300])
    hello = sandbox / "hello.txt"
    assert hello.is_file(), "hello.txt chua duoc tao!"
    print("hello.txt content:", hello.read_text(encoding="utf-8"))
    events = store.list_events(task.id)
    print(f"events: {len(events)}")
    for e in events:
        print(" -", e.agent, e.kind, e.message[:80])
    print("RUNTIME TEST PASSED")


asyncio.run(main())

if store._conn is not None:
    store._conn.close()
    store._conn = None
config.DB_PATH.unlink(missing_ok=True)
shutil.rmtree(sandbox, ignore_errors=True)
