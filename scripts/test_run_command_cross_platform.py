"""
Test: run_command phải tự phát hiện shell khả dụng (powershell/pwsh/bash) thay vì
hardcode "powershell" — bug cũ khiến run_command crash hoàn toàn trên Linux/Mac
với FileNotFoundError: [Errno 2] No such file or directory: 'powershell'.

Cách chạy:
    python scripts/test_run_command_cross_platform.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.board.models import Task  # noqa: E402
from orchestrator.agents.tools import ToolContext  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    failed = False
    # ignore_cleanup_errors: lệnh background (npm run dev) có thể giữ cwd trên Windows
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        task = Task(
            id="tsk-crossplat-test", title="cross-platform test", assignee="kid",
            project="crossplat-test", project_dir=tmp,
        )
        ctx = ToolContext(agent="kid", task=task)

        print("=== 1. Lệnh thường (echo + &&) ===")
        out = ctx.execute("run_command", {"command": "echo hello && echo world"})
        print(f"  output: {out!r}")
        if out.startswith("ERROR") or "hello" not in out or "world" not in out:
            failed = True
            print("  FAIL  lệnh cơ bản không chạy được")
        else:
            print("  OK")

        print("\n=== 2. Không còn hardcode 'powershell' gây FileNotFoundError ===")
        if "No such file or directory: 'powershell'" in out or "FileNotFoundError" in out:
            failed = True
            print("  FAIL  vẫn còn lỗi thiếu powershell trên máy này")
        else:
            print("  OK    không gặp lỗi thiếu powershell")

        print("\n=== 3. Lệnh background (server_pattern) không crash ===")
        out2 = ctx.execute("run_command", {"command": "npm run dev"})
        print(f"  output: {out2!r}")
        if out2.startswith("ERROR"):
            failed = True
            print("  FAIL  lệnh background bị lỗi")
        else:
            print("  OK")

        print("\n=== 4. Cú pháp PowerShell Start-Process trên máy không có PowerShell vẫn không crash ===")
        out3 = ctx.execute("run_command", {"command": "Start-Process node server.cjs"})
        print(f"  output: {out3!r}")
        if out3.startswith("ERROR: không thể khởi chạy") or "FileNotFoundError" in out3:
            failed = True
            print("  FAIL  cú pháp Start-Process làm crash trên máy không có PowerShell")
        else:
            print("  OK    (agent lỡ viết cú pháp Windows vẫn được dịch sang chạy nền bằng bash)")

    print()
    if failed:
        print("KẾT QUẢ: FAIL")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — run_command chạy được cross-platform.")
    sys.exit(0)


if __name__ == "__main__":
    main()
