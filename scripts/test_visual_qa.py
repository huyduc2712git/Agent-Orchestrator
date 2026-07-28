"""Smoke test Visual QA tools."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.qa import browser as qa

URL = "http://127.0.0.1:8600/preview/ca-phe-sang-landing/"
OUT = Path(__file__).resolve().parent.parent / "workspace" / "artifacts" / "test-qa" / "desktop-top.png"

print("1. screenshot...")
r = qa.capture_screenshot(URL, OUT, viewport_name="desktop", full_page=False)
print("   OK", r.get("title"), OUT.exists())

print("2. inspect_render...")
r2 = qa.inspect_render(URL, viewport_name="desktop")
print("   overall:", r2.get("overall"), "checks:", len(r2.get("checks", [])))
print(qa.format_inspect_table(r2)[:300])
