"""Dọn file tạm workspace sau khi xử lý xong — không tích tụ artifacts/uploads/cache."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from . import config

log = logging.getLogger("workspace_cleanup")

# Upload/cache hết hạn nếu còn sót (giờ)
STALE_MAX_AGE_HOURS = 24


def _safe_under(root: Path, path: Path) -> bool:
    try:
        return str(path.resolve()).startswith(str(root.resolve()))
    except OSError:
        return False


def remove_artifact_dir(task_id: str) -> bool:
    """Xóa workspace/artifacts/<task_id>/ nếu tồn tại."""
    tid = (task_id or "").strip()
    if not tid or "/" in tid or "\\" in tid or ".." in tid:
        return False
    root = config.ARTIFACTS_DIR
    path = (root / tid).resolve()
    if not _safe_under(root, path) or not path.is_dir():
        return False
    try:
        shutil.rmtree(path, ignore_errors=False)
        log.info("Đã xóa artifacts task %s", tid)
        return True
    except OSError as e:
        log.warning("Không xóa được artifacts/%s: %s", tid, e)
        return False


def cleanup_task_tree_artifacts(task_id: str, child_ids: list[str] | None = None) -> int:
    """Xóa artifacts của task + các subtask (khi task cha đóng/archive)."""
    ids = [task_id, *(child_ids or [])]
    n = 0
    for tid in ids:
        if remove_artifact_dir(tid):
            n += 1
    return n


def cleanup_upload_file(path: str | Path) -> bool:
    """Xóa một file trong uploads sau khi đã xử lý xong (vision/chat)."""
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    root = config.UPLOADS_DIR.resolve()
    if not _safe_under(root, p) or not p.is_file():
        return False
    try:
        p.unlink(missing_ok=True)
        log.info("Đã xóa upload tạm: %s", p.name)
        return True
    except OSError as e:
        log.warning("Không xóa được upload %s: %s", p, e)
        return False


def _unlink_old_files(directory: Path, max_age_hours: float) -> int:
    if not directory.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    n = 0
    try:
        for f in directory.rglob("*"):
            if not f.is_file():
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    n += 1
            except OSError:
                continue
    except OSError as e:
        log.warning("Scan stale trong %s lỗi: %s", directory, e)
    return n


def cleanup_stale_workspace(max_age_hours: float = STALE_MAX_AGE_HOURS) -> dict[str, int]:
    """Dọn uploads + cache đã cũ (sót lại sau crash / MCP copy)."""
    cache_dir = config.WORKSPACE_DIR / "cache"
    removed = {
        "uploads": _unlink_old_files(config.UPLOADS_DIR, max_age_hours),
        "cache": _unlink_old_files(cache_dir, max_age_hours),
    }
    # Xóa thư mục cache con trống
    if cache_dir.is_dir():
        for d in sorted(cache_dir.rglob("*"), reverse=True):
            if d.is_dir():
                try:
                    next(d.iterdir())
                except StopIteration:
                    try:
                        d.rmdir()
                    except OSError:
                        pass
                except OSError:
                    pass
    if any(removed.values()):
        log.info(
            "Stale cleanup: uploads=%s cache=%s (>%sh)",
            removed["uploads"], removed["cache"], max_age_hours,
        )
    return removed


def cleanup_orphan_artifacts() -> int:
    """Xóa artifacts của task đã done/archived/failed hoặc không còn trên board."""
    from .board import store

    root = config.ARTIFACTS_DIR
    if not root.is_dir():
        return 0
    n = 0
    for d in list(root.iterdir()):
        if not d.is_dir():
            continue
        task = store.get_task(d.name)
        if task is None or task.status in ("done", "archived", "failed"):
            if remove_artifact_dir(d.name):
                n += 1
    return n


def on_task_terminal(task_id: str, status: str) -> None:
    """Gọi khi task chuyển sang done/archived — dọn artifacts của cây task."""
    if status not in ("done", "archived"):
        return
    from .board import store

    task = store.get_task(task_id)
    if not task:
        remove_artifact_dir(task_id)
        return

    # Task cha: dọn cả subtask. Task con: chỉ dọn khi cha cũng đã đóng,
    # hoặc task độc lập (không có cha).
    if not task.parent_id:
        children = [t.id for t in store.list_tasks(parent_id=task_id, include_archived=True)]
        cleanup_task_tree_artifacts(task_id, children)
        return

    parent = store.get_task(task.parent_id)
    if parent and parent.status in ("done", "archived"):
        siblings = [t.id for t in store.list_tasks(parent_id=parent.id, include_archived=True)]
        cleanup_task_tree_artifacts(parent.id, siblings)
    elif parent is None:
        remove_artifact_dir(task_id)
