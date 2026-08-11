"""Test suite: Quản lý Board Store, Task Lifecycle, State Machine Guards & Review Cards."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8")

from orchestrator import config
from orchestrator.board import store
from orchestrator.board.review_card import write_review_card
from tests.test_helpers import isolate_test_workspace


def test_board_state_machine_and_guards():
    """Kiểm tra state machine, phân quyền duyệt và các guard bảo vệ trạng thái task."""
    with isolate_test_workspace():
        t = store.create_task("Build header", "desc", assignee="kid", created_by="conan")
        qa = store.create_task("QA header", "verify", assignee="heiji", created_by="conan")
        store.add_dep(qa.id, t.id, "blocks")

        assert not store.deps_satisfied(qa.id), "QA phải bị block khi build chưa xong"

        r = store.set_status(t.id, "in_progress", "kid")
        assert r.accepted and r.final_status == "in_progress"

        r = store.set_status(t.id, "testing", "kid")
        assert r.accepted
        assert store.deps_satisfied(qa.id), "QA phải được mở khóa khi build sang testing"

        # Guard: agent set review trên task agent-only -> normalize về testing
        r = store.set_status(t.id, "review", "heiji")
        assert not r.accepted and r.final_status == "testing", r

        # Guard: agent không được tự đóng task (self-done)
        r = store.set_status(t.id, "done", "kid")
        assert not r.accepted, r

        # Conan đóng task của kid -> OK
        r = store.set_status(t.id, "done", "conan")
        assert r.accepted and r.final_status == "done", r

        # Task operator-review: tag deploy-prod
        sec = store.create_task("Deploy prod", "x", assignee="kid", tags=["deploy-prod"], created_by="conan")
        assert sec.review_type == "operator", sec.review_type
        store.set_status(sec.id, "in_progress", "kid")
        store.set_status(sec.id, "testing", "kid")
        r = store.set_status(sec.id, "review", "kid")
        assert r.accepted and r.final_status == "review", r
        r = store.set_status(sec.id, "done", "conan")
        assert not r.accepted, "conan không được duyệt operator-review"
        r = store.set_status(sec.id, "done", "operator")
        assert r.accepted, r

        # Bug ID prefix
        b = store.create_task("Fix typo", type="bug", severity="low", created_by="heiji")
        assert b.id.startswith("bug-"), b.id

        assert len(store.search_tasks("header")) == 2
        assert len(store.list_events(t.id)) >= 4


def test_human_review_card():
    """Kiểm tra sinh Human Review Card tại workspace/wiki/reviews/<task_id>.review.md."""
    with isolate_test_workspace():
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
            assert path == expected_location and path.is_file()
            assert "VERDICT" in content or "`PASS`" in content
            assert "Header.tsx" in content and "theme.css" in content
            assert bug.id in content
            assert "## Rollback" in content


def main():
    test_board_state_machine_and_guards()
    test_human_review_card()
    print("PASS test_board (State machine, guards & review cards OK)")


if __name__ == "__main__":
    main()
