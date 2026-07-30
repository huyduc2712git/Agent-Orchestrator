"""Test board store + state machine guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import config
from orchestrator.board import store

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def main():
    # dùng DB tạm để không đụng dữ liệu thật
    config.DB_PATH = config.WORKSPACE_DIR / "test_board.db"
    config.DB_PATH.unlink(missing_ok=True)

    t = store.create_task("Build header", "desc", assignee="kid", created_by="conan")
    qa = store.create_task("QA header", "verify", assignee="heiji", created_by="conan")
    store.add_dep(qa.id, t.id, "blocks")

    assert not store.deps_satisfied(qa.id), "QA phai bi block khi build chua xong"

    r = store.set_status(t.id, "in_progress", "kid")
    assert r.accepted and r.final_status == "in_progress"

    r = store.set_status(t.id, "testing", "kid")
    assert r.accepted
    assert store.deps_satisfied(qa.id), "QA phai duoc mo khoa khi build sang testing"

    # Guard: agent set review tren task agent-only -> normalize ve testing
    r = store.set_status(t.id, "review", "heiji")
    assert not r.accepted and r.final_status == "testing", r
    print("Guard review->testing OK:", r.note[:60])

    # Guard: agent khong duoc tu dong task
    r = store.set_status(t.id, "done", "kid")
    assert not r.accepted, r
    print("Guard self-done OK:", r.note[:60])

    # Conan dong task cua kid -> OK
    r = store.set_status(t.id, "done", "conan")
    assert r.accepted and r.final_status == "done", r

    # Task operator-review: tag security
    sec = store.create_task("Deploy prod", "x", assignee="kid", tags=["deploy-prod"], created_by="conan")
    assert sec.review_type == "operator", sec.review_type
    store.set_status(sec.id, "in_progress", "kid")
    store.set_status(sec.id, "testing", "kid")
    r = store.set_status(sec.id, "review", "kid")
    assert r.accepted and r.final_status == "review", r
    r = store.set_status(sec.id, "done", "conan")
    assert not r.accepted, "conan khong duoc duyet operator-review"
    r = store.set_status(sec.id, "done", "operator")
    assert r.accepted, r

    # Bug id prefix
    b = store.create_task("Fix typo", type="bug", severity="low", created_by="heiji")
    assert b.id.startswith("bug-"), b.id

    assert len(store.search_tasks("header")) == 2
    assert len(store.list_events(t.id)) >= 4

    print("ALL BOARD TESTS PASSED")
    if store._conn is not None:
        store._conn.close()
        store._conn = None
    config.DB_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

