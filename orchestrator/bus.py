"""Event bus in-process: store phát event, WebSocket/daemon subscribe."""
import asyncio
from typing import Any

_subscribers: list[asyncio.Queue] = []


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)


def publish(event: dict[str, Any]) -> None:
    """Không chặn — an toàn khi gọi từ code sync chạy trong event loop."""
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
