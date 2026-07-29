"""Transition guard cho status của task — enforce ở tầng hệ thống, không tin agent tự giác.

Nguyên tắc (theo docs/design.md + log jts-0001):
- Trạng thái `review` chỉ dành cho task có review_type=operator. Agent set `review`
  trên task agent-only sẽ bị normalize về `testing` kèm message giải thích (kiểu Heimdall).
- Task operator-review ở trạng thái `review` chỉ operator mới được duyệt sang `done`.
- Agent không tự set `done` cho task mình làm — chỉ jarvis (closure flow) hoặc operator.
"""
from dataclasses import dataclass

from .models import Task

ALLOWED = {
    "backlog": {"in_progress", "blocked", "archived", "failed"},
    "in_progress": {"testing", "blocked", "backlog", "failed"},
    "blocked": {"backlog", "in_progress", "failed"},
    "testing": {"review", "done", "in_progress", "blocked", "failed"},
    "review": {"done", "testing", "failed"},
    "done": {"archived", "in_progress"},
    "failed": {"backlog", "archived"},
    "archived": set(),
}

OPERATOR = "operator"
JARVIS = "jarvis"


@dataclass
class TransitionResult:
    final_status: str
    accepted: bool
    note: str = ""  # message hệ thống nếu bị normalize/từ chối


def request_transition(task: Task, new_status: str, actor: str) -> TransitionResult:
    cur = task.status

    if new_status == cur:
        return TransitionResult(cur, True)

    if new_status not in ALLOWED.get(cur, set()):
        return TransitionResult(
            cur,
            False,
            f"Chuyển trạng thái không hợp lệ: {cur} → {new_status}. Giữ nguyên {cur}.",
        )

    # Guard 1: review chỉ dành cho operator review
    if new_status == "review" and task.review_type != "operator":
        return TransitionResult(
            "testing",
            False,
            "Review normalized về testing — task này dùng agent-only review, trạng thái "
            "review được dành riêng cho operator review. Quy trình đúng: tester post PASS "
            "evidence dạng message, Jarvis sẽ complete task từ testing.",
        )

    # Guard 2: từ review sang done chỉ operator được duyệt
    if cur == "review" and new_status == "done" and actor != OPERATOR:
        return TransitionResult(
            cur,
            False,
            f"Task đang chờ operator review — {actor} không có quyền duyệt. "
            "Cần người thật bấm Approve trên UI.",
        )

    # Guard 3: không tự approve việc của chính mình
    if new_status == "done":
        if actor not in (OPERATOR, JARVIS):
            return TransitionResult(
                cur,
                False,
                f"{actor} không được tự đóng task. Post deliverable/PASS evidence, "
                "Jarvis sẽ verify độc lập và đóng task.",
            )
        if actor == JARVIS and task.assignee == JARVIS:
            return TransitionResult(
                cur,
                False,
                "Jarvis không được tự approve task do chính mình thực hiện — "
                "cần agent khác hoặc operator xác nhận.",
            )

    return TransitionResult(new_status, True)
