"""Test board store + state machine guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import config
from orchestrator.board import store

# dùng DB tạm để không đụng dữ liệu thật
config.DB_PATH = config.WORKSPACE_DIR / "test_board.db"
config.DB_PATH.unlink(missing_ok=True)

t = store.create_task("Build header", "desc", assignee="stark", created_by="jarvis")
qa = store.create_task("QA header", "verify", assignee="hawkeye", created_by="jarvis")
store.add_dep(qa.id, t.id, "blocks")

assert not store.deps_satisfied(qa.id), "QA phai bi block khi build chua xong"

r = store.set_status(t.id, "in_progress", "stark")
assert r.accepted and r.final_status == "in_progress"

r = store.set_status(t.id, "testing", "stark")
assert r.accepted
assert store.deps_satisfied(qa.id), "QA phai duoc mo khoa khi build sang testing"

# Guard: agent set review tren task agent-only -> normalize ve testing
r = store.set_status(t.id, "review", "hawkeye")
assert not r.accepted and r.final_status == "testing", r
print("Guard review->testing OK:", r.note[:60])

# Guard: agent khong duoc tu dong task
r = store.set_status(t.id, "done", "stark")
assert not r.accepted, r
print("Guard self-done OK:", r.note[:60])

# Jarvis dong task cua stark -> OK
r = store.set_status(t.id, "done", "jarvis")
assert r.accepted and r.final_status == "done", r

# Task operator-review: tag security
sec = store.create_task("Deploy prod", "x", assignee="stark", tags=["deploy-prod"], created_by="jarvis")
assert sec.review_type == "operator", sec.review_type
store.set_status(sec.id, "in_progress", "stark")
store.set_status(sec.id, "testing", "stark")
r = store.set_status(sec.id, "review", "stark")
assert r.accepted and r.final_status == "review", r
r = store.set_status(sec.id, "done", "jarvis")
assert not r.accepted, "jarvis khong duoc duyet operator-review"
r = store.set_status(sec.id, "done", "operator")
assert r.accepted, r

# Bug id prefix
b = store.create_task("Fix typo", type="bug", severity="low", created_by="hawkeye")
assert b.id.startswith("bug-"), b.id

assert len(store.search_tasks("header")) == 2
assert len(store.list_events(t.id)) >= 4

print("ALL BOARD TESTS PASSED")
if store._conn is not None:
    store._conn.close()
    store._conn = None
config.DB_PATH.unlink(missing_ok=True)
