"""
Test: _gate_security_pentest (đã refactor gộp logic Akai/Amuro thành _gate_critic_stage
dùng chung) phải giữ đúng hành vi qua toàn bộ luồng trạng thái — không phải chỉ test
import được, mà test thật từng bước chuyển trạng thái.

Cách chạy:
    python scripts/test_gate_critic_stage.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.board import store  # noqa: E402
from orchestrator.core import orchestrator as o  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    failed = False

    with tempfile.TemporaryDirectory() as tmp:
        parent = store.create_task(
            "parent for gate test", description="fake", assignee="conan",
            project="gate-test", project_dir=tmp,
        )

        # Bước 1: chưa có subtask akai -> phải tự tạo Security Review task, trả "wait"
        r1 = o._gate_security_pentest(parent, [])
        sec_tasks = [t for t in store.list_tasks(parent_id=parent.id) if t.assignee == "akai"]
        ok1 = r1 == "wait" and len(sec_tasks) == 1 and sec_tasks[0].tags == ["security-review"]
        print(f'  {"OK  " if ok1 else "FAIL"}  Bước 1: tự tạo Security Review task (akai), trả "wait"')
        failed = failed or not ok1

        # Bước 2: Akai post PASS -> phải tạo Pentest task cho amuro, vẫn "wait"
        sec = sec_tasks[0]
        store.set_status(sec.id, "in_progress", "conan")
        store.set_status(sec.id, "testing", "conan")
        store.add_event(sec.id, "akai", "comment", "## Security Review — PASS\nKhông phát hiện lỗi nghiêm trọng.")
        r2 = o._gate_security_pentest(parent, [])
        pen_tasks = [t for t in store.list_tasks(parent_id=parent.id) if t.assignee == "amuro"]
        ok2 = r2 == "wait" and len(pen_tasks) == 1 and pen_tasks[0].tags == ["penetration-test"]
        print(f'  {"OK  " if ok2 else "FAIL"}  Bước 2: Akai PASS -> tự tạo Pentest task (amuro), trả "wait"')
        failed = failed or not ok2

        # Bước 3: Amuro cũng post PASS -> "proceed" (đến Final Review)
        pen = pen_tasks[0]
        store.set_status(pen.id, "in_progress", "conan")
        store.set_status(pen.id, "testing", "conan")
        store.add_event(pen.id, "amuro", "comment", "## Penetration Test — PASS\nKhông khai thác được lỗ hổng nào.")
        r3 = o._gate_security_pentest(parent, [])
        ok3 = r3 == "proceed"
        print(f'  {"OK  " if ok3 else "FAIL"}  Bước 3: cả Akai + Amuro PASS -> "proceed"')
        failed = failed or not ok3

        # Bước 4 (case FAIL riêng, project khác): Akai FAIL -> requeue với tag resec-1
        parent2 = store.create_task(
            "parent for gate fail test", description="fake", assignee="conan",
            project="gate-test-2", project_dir=tmp,
        )
        o._gate_security_pentest(parent2, [])
        sec2 = [t for t in store.list_tasks(parent_id=parent2.id) if t.assignee == "akai"][0]
        store.set_status(sec2.id, "in_progress", "conan")
        store.set_status(sec2.id, "testing", "conan")
        store.add_event(sec2.id, "akai", "comment", "## Security Review — FAIL\nKhông có bug ticket kèm theo (giả lập lỗi).")
        r4 = o._gate_security_pentest(parent2, [])
        sec2_after = store.get_task(sec2.id)
        ok4 = r4 == "wait" and "resec-1" in (sec2_after.tags or [])
        print(f'  {"OK  " if ok4 else "FAIL"}  Bước 4: Akai FAIL không kèm bug -> gắn tag resec-1, requeue')
        failed = failed or not ok4

    print()
    if failed:
        print("KẾT QUẢ: FAIL — refactor _gate_critic_stage làm sai lệch hành vi.")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — _gate_critic_stage giữ đúng hành vi qua toàn bộ luồng trạng thái.")
    sys.exit(0)


if __name__ == "__main__":
    main()
