"""Handoff snapshot — file .md ghi đè mỗi vòng scheduler, cho biết hệ thống đang
ở đâu MÀ KHÔNG CẦN MỞ DATABASE.

Lấy cảm hứng từ repo-harness (.ai/harness/handoff/) — "Resume the exact next step"
mà không phải grep-and-read lại toàn bộ event history hay mở SQLite bằng tay.
Khác biệt quan trọng: đây chỉ là snapshot ĐỌC (derived state), KHÔNG phải nguồn sự
thật — SQLite vẫn là nguồn sự thật duy nhất. File này chỉ để con người (hoặc 1
agent mới bắt đầu session) đọc nhanh mà không cần công cụ DB.
"""
from pathlib import Path

from .. import config
from ..board import store


def build_handoff_snapshot() -> str:
    in_progress = store.list_tasks(status=["in_progress"])
    backlog = store.list_tasks(status=["backlog"])
    review = store.list_tasks(status=["review"])
    blocked = store.list_tasks(status=["blocked"])

    lines = [
        "# Handoff Snapshot",
        "",
        "_File này tự động ghi đè mỗi vòng scheduler — chỉ để đọc nhanh, "
        "KHÔNG phải nguồn sự thật (SQLite mới là nguồn sự thật)._",
        "",
        f"## Đang chạy ({len(in_progress)})",
    ]
    if in_progress:
        for t in in_progress:
            lines.append(f"- `{t.id}` [{t.assignee}] {t.title} (project: `{t.project}`)")
    else:
        lines.append("_Không có task nào đang chạy._")

    lines += ["", f"## Chờ operator review ({len(review)})"]
    if review:
        for t in review:
            card = config.WIKI_DIR / "reviews" / f"{t.id}.review.md"
            card_note = f" — card: `{card}`" if card.is_file() else ""
            lines.append(f"- `{t.id}` {t.title}{card_note}")
    else:
        lines.append("_Không có task nào chờ review._")

    lines += ["", f"## Bị block, cần người can thiệp ({len(blocked)})"]
    if blocked:
        for t in blocked:
            lines.append(f"- `{t.id}` [{t.assignee}] {t.title}")
    else:
        lines.append("_Không có task nào bị block._")

    lines += ["", f"## Backlog chờ chạy ({len(backlog)})"]
    if backlog:
        for t in backlog[:20]:
            lines.append(f"- `{t.id}` [{t.assignee or 'chưa gán'}] {t.title}")
        if len(backlog) > 20:
            lines.append(f"- _...và {len(backlog) - 20} task khác_")
    else:
        lines.append("_Backlog trống._")

    return "\n".join(lines) + "\n"


def write_handoff_snapshot() -> Path:
    content = build_handoff_snapshot()
    out_path = config.WORKSPACE_DIR / "handoff.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path
