"""Unified Test Runner — Chạy toàn bộ các file test offline trong scripts/ và tổng hợp kết quả."""
import os
import sys
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 9 file test offline chính
TEST_FILES = [
    ("test_agent_consistency.py", "Tính nhất quán tên agent toàn codebase"),
    ("test_board.py", "State machine & board store guards"),
    ("test_json_repair.py", "Thuật toán sửa lỗi JSON dở chừng"),
    ("test_link_registry.py", "Link parser (GitHub, GitLab, Figma, Jira)"),
    ("test_prompt_tool_consistency.py", "Đối chiếu prompt & tool registry"),
    ("test_heiji_checklist_coverage.py", "Độ phủ QA checklist của Heiji"),
    ("test_security_pipeline.py", "Cấu hình role & tools Akai/Amuro"),
    ("test_figma.py", "Parse link & auth error handling Figma"),
    ("test_git.py", "Git clone & status check ops"),
]


def run_all():
    print("=" * 75)
    print(" 🚀 AGENT ORCHESTRATOR — UNIFIED TEST SUITE")
    print("=" * 75)
    print()

    results = []
    total_start = time.perf_counter()

    for filename, description in TEST_FILES:
        filepath = SCRIPTS_DIR / filename
        if not filepath.exists():
            results.append((filename, description, "MISSING", 0.0, "File không tồn tại"))
            continue

        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(filepath)],
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

    print(f"{'Test File':<35} | {'Mô tả':<32} | {'Kết quả':<8} | {'Thời gian':<10}")
    print("-" * 92)

    all_passed = True
    for filename, description, status, elapsed, err in results:
        status_str = "✅ PASS" if status == "PASS" else ("❌ FAIL" if status == "FAIL" else "⚠️ MISSING")
        if status != "PASS":
            all_passed = False
        print(f"{filename:<35} | {description:<32} | {status_str:<8} | {elapsed:.3f}s")

    print("-" * 92)
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
                print(err[:500])
        sys.exit(1)


if __name__ == "__main__":
    run_all()
