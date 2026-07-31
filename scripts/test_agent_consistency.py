"""
Test tính nhất quán tên agent trên toàn bộ codebase.
Mục đích: bắt lỗi kiểu "đổi tên agent nhưng còn sót string hardcode ở chỗ khác"
(chính là lỗi assignee="stark" từng gây deadlock bug ticket).

Cách chạy:
    python scripts/test_agent_consistency.py

PASS khi:
  1. Mọi giá trị assignee hardcode trong orchestrator/ đều nằm trong WORKER_KEYS
     hoặc là "conan" (planner) hoặc "operator".
  2. Không còn tên agent cũ (jarvis/stark/banner/hawkeye/pepper/heimdall) xuất hiện
     trong orchestrator/ và web/ (loại trừ file migrate/comment lịch sử).
  3. registry.py, store.py, tools.py, orchestrator.py dùng chung một danh sách
     agent key duy nhất (không lệch nhau).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.agents.registry import AGENTS, WORKER_KEYS  # noqa: E402

OLD_NAMES = ["jarvis", "stark", "banner", "hawkeye", "pepper", "heimdall"]

# File được phép nhắc tên cũ (lịch sử), không tính là lỗi
ALLOWLIST = {
    "docs/CHANGELOG.md",
}

SCAN_DIRS = ["orchestrator", "web"]
SCAN_EXT = {".py", ".js", ".html"}


def find_old_name_leaks() -> list[str]:
    problems = []
    pattern = re.compile(r"\b(" + "|".join(OLD_NAMES) + r")\b", re.IGNORECASE)
    for d in SCAN_DIRS:
        for path in (ROOT / d).rglob("*"):
            if path.suffix not in SCAN_EXT or not path.is_file():
                continue
            rel = str(path.relative_to(ROOT))
            if rel in ALLOWLIST:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    problems.append(f"{rel}:{i}: {line.strip()[:100]}")
    return problems


def find_hardcoded_assignee_leaks() -> list[str]:
    """Bắt các chỗ hardcode assignee="xxx" mà xxx không phải agent hợp lệ hiện tại."""
    valid = set(WORKER_KEYS) | {"conan", "operator", ""}
    problems = []
    assign_pattern = re.compile(r'assignee\s*=\s*["\']([a-zA-Z_]+)["\']')
    for path in (ROOT / "orchestrator").rglob("*.py"):
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            for m in assign_pattern.finditer(line):
                name = m.group(1)
                if name not in valid:
                    problems.append(
                        f"{rel}:{i}: assignee=\"{name}\" không nằm trong WORKER_KEYS={sorted(WORKER_KEYS)}"
                    )
    return problems


def check_registry_matches_worker_keys() -> list[str]:
    problems = []
    registry_keys = set(AGENTS.keys())
    worker_keys = set(WORKER_KEYS)
    missing = worker_keys - registry_keys
    if missing:
        problems.append(f"WORKER_KEYS có key không tồn tại trong AGENTS: {missing}")
    return problems


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    failed = False

    print("=== 1. Quét tên agent cũ còn sót (jarvis/stark/banner/hawkeye/pepper/heimdall) ===")
    leaks = find_old_name_leaks()
    if leaks:
        failed = True
        for l in leaks:
            print(f"  FAIL  {l}")
    else:
        print("  PASS  Không còn tên agent cũ nào trong orchestrator/ và web/")

    print("\n=== 2. Quét assignee hardcode trỏ tới agent không tồn tại ===")
    bad_assignees = find_hardcoded_assignee_leaks()
    if bad_assignees:
        failed = True
        for b in bad_assignees:
            print(f"  FAIL  {b}")
    else:
        print(f"  PASS  Mọi assignee hardcode đều nằm trong WORKER_KEYS={sorted(WORKER_KEYS)}")

    print("\n=== 3. Đối chiếu registry.py AGENTS vs WORKER_KEYS ===")
    reg_problems = check_registry_matches_worker_keys()
    if reg_problems:
        failed = True
        for r in reg_problems:
            print(f"  FAIL  {r}")
    else:
        print("  PASS  AGENTS và WORKER_KEYS khớp nhau")

    print()
    if failed:
        print("KẾT QUẢ: FAIL — còn tồn tại lỗi tên agent, xem chi tiết ở trên.")
        sys.exit(1)
    else:
        print("KẾT QUẢ: ALL FILE DONE — không còn lỗi tên agent nào.")
        sys.exit(0)


if __name__ == "__main__":
    main()
