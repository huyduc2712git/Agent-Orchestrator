"""
Test: scheduler._run_worker phải phân biệt "agent thật sự chạm giới hạn vòng lặp"
bằng marker cố định [ITERATION_LIMIT_REACHED] do run_agent() tự gắn, KHÔNG dò theo
cụm từ tự do ("chưa xong", "chưa hoàn tất"...) trong text LLM trả về — vì agent có
thể tự nhiên dùng các cụm từ đó khi mô tả tiến độ mà không hề chạm giới hạn thật.

Cách chạy:
    python scripts/test_scheduler_iteration_limit_marker.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import config  # noqa: E402
from orchestrator.board import store  # noqa: E402
from orchestrator.core import scheduler  # noqa: E402

scheduler._semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_AGENTS)

CASES = [
    dict(
        name="Hoàn tất bình thường",
        fake_result="Đã sửa xong, build pass.",
        expect_status="testing",
    ),
    dict(
        name="Chạm giới hạn vòng lặp THẬT (có marker do code gắn)",
        fake_result="[ITERATION_LIMIT_REACHED] Đã sửa 1 phần, còn phần API chưa test.",
        expect_status="backlog",
    ),
    dict(
        name="False-positive cũ: nhắc 'chưa xong' tự nhiên nhưng KHÔNG chạm giới hạn thật",
        fake_result="Phần CSS đã xong, nhưng phần responsive mobile thì chưa xong, cần thêm task riêng.",
        expect_status="testing",
    ),
]


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        for i, case in enumerate(CASES):
            t = store.create_task(f"test case {i}", description="fake", assignee="kid",
                                   project=f"sched-test-{i}", project_dir=tmp)
            store.set_status(t.id, "in_progress", "kid")
            with patch("orchestrator.core.scheduler.run_agent", return_value=case["fake_result"]):
                await scheduler._run_worker(store.get_task(t.id))
            actual = store.get_task(t.id).status
            ok = actual == case["expect_status"]
            print(f'  {"OK  " if ok else "FAIL"}  {case["name"]}: status={actual} (kỳ vọng {case["expect_status"]})')
            failed = failed or not ok

    print()
    if failed:
        print("KẾT QUẢ: FAIL")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — scheduler phân biệt đúng chạm giới hạn thật vs text tự nhiên.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
