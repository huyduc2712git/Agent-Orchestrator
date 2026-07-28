"""Memory dài hạn (MEMORY.md) + wiki nội bộ (connections.md, features/)."""
import re
from datetime import datetime, timezone

from .. import config

MEMORY_FILE = config.MEMORY_DIR / "MEMORY.md"
CONNECTIONS_FILE = config.WIKI_DIR / "connections.md"
FEATURES_DIR = config.WIKI_DIR / "features"

MEMORY_SEED = """# MEMORY.md — Trí nhớ dài hạn của Jarvis

Ghi lại quyết định, pattern, bài học sau mỗi task. Mỗi entry một bullet, kèm ngày và task id.

## Entries
"""

CONNECTIONS_SEED = """# connections.md — Port, URL, service đang dùng

| Service | URL/Port | Ghi chú |
|---|---|---|
"""


def _ensure_seeds() -> None:
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text(MEMORY_SEED, encoding="utf-8")
    if not CONNECTIONS_FILE.exists():
        CONNECTIONS_FILE.write_text(CONNECTIONS_SEED, encoding="utf-8")


def read_memory() -> str:
    _ensure_seeds()
    return MEMORY_FILE.read_text(encoding="utf-8")


def append_memory(entry: str, task_id: str = "") -> None:
    _ensure_seeds()
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ref = f" [{task_id}]" if task_id else ""
    with MEMORY_FILE.open("a", encoding="utf-8") as f:
        f.write(f"- **{date}**{ref}: {entry.strip()}\n")


def read_wiki_summary(max_chars: int = 6000) -> str:
    """Gom nội dung wiki (connections + danh sách + nội dung features) cho context."""
    _ensure_seeds()
    parts = [CONNECTIONS_FILE.read_text(encoding="utf-8")]
    for f in sorted(FEATURES_DIR.glob("*.md")):
        parts.append(f"\n--- wiki/features/{f.name} ---\n{f.read_text(encoding='utf-8')}")
    out = "\n".join(parts)
    return out[:max_chars]


def write_feature(slug: str, content: str) -> str:
    _ensure_seeds()
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-") or "untitled"
    path = FEATURES_DIR / f"{slug}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)
