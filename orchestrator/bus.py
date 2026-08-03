"""Event bus in-process: store phát event, WebSocket/daemon subscribe."""
import asyncio
from typing import Any

_subscribers: list[asyncio.Queue] = []
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Gắn event loop chính — bắt buộc để publish an toàn từ worker thread."""
    global _main_loop
    _main_loop = loop


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)


def _put_all(event: dict[str, Any]) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def publish(event: dict[str, Any]) -> None:
    """Thread-safe: asyncio.Queue chỉ được touch từ event-loop thread.

    Agent tools chạy trong asyncio.to_thread() và gọi store → publish.
    put_nowait từ thread khác có thể treo/corrupt event loop → UI đơ hoàn toàn.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        _put_all(event)
        return

    loop = _main_loop
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(_put_all, event)
