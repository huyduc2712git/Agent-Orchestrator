"""
Test: handoff snapshot (workspace/handoff.md) phải phản ánh đúng trạng thái board
hiện tại — đang chạy, chờ review, bị block, backlog — đọc được ngoài DB.

Cách chạy:
    python scripts/test_handoff_snapshot.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.board import store  # noqa: E402
from orchestrator.core import handoff  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    failed = False
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

        ok1 = path.name == "handoff.md" and path.is_file()
        print(f'  {"OK  " if ok1 else "FAIL"}  File sinh đúng vị trí workspace/handoff.md')
        failed = failed or not ok1

        ok2 = t_running.id in content and "Đang chạy" in content
        print(f'  {"OK  " if ok2 else "FAIL"}  Snapshot liệt kê đúng task đang chạy')
        failed = failed or not ok2

        ok3 = t_blocked.id in content and "block" in content.lower()
        print(f'  {"OK  " if ok3 else "FAIL"}  Snapshot liệt kê đúng task bị block')
        failed = failed or not ok3

        ok4 = "KHÔNG phải nguồn sự thật" in content
        print(f'  {"OK  " if ok4 else "FAIL"}  Snapshot có ghi rõ đây chỉ là derived state, không phải source of truth')
        failed = failed or not ok4

    print()
    if failed:
        print("KẾT QUẢ: FAIL")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — handoff snapshot phản ánh đúng trạng thái board.")
    sys.exit(0)


if __name__ == "__main__":
    main()
