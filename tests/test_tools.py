"""Test suite: Agent Tools, Execution Utilities, Parsers, Bug Routing, JSON Repair & Link Registry."""
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8")

from orchestrator import llm
from orchestrator.agents.tools import ToolContext
from orchestrator.board import store
from orchestrator.board.models import Task
from orchestrator.links import default_registry, detect_links, steer_hints
from tests.test_helpers import isolate_test_workspace


def test_bug_area_routing():
    """Kiểm tra create_bug_ticket route đúng agent theo area (frontend -> kid, backend -> agasa)."""
    cases = [
        (
            {
                "title": "SQL Injection ở /api/login", "description": "Param username không escape",
                "severity": "critical", "repro_steps": "POST /api/login", "area": "backend",
            },
            "agasa",
        ),
        (
            {
                "title": "IDOR ở /api/orders/:id", "description": "User A xem được order user B",
                "severity": "high", "repro_steps": "GET /api/orders/123",
            },
            "agasa",
        ),
        (
            {
                "title": "Button lệch trên mobile", "description": "CSS layout vỡ ở <375px",
                "severity": "low", "repro_steps": "Mở Header.tsx trên viewport mobile",
            },
            "kid",
        ),
    ]

    with isolate_test_workspace():
        with tempfile.TemporaryDirectory() as tmp:
            parent = store.create_task(
                "parent task cho test routing", description="fake",
                assignee="akai", project="area-routing-test", project_dir=tmp,
            )
            ctx = ToolContext(agent="akai", task=parent)

            for args, expect_assignee in cases:
                out = ctx.execute("create_bug_ticket", args)
                m = re.search(r"bug-\d+", out)
                bug_id = m.group(0) if m else ""
                bug = next((t for t in store.list_tasks(parent_id=parent.id) if t.id == bug_id), None)
                assert bug is not None, f"Bug ticket {bug_id} chưa được tạo"
                assert bug.assignee == expect_assignee, f"Kỳ vọng {expect_assignee} nhưng nhận {bug.assignee}"


def test_figma_tool_error_handling():
    """Kiểm tra tool figma_get xử lý link sai format hoặc file không tồn tại."""
    with isolate_test_workspace():
        with tempfile.TemporaryDirectory() as tmp:
            task = Task(id="tsk-figma-test", title="t", project="figma-test", project_dir=tmp)
            ctx = ToolContext("kid", task)

            # 1. Link không đúng định dạng
            r1 = ctx.execute("figma_get", {"url": "https://example.com/abc"})
            assert r1.startswith("ERROR"), f"Expected ERROR, got: {r1}"

            # 2. Link đúng định dạng nhưng file không tồn tại / unauthorized
            r2 = ctx.execute("figma_get", {"url": "https://www.figma.com/design/AAAABBBBCCCCDDDD1111/fake"})
            assert any(term in r2 for term in ["404", "403", "ERROR", "Unauthorized"]), f"Unexpected response: {r2}"


def test_run_command_cross_platform():
    """Kiểm tra tool run_command phát hiện shell tự động, thực thi lệnh cross-platform an toàn."""
    with isolate_test_workspace():
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            task = Task(
                id="tsk-crossplat-test", title="cross-platform test", assignee="kid",
                project="crossplat-test", project_dir=tmp,
            )
            ctx = ToolContext(agent="kid", task=task)

            # 1. Lệnh cơ bản
            out = ctx.execute("run_command", {"command": "echo hello && echo world"})
            assert not out.startswith("ERROR"), f"Lệnh cơ bản bị lỗi: {out}"
            assert "hello" in out or "world" in out

            # 2. Không lỗi hardcode powershell trên Linux/macOS
            assert "No such file or directory: 'powershell'" not in out

            # 3. Lệnh background pattern
            out2 = ctx.execute("run_command", {"command": "npm run dev"})
            assert not out2.startswith("ERROR"), f"Lệnh background bị lỗi: {out2}"


def test_json_repair_and_extraction():
    """Kiểm tra extract_json phân tích và vá thành công các chuỗi JSON bị cắt giữa chừng."""
    cases = {
        "cut giữa key": '{"action": "plan", "task": {"title": "A"}, "subtasks": [{"title": "x", "agent": "kid"}, {"title":',
        "cut giữa string": '{"action": "plan", "reply": "Da hieu yeu ca',
        "cut sau dau phay": '{"action": "plan", "subtasks": [{"title": "x"},',
        "cut trong nested": '{"action": "plan", "task": {"title": "A", "description": "B"',
        "fence + cut": '```json\n{"action": "reply", "message": "xin cha',
        "json day du": '{"action": "reply", "message": "ok"}',
        "array boc object": '[{"action": "reply", "message": "ok"}]',
    }
    for name, raw in cases.items():
        obj = llm.extract_json(raw)
        assert isinstance(obj, dict) and "action" in obj, f"Failed on case '{name}'"


def test_link_registry_and_hints():
    """Kiểm tra phát hiện link GitHub, GitLab, Figma, Jira và sinh hint phù hợp."""
    sample_links = [
        "https://figma.com/design/abc123XYZ/My-File?node-id=12-34",
        "https://github.com/octocat/Hello-World/tree/master",
        "https://gitlab.com/gitlab-org/gitlab-runner/-/tree/main",
        "https://company.atlassian.net/browse/PROJ-42",
        "xem https://github.com/a/b và https://www.figma.com/design/fff111/Landing",
    ]
    for c in sample_links:
        links = detect_links(c)
        assert len(links) >= 1
    hints = steer_hints(sample_links[-1])
    assert hints is not None


def main():
    test_bug_area_routing()
    test_figma_tool_error_handling()
    test_run_command_cross_platform()
    test_json_repair_and_extraction()
    test_link_registry_and_hints()
    print("PASS test_tools (Bug routing, Figma, run_command, JSON repair & link registry OK)")


if __name__ == "__main__":
    main()
