"""Human Review Card — 1 file .md duy nhất tóm tắt đủ để operator quyết định
accept/reject 1 task, không phải đọc lại toàn bộ event log dài dằng dặc.

Lấy cảm hứng từ repo-harness (tasks/reviews/*.review.md): verdict, file thay đổi,
lệnh đã chạy qua, rủi ro còn lại, cách rollback — tất cả trong 1 màn hình.
"""
import re
from pathlib import Path

from .. import config
from . import store
from .models import Task


def _extract_changed_files(events: list) -> list[str]:
    """Bóc tên file được nhắc tới trong event log (best-effort)."""
    pattern = re.compile(
        r"\b[\w./-]+\.(?:py|js|jsx|ts|tsx|css|html|json|md|yml|yaml|cjs|mjs)\b"
    )
    files: dict[str, None] = {}
    for ev in events:
        for m in pattern.findall(ev.message or ""):
            files[m] = None
    return list(files.keys())[:30]


def _extract_commands(events: list) -> list[str]:
    """Bóc lệnh run_command đã chạy (best-effort qua event log dạng comment)."""
    pattern = re.compile(r"(?:npm|python|pytest|pip|git|bun|node)\s[^\n`]{0,120}")
    cmds: dict[str, None] = {}
    for ev in events:
        for m in pattern.findall(ev.message or ""):
            cmds[m.strip()] = None
    return list(cmds.keys())[:20]


def _extract_verdict(events: list) -> str:
    for ev in reversed(events):
        msg = ev.message or ""
        if "VERDICT: PASS" in msg or ("## " in msg and "PASS" in msg.upper()):
            return "PASS"
        if "VERDICT: FAIL" in msg:
            return "FAIL"
    return "UNKNOWN"


def build_review_card(task: Task) -> str:
    """Build nội dung markdown của Human Review Card cho 1 task."""
    events = store.list_events(task.id, limit=500)
    subtasks = store.list_tasks(parent_id=task.id)
    open_bugs = [t for t in subtasks if t.type == "bug" and t.status not in ("done", "archived")]

    verdict = _extract_verdict(events)
    changed_files = _extract_changed_files(events)
    commands = _extract_commands(events)

    lines = [
        f"# Human Review Card — `{task.id}`",
        "",
        f"**Verdict:** `{verdict}`" + ("  ⚠️ còn bug mở" if open_bugs else ""),
        f"**Task:** {task.title}",
        f"**Project:** `{task.project}` ({task.project_dir})",
        f"**Trạng thái hiện tại:** `{task.status.upper()}`",
        "",
        "## Đã thay đổi những file nào (best-effort, trích từ event log)",
    ]
    if changed_files:
        lines += [f"- `{f}`" for f in changed_files]
    else:
        lines.append("_Không trích được tên file cụ thể từ event log — xem chi tiết task để biết chính xác._")

    lines += ["", "## Lệnh đã chạy qua (best-effort)"]
    if commands:
        lines += [f"- `{c}`" for c in commands]
    else:
        lines.append("_Không có lệnh nào được ghi nhận trong event log._")

    lines += ["", "## Bug còn mở"]
    if open_bugs:
        for b in open_bugs:
            lines.append(f"- `{b.id}` ({b.severity}) — {b.title} — assignee: `{b.assignee}`")
    else:
        lines.append("Không còn bug mở.")

    lines += [
        "",
        "## Rủi ro còn lại",
        "_Tự động không đánh giá được rủi ro nghiệp vụ — operator cần tự đọc description "
        "và deliverable cuối cùng trước khi accept._",
        "",
        "## Rollback",
    ]
    if Path(task.project_dir or "").exists() and (Path(task.project_dir) / ".git").exists():
        lines.append(
            f"```\ncd {task.project_dir}\ngit log --oneline -5   # tìm commit cần revert\ngit revert <commit>\n```"
        )
    else:
        lines.append(
            "_Project không phải git repo (hoặc chưa xác định project_dir) — không có lệnh rollback tự động._"
        )

    lines += [
        "",
        "## Toàn bộ event log (theo thời gian)",
    ]
    for ev in events[-50:]:
        lines.append(
            f"- **[{ev.created_at[:19]}] `{ev.agent}` (`{ev.kind}`):** {(ev.message or '').strip()[:300]}"
        )

    return "\n".join(lines) + "\n"


def write_review_card(task: Task) -> Path:
    """Ghi Human Review Card ra workspace/wiki/reviews/<task_id>.review.md."""
    content = build_review_card(task)
    out_dir = config.WIKI_DIR / "reviews"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{task.id}.review.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path
