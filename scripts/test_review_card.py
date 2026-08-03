"""
Test: Human Review Card (lấy cảm hứng từ repo-harness tasks/reviews/*.review.md)
phải sinh đúng file .md tại workspace/wiki/reviews/<task_id>.review.md, chứa đủ:
verdict, file thay đổi, lệnh đã chạy, bug còn mở, rollback.

Cách chạy:
    python scripts/test_review_card.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import config  # noqa: E402
from orchestrator.board import store  # noqa: E402
from orchestrator.board.review_card import write_review_card  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        t = store.create_task(
            "Thêm nút Dark Mode", description="Yêu cầu thêm dark mode toggle",
            assignee="conan", project="review-card-test", project_dir=tmp,
            review_type="operator",
        )
        store.add_event(t.id, "kid", "comment",
                         "Đã sửa src/components/Header.tsx và src/styles/theme.css.")
        store.add_event(t.id, "kid", "comment", "npm run build thành công.")
        store.add_event(t.id, "heiji", "comment", "## Visual QA Report\nVERDICT: PASS")
        bug = store.create_task(
            "Bug lặt vặt", description="fake", type="bug", assignee="kid",
            project="review-card-test", project_dir=tmp, parent_id=t.id, severity="low",
        )

        path = write_review_card(t)
        content = path.read_text(encoding="utf-8")

        expected_location = config.WIKI_DIR / "reviews" / f"{t.id}.review.md"
        ok1 = path == expected_location and path.is_file()
        print(f'  {"OK  " if ok1 else "FAIL"}  File sinh đúng vị trí workspace/wiki/reviews/<task_id>.review.md')
        failed = failed or not ok1

        ok2 = "VERDICT" in content or "`PASS`" in content
        print(f'  {"OK  " if ok2 else "FAIL"}  Card chứa verdict trích từ event log')
        failed = failed or not ok2

        ok3 = "Header.tsx" in content and "theme.css" in content
        print(f'  {"OK  " if ok3 else "FAIL"}  Card trích đúng tên file đã thay đổi')
        failed = failed or not ok3

        ok4 = bug.id in content
        print(f'  {"OK  " if ok4 else "FAIL"}  Card liệt kê đúng bug còn mở')
        failed = failed or not ok4

        ok5 = "## Rollback" in content
        print(f'  {"OK  " if ok5 else "FAIL"}  Card có section Rollback')
        failed = failed or not ok5

    print()
    if failed:
        print("KẾT QUẢ: FAIL")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — Human Review Card sinh đúng nội dung.")
    sys.exit(0)


if __name__ == "__main__":
    main()
