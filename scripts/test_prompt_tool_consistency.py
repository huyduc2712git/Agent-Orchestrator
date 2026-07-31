"""
Test: prompt (system_prompt) của mỗi agent không được ra lệnh dùng tool mà
agent đó không có trong danh sách tools. Đây là loại lỗi "prompt tự mâu thuẫn"
— rule chung nói phải làm X, nhưng agent không có tool để làm X.

Cách chạy:
    python scripts/test_prompt_tool_consistency.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.agents.registry import AGENTS  # noqa: E402

# Map: cụm từ hay xuất hiện trong prompt <-> tool cần có để thực hiện được
PROMPT_TOOL_MAP = {
    "create_bug_ticket": "create_bug_ticket",
    "figma_get": "figma_get",
    "screenshot_url": "screenshot_url",
    "inspect_render": "inspect_render",
    "git_clone": "git_clone",
    "run_command": "run_command",
    "write_file": "write_file",
}

# Agent được phép nhắc tên tool trong prompt dù không có tool đó, vì chỉ nhắc
# ở dạng phủ định/giải thích cho agent khác làm (không phải tự ra lệnh cho mình)
REFERENTIAL_ONLY = {
    ("conan", "create_bug_ticket"),  # "KHÔNG tạo bug ticket (đó là việc của Heiji/QA)"
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    failed = False
    for key, agent in AGENTS.items():
        prompt = agent.system_prompt()
        for phrase, tool in PROMPT_TOOL_MAP.items():
            if phrase in prompt and tool not in agent.tools and (key, tool) not in REFERENTIAL_ONLY:
                failed = True
                print(
                    f'  FAIL  {key}: prompt nhắc "{phrase}" nhưng agent không có '
                    f'tool "{tool}" (tools={agent.tools})'
                )
        else:
            pass
        print(f"  OK    {key}: prompt tự nhắc {sum(1 for p in PROMPT_TOOL_MAP if p in prompt)} tool-phrase, "
              f"đều khớp tools={sorted(agent.tools)}")

    print()
    if failed:
        print("KẾT QUẢ: FAIL — còn prompt ra lệnh dùng tool agent không có.")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — mọi prompt đều khớp đúng tool thật.")
    sys.exit(0)


if __name__ == "__main__":
    main()
