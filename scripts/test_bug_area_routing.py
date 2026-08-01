"""
Test: create_bug_ticket phải route đúng agent theo area (frontend->kid, backend->agasa),
kể cả khi agent không chỉ định area tường minh (auto-guess theo từ khóa trong repro_steps).

Bug cũ: mọi bug (kể cả lỗi backend như SQL Injection do Akai/Amuro phát hiện) đều bị gán
cứng cho "kid" — mâu thuẫn với chính "Never" của Kid (không được sửa business logic backend).

Cách chạy:
    python scripts/test_bug_area_routing.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.board import store  # noqa: E402
from orchestrator.agents.tools import ToolContext  # noqa: E402

import re

CASES = [
    dict(
        name="area=backend tường minh (SQL Injection)",
        args=dict(
            title="SQL Injection ở /api/login", description="Param username không escape",
            severity="critical", repro_steps="POST /api/login username=' OR 1=1--",
            area="backend",
        ),
        expect_assignee="agasa",
    ),
    dict(
        name="không chỉ định area, auto-guess từ từ khóa backend (IDOR)",
        args=dict(
            title="IDOR ở /api/orders/:id", description="User A xem được order user B",
            severity="high", repro_steps="GET /api/orders/123 với token khác vẫn 200",
        ),
        expect_assignee="agasa",
    ),
    dict(
        name="không chỉ định area, auto-guess từ từ khóa frontend (CSS lệch)",
        args=dict(
            title="Button lệch trên mobile", description="CSS layout vỡ ở <375px",
            severity="low", repro_steps="Mở Header.tsx trên viewport mobile",
        ),
        expect_assignee="kid",
    ),
]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        parent = store.create_task(
            "parent task cho test routing", description="fake",
            assignee="akai", project="area-routing-test", project_dir=tmp,
        )
        ctx = ToolContext(agent="akai", task=parent)

        for case in CASES:
            out = ctx.execute("create_bug_ticket", case["args"])
            m = re.search(r"bug-\d+", out)
            bug_id = m.group(0) if m else ""
            bug = next((t for t in store.list_tasks(parent_id=parent.id) if t.id == bug_id), None)
            ok = bug is not None and bug.assignee == case["expect_assignee"]
            print(f'  {"OK  " if ok else "FAIL"}  {case["name"]}: assignee={bug.assignee if bug else "?"} '
                  f'(kỳ vọng {case["expect_assignee"]})')
            if not ok:
                failed = True

    print()
    if failed:
        print("KẾT QUẢ: FAIL")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — bug được route đúng agent theo area.")
    sys.exit(0)


if __name__ == "__main__":
    main()
