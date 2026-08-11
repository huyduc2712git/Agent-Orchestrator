"""Test suite: Agent Registry, Naming Consistency, Prompt-Tool Alignment, Security Roles & QA Checklists."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8")

from orchestrator.agents.registry import AGENTS, WORKER_KEYS

OLD_NAMES = ["jarvis", "stark", "banner", "hawkeye", "pepper", "heimdall"]
ALLOWLIST = {"docs/CHANGELOG.md"}
SCAN_DIRS = ["orchestrator", "web"]
SCAN_EXT = {".py", ".js", ".html"}

PROMPT_TOOL_MAP = {
    "create_bug_ticket": "create_bug_ticket",
    "figma_get": "figma_get",
    "screenshot_url": "screenshot_url",
    "inspect_render": "inspect_render",
    "git_clone": "git_clone",
    "run_command": "run_command",
    "write_file": "write_file",
}

REFERENTIAL_ONLY = {
    ("conan", "create_bug_ticket"),
    ("haibara", "create_bug_ticket"),
}

HEIJI_REQUIRED_CONCEPTS = [
    ("Live URL", "xác định URL để test"),
    ("http_get", "verify status bằng http_get"),
    ("same-origin", "kiểm tra API same-origin, không PASS chỉ vì UI đẹp"),
    ("figma_get", "đọc Figma spec trước khi so sánh"),
    ("screenshot_url", "chụp screenshot desktop+mobile"),
    ("inspect_render", "kiểm tra CSS/render"),
    ("Visual QA Report", "post_message báo cáo đúng format"),
    ("VERDICT", "kết luận PASS/FAIL"),
    ("create_bug_ticket", "tạo bug ticket cho lỗi phát hiện"),
    ("search_tasks", "kiểm tra trùng lặp trước khi tạo bug (kế thừa từ BUG_REPORT_RULE)"),
    ("Conan", "Final Review chỉ chạy sau khi Heiji PASS"),
]


def _find_old_name_leaks() -> list[str]:
    problems = []
    pattern = re.compile(r"\b(" + "|".join(OLD_NAMES) + r")\b", re.IGNORECASE)
    for d in SCAN_DIRS:
        for path in (ROOT / d).rglob("*"):
            if path.suffix not in SCAN_EXT or not path.is_file():
                continue
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if rel in ALLOWLIST:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    problems.append(f"{rel}:{i}: {line.strip()[:100]}")
    return problems


def _find_hardcoded_assignee_leaks() -> list[str]:
    valid = set(WORKER_KEYS) | {"conan", "operator", ""}
    problems = []
    assign_pattern = re.compile(r'assignee\s*=\s*["\']([a-zA-Z_]+)["\']')
    for path in (ROOT / "orchestrator").rglob("*.py"):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        text = path.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            for m in assign_pattern.finditer(line):
                name = m.group(1)
                if name not in valid:
                    problems.append(
                        f"{rel}:{i}: assignee=\"{name}\" không nằm trong WORKER_KEYS={sorted(WORKER_KEYS)}"
                    )
    return problems


def test_agent_naming_consistency():
    """Kiểm tra không còn tên agent cũ còn sót, không có assignee lạ, và registry khớp worker keys."""
    assert len(_find_old_name_leaks()) == 0, "Phát hiện tên agent cũ còn sót lại"
    assert len(_find_hardcoded_assignee_leaks()) == 0, "Phát hiện assignee hardcode không hợp lệ"
    missing = set(WORKER_KEYS) - set(AGENTS.keys())
    assert not missing, f"WORKER_KEYS có key không tồn tại trong AGENTS: {missing}"


def test_prompt_tool_consistency():
    """Kiểm tra system prompt của agent không ra lệnh dùng tool mà agent đó không được cấp."""
    for key, agent in AGENTS.items():
        prompt = agent.system_prompt()
        for phrase, tool in PROMPT_TOOL_MAP.items():
            if phrase in prompt and tool not in agent.tools and (key, tool) not in REFERENTIAL_ONLY:
                assert False, f'{key}: prompt nhắc "{phrase}" nhưng agent không có tool "{tool}" (tools={agent.tools})'


def test_security_critic_agent_restrictions():
    """Kiểm tra Akai & Amuro chỉ có role critic và tuyệt đối bị cấm các tool write_file/run_command."""
    for key in ["akai", "amuro"]:
        assert key in AGENTS, f"'{key}' chưa có trong AGENTS"
        a = AGENTS[key]
        forbidden = {"write_file", "run_command", "bash"}
        leaked = forbidden & set(a.tools)
        assert not leaked, f"{key} có tool bị cấm: {leaked}"
        assert key in WORKER_KEYS, f"'{key}' chưa có trong WORKER_KEYS"


def test_heiji_checklist_coverage():
    """Kiểm tra prompt của Heiji (QA Agent) chứa đầy đủ các khái niệm bắt buộc trong QA checklist."""
    prompt = AGENTS["heiji"].system_prompt()
    for concept, note in HEIJI_REQUIRED_CONCEPTS:
        assert concept.lower() in prompt.lower(), f"'{concept}' BỊ MẤT khỏi prompt của Heiji — {note}"


def main():
    test_agent_naming_consistency()
    test_prompt_tool_consistency()
    test_security_critic_agent_restrictions()
    test_heiji_checklist_coverage()
    print("PASS test_agents (Registry, consistency, prompts & security constraints OK)")


if __name__ == "__main__":
    main()
