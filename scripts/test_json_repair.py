"""Kiểm tra extract_json vá được JSON bị cắt giữa chừng."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from orchestrator import llm  # noqa: E402

CASES = {
    "cut giữa key": '{"action": "plan", "task": {"title": "A"}, "subtasks": [{"title": "x", "agent": "stark"}, {"title":',
    "cut giữa string": '{"action": "plan", "reply": "Da hieu yeu ca',
    "cut sau dau phay": '{"action": "plan", "subtasks": [{"title": "x"},',
    "cut trong nested": '{"action": "plan", "task": {"title": "A", "description": "B"',
    "fence + cut": '```json\n{"action": "reply", "message": "xin cha',
    "json day du": '{"action": "reply", "message": "ok"}',
    "array boc object": '[{"action": "reply", "message": "ok"}]',
}

def main():
    fail = 0
    for name, raw in CASES.items():
        try:
            obj = llm.extract_json(raw)
            ok = isinstance(obj, dict) and "action" in obj
            print(f"{'PASS' if ok else 'FAIL'} | {name} -> {type(obj).__name__} {str(obj)[:110]}")
            fail += 0 if ok else 1
        except Exception as e:
            print(f"FAIL | {name} -> {type(e).__name__}: {e}")
            fail += 1

    print("\nall ok" if not fail else f"\n{fail} case fail")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()

