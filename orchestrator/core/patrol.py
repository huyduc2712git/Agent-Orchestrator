"""Board Patrol — quét board định kỳ, gom task cần người xử lý thành 1 digest (không spam)."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .. import config
from ..board import store

log = logging.getLogger("patrol")

_last_signature: str = ""


def _build_digest() -> tuple[str, str]:
    """Trả về (signature, digest_text). Digest rỗng nếu không có gì cần chú ý."""
    attention = []

    for t in store.list_tasks(status=["blocked"]):
        attention.append(f"- {t.id} [blocked] {t.title} — cần can thiệp")
    for t in store.list_tasks(status=["review"]):
        attention.append(f"- {t.id} [review] {t.title} — chờ operator approve")

    # in_progress quá lâu (>2h) có thể bị kẹt
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    for t in store.list_tasks(status=["in_progress"]):
        try:
            if datetime.fromisoformat(t.updated_at) < stale_cutoff and not t.parent_id == "":
                attention.append(f"- {t.id} [stale] {t.title} — in_progress hơn 2h")
        except ValueError:
            continue

    if not attention:
        return "", ""
    signature = "|".join(sorted(attention))
    text = "📋 Board Patrol — các mục cần bạn chú ý:\n" + "\n".join(attention)
    return signature, text


async def patrol_loop() -> None:
    global _last_signature
    log.info("Board Patrol started (interval %ss)", config.PATROL_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(config.PATROL_INTERVAL_SECONDS)
        try:
            signature, text = _build_digest()
            # chỉ gửi khi có thay đổi so với digest trước — tránh lặp lại
            if text and signature != _last_signature:
                _last_signature = signature
                store.add_chat("system", text)
        except Exception:
            log.exception("Patrol tick failed")
        try:
            from ..workspace_cleanup import cleanup_orphan_artifacts, cleanup_stale_workspace
            cleanup_stale_workspace()
            cleanup_orphan_artifacts()
        except Exception:
            log.exception("Workspace cleanup tick failed")
