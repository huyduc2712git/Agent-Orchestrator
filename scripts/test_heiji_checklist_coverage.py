"""
Test: persona Heiji sau khi viết lại (checklist) vẫn phải chứa đủ các "khái niệm bắt buộc"
so với bản gốc — tránh việc rút gọn/xóa emphasis làm mất luôn nội dung yêu cầu.

Cách chạy:
    python scripts/test_heiji_checklist_coverage.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.agents.registry import AGENTS  # noqa: E402

# Các khái niệm/hành vi bắt buộc phải còn xuất hiện đâu đó trong system_prompt() của Heiji
# (không cần đúng từng chữ — chỉ cần khái niệm còn được nhắc tới)
REQUIRED_CONCEPTS = [
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


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    prompt = AGENTS["heiji"].system_prompt()
    failed = False
    for concept, note in REQUIRED_CONCEPTS:
        if concept.lower() in prompt.lower():
            print(f"  OK    '{concept}' còn trong prompt — {note}")
        else:
            failed = True
            print(f"  FAIL  '{concept}' BỊ MẤT khỏi prompt — {note}")

    print()
    if failed:
        print("KẾT QUẢ: FAIL — checklist rút gọn đã làm mất nội dung yêu cầu.")
        sys.exit(1)
    print("KẾT QUẢ: ALL FILE DONE — checklist rút gọn vẫn giữ đủ nội dung gốc.")
    sys.exit(0)


if __name__ == "__main__":
    main()
