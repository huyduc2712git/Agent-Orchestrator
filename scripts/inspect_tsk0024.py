import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchestrator.board import store

parent = store.get_task("tsk-0024")
print("=== PARENT ===")
if parent:
    print(parent.id, parent.status, parent.project, parent.title)
    print("tags:", parent.tags)
    print("desc[:400]:", (parent.description or "")[:400])
else:
    print("NOT FOUND tsk-0024 — searching...")
    for t in store.list_tasks(include_archived=True):
        if "0024" in t.id or "mp3" in t.title.lower() or "voxbeat" in (t.project or ""):
            print(t.id, t.status, t.parent_id, t.assignee, t.title[:70])

# all related
print("\n=== SUBTASKS / RELATED ===")
for t in store.list_tasks(include_archived=True):
    if (parent and (t.parent_id == parent.id or t.id == parent.id or t.project == parent.project)) or (
        not parent and ("voxbeat" in (t.project or "") or "mp3" in t.title.lower())
    ):
        if parent and t.project != parent.project and t.id != parent.id and t.parent_id != parent.id:
            continue
        print(f"{t.id:10} {t.status:12} parent={t.parent_id or '-':10} {t.assignee or '-':10} {t.title[:60]}")

if parent:
    print("\n=== EVENTS parent ===")
    for e in store.list_events(parent.id)[-15:]:
        msg = (e.message or "").replace("\n", " ")[:180]
        print(f"  [{e.agent}/{e.kind}] {msg}")
    subs = [t for t in store.list_tasks(include_archived=True) if t.parent_id == parent.id]
    for s in subs:
        print(f"\n=== EVENTS {s.id} ({s.assignee}, {s.status}) ===")
        for e in store.list_events(s.id)[-8:]:
            msg = (e.message or "").replace("\n", " ")[:200]
            print(f"  [{e.agent}/{e.kind}] {msg}")
    bugs = [t for t in store.list_tasks(include_archived=True, type="bug") if t.project == parent.project]
    print("\n=== BUGS ===")
    for b in bugs:
        print(f"{b.id} {b.status} {b.assignee} sev={b.severity} | {b.title[:70]}")
        for e in store.list_events(b.id)[-4:]:
            print(f"    [{e.agent}/{e.kind}] {(e.message or '')[:150].replace(chr(10),' ')}")
