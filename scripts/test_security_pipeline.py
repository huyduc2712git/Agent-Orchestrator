"""Test: Akai/Amuro có đúng role critic, không có tool write_file/run_command."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchestrator.agents.registry import AGENTS, WORKER_KEYS


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    failed = False
    for key in ["akai", "amuro"]:
        if key not in AGENTS:
            print(f"FAIL  '{key}' chưa có trong AGENTS")
            failed = True
            continue
        a = AGENTS[key]
        forbidden = {"write_file", "run_command"}
        leaked = forbidden & set(a.tools)
        if leaked:
            print(f"FAIL  {key} có tool bị cấm: {leaked}")
            failed = True
        else:
            print(f"PASS  {key}: role={a.role}, tools={a.tools}")
        if key not in WORKER_KEYS:
            print(f"FAIL  '{key}' chưa có trong WORKER_KEYS")
            failed = True

    print()
    print("KẾT QUẢ: FAIL" if failed else "KẾT QUẢ: ALL FILE DONE — Akai/Amuro cấu hình đúng.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
