"""Unified Test Runner — Chạy toàn bộ 5 test suite cốt lõi trong tests/ và tổng hợp kết quả."""
import os
import sys
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8")

# Chọn Python executable (ưu tiên .venv nếu có)
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON_BIN = str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable

# 5 Core Test Suites
TEST_FILES = [
    ("test_board.py", "Board Store, State Machine Guards & Review Cards"),
    ("test_agents.py", "Agent Registry, Consistency, Prompts & Security Roles"),
    ("test_core.py", "Core Engine: Runtime Loop, Bus, Scheduler & Gates"),
    ("test_tools.py", "Tools: Bug Routing, Figma, Run Command & Parsers"),
    ("test_routes.py", "API Routes: Path Traversal, Git Push Safety & URLs"),
]


def run_all():
    print("=" * 80)
    print(" 🚀 AGENT ORCHESTRATOR — CORE TEST SUITE")
    print(f" 🐍 Python: {PYTHON_BIN}")
    print("=" * 80)
    print()

    results = []
    total_start = time.perf_counter()

    for filename, description in TEST_FILES:
        filepath = TESTS_DIR / filename
        if not filepath.exists():
            results.append((filename, description, "MISSING", 0.0, "File không tồn tại"))
            continue

        start = time.perf_counter()
        proc = subprocess.run(
            [PYTHON_BIN, str(filepath)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.perf_counter() - start

        if proc.returncode == 0:
            results.append((filename, description, "PASS", elapsed, ""))
        else:
            err_msg = (proc.stderr or proc.stdout or "Lỗi không xác định").strip()
            results.append((filename, description, "FAIL", elapsed, err_msg))

    total_elapsed = time.perf_counter() - total_start

    print(f"{'Test File':<20} | {'Mô tả':<50} | {'Kết quả':<8} | {'Thời gian':<10}")
    print("-" * 95)

    all_passed = True
    for filename, description, status, elapsed, err in results:
        status_str = "✅ PASS" if status == "PASS" else ("❌ FAIL" if status == "FAIL" else "⚠️ MISSING")
        if status != "PASS":
            all_passed = False
        print(f"{filename:<20} | {description:<50} | {status_str:<8} | {elapsed:.3f}s")

    print("-" * 95)
    print(f"⏱️  Tổng thời gian thực thi: {total_elapsed:.3f}s")
    print()

    if all_passed:
        print("🎉 KẾT QUẢ: ALL TESTS PASSED! Hệ thống hoạt động chính xác 100%.")
        sys.exit(0)
    else:
        print("❌ KẾT QUẢ: Có test case thất bại. Chi tiết lỗi:")
        for filename, _, status, _, err in results:
            if status != "PASS":
                print(f"\n--- Lỗi ở {filename} ---")
                print(err[:800])
        sys.exit(1)


if __name__ == "__main__":
    run_all()
