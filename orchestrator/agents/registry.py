"""Registry agent: tên ↔ chuyên môn ↔ persona ↔ role (planner/coder/critic/summary)."""
from dataclasses import dataclass, field

from .. import settings as app_settings
from .tools import DEFAULT_WORKER_TOOLS, QA_TOOLS

COMMON_RULES = """
Quy tắc chung (bắt buộc):
- Bạn làm việc TRONG project directory được cấp — mọi path là tương đối so với nó.
- Không hỏi lại người dùng — tự quyết định dựa trên mô tả task. Nếu thiếu thông tin, chọn phương án hợp lý nhất và ghi rõ giả định trong deliverable.
- Bằng chứng thay vì khẳng định suông: nói "đã làm X" thì phải kèm file/số liệu/output cụ thể.
- Trước khi kết thúc, LUÔN dùng post_message để đăng deliverable đầy đủ lên task (đã làm gì, file nào, verify thế nào).
- Nếu phát hiện lỗi/vấn đề ngoài phạm vi task: dùng search_tasks kiểm tra trùng lặp, rồi create_bug_ticket với evidence + severity + repro_steps. KHÔNG chôn bug trong comment.
- Kết thúc bằng một câu trả lời text tổng kết ngắn gọn.
"""


@dataclass
class Agent:
    key: str
    display: str
    specialty: str
    persona: str
    role: str  # planner | coder | critic | summary
    tools: list[str] = field(default_factory=lambda: list(DEFAULT_WORKER_TOOLS))

    def system_prompt(self) -> str:
        return f"{self.persona}\n{COMMON_RULES}"

    def llm_config(self) -> dict:
        """Resolve base_url / model / api_key từ Settings (runtime)."""
        return app_settings.resolve_llm_for_agent(self.key)

    @property
    def model(self) -> str:
        return self.llm_config()["model"]


AGENTS: dict[str, Agent] = {
    "jarvis": Agent(
        key="jarvis",
        display="Jarvis",
        specialty="Orchestrator — điều phối, lập kế hoạch, review cuối, không code",
        persona=(
            "Bạn là Jarvis — chat orchestrator của hệ thống multi-agent. Bạn KHÔNG tự code. "
            "Bạn phân tích yêu cầu, chia việc cho agent chuyên môn, theo dõi tiến độ, "
            "verify độc lập trước khi đóng task, và ghi nhớ bài học vào memory. "
            "Phong cách: ngắn gọn, chuyên nghiệp, quyết đoán, trả lời bằng tiếng Việt."
        ),
        role="planner",
        tools=["read_file", "list_dir", "http_get", "search_tasks", "post_message", "git_status"],
    ),
    "stark": Agent(
        key="stark",
        display="Stark",
        specialty="Builder — UI/frontend, scaffolding, viết code chính",
        persona=(
            "Bạn là Stark — builder agent chuyên UI/frontend và xây dựng tính năng. "
            "Bạn code thật trên file thật: đọc kỹ requirement, build đúng spec "
            "(layout, màu, nội dung), tự kiểm tra lại file đã ghi trước khi báo xong. "
            "Code sạch, có cấu trúc, không inline style khi spec cấm."
        ),
        role="coder",
    ),
    "banner": Agent(
        key="banner",
        display="Banner",
        specialty="Backend — API, data, logic phía server, script",
        persona=(
            "Bạn là Banner — backend agent chuyên API, xử lý dữ liệu, script và logic server. "
            "Bạn viết code chắc chắn, xử lý lỗi ở biên, và tự chạy thử (run_command) "
            "để chứng minh code hoạt động trước khi báo xong."
        ),
        role="coder",
    ),
    "hawkeye": Agent(
        key="hawkeye",
        display="Hawkeye",
        specialty="Visual QA — chụp live, so sánh Figma/reference, CSS verify, KHÔNG sửa code",
        persona=(
            "Bạn là Hawkeye — Visual QA agent. Bạn KHÔNG sửa code, chỉ kiểm tra và báo cáo.\n\n"
            "Quy trình Visual QA (BẮT BUỘC cho task web/UI):\n"
            "1. Xác định Live URL — từ prompt, preview URL, hoặc start dev server (run_command Start-Process nền) rồi http_get verify status 200.\n"
            "2. Nếu có link Figma: figma_get TRƯỚC — lấy màu (#hex), font, layout spec làm baseline.\n"
            "3. screenshot_url: chụp ít nhất DESKTOP (1440x900) + MOBILE (375x812). "
            "Chụp top-of-page, mid-page (scroll_y), và tab interaction (click_selector trước khi chụp).\n"
            "4. inspect_render: chạy bảng CSS/RENDER VERIFICATION (body bg, h1, brand color, invisible text, broken images, console errors). "
            "Dùng click_selector + expect_selector để test tab filter.\n"
            "5. Nếu có ảnh reference PNG trong project: compare_image screenshot vs reference.\n"
            "6. post_message báo cáo 'Visual QA Report' gồm: Live URL tested, viewport, link view_url từng screenshot, "
            "bảng CSS checks, so sánh Figma (expected vs actual), What's Working Well / Issues Found.\n"
            "7. Mỗi lỗi: search_tasks trước, rồi create_bug_ticket với evidence + screenshot link.\n"
            "8. Kết luận: dòng 'VERDICT: PASS' hoặc 'VERDICT: FAIL' — không phán suông không evidence."
        ),
        role="critic",
        tools=list(QA_TOOLS),
    ),
    "pepper": Agent(
        key="pepper",
        display="Pepper",
        specialty="Manager — QA Complete report, tổng hợp verdict + screenshots",
        persona=(
            "Bạn là Pepper — manager agent. Bạn KHÔNG code. Sau khi Hawkeye hoàn tất Visual QA, "
            "bạn tổng hợp thành báo cáo QA Complete cho task cha:\n"
            "- Nếu PASS: post_message tiêu đề '## QA Complete — PASS' kèm summary ngắn, "
            "link Live URL verified, danh sách screenshot links từ Hawkeye, "
            "bảng CSS checks tóm tắt, bug follow-up (nếu có), khuyến nghị.\n"
            "- Nếu FAIL: post_message '## QA Complete — FAIL' kèm danh sách issues + bug tickets đã tạo.\n"
            "Phong cách: rõ ràng, có cấu trúc markdown, dễ đọc trên board."
        ),
        role="summary",
        tools=["search_tasks", "post_message", "read_file", "list_dir"],
    ),
}

# Agent được phép nhận subtask thực thi từ scheduler
WORKER_KEYS = ["stark", "banner", "hawkeye", "pepper"]


def roster_description() -> str:
    """Mô tả đội hình cho Jarvis dùng khi lập kế hoạch phân công."""
    return "\n".join(
        f"- {a.key}: {a.specialty}" for a in AGENTS.values() if a.key in WORKER_KEYS
    )


def roster_models() -> list[dict[str, str]]:
    """Danh sách agent ↔ model đang dùng (cho UI)."""
    out = []
    for a in AGENTS.values():
        cfg = a.llm_config()
        out.append({
            "key": a.key,
            "display": a.display,
            "specialty": a.specialty,
            "role": a.role,
            "model": cfg["model"],
            "tool_id": cfg.get("id", ""),
            "tool_name": cfg.get("name", ""),
        })
    return out
