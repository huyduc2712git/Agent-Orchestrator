"""Test tool figma_get: parse link + gọi API bằng token trong settings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from orchestrator import config
from orchestrator.agents.tools import ToolContext
from orchestrator.board.models import Task

task = Task(id="tsk-test", title="t", project="figma-test",
            project_dir=str(config.WORKSPACE_DIR / "projects" / "figma-test"))
ctx = ToolContext("kid", task)

# 1. Link không đúng định dạng
r1 = ctx.execute("figma_get", {"url": "https://example.com/abc"})
print("bad link ->", r1[:80])
assert r1.startswith("ERROR"), r1

# 2. Link đúng định dạng nhưng file không tồn tại -> token được dùng, Figma trả 404
r2 = ctx.execute("figma_get", {"url": "https://www.figma.com/design/AAAABBBBCCCCDDDD1111/fake"})
print("fake key ->", r2[:120])
assert "404" in r2 or "403" in r2, r2

print("FIGMA TOOL TESTS PASSED (parse + auth pipeline OK)")
