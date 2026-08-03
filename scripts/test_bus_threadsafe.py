"""bus.publish từ worker thread không được gọi put_nowait trực tiếp trên asyncio.Queue."""
import asyncio
import threading
import time

from orchestrator import bus


def test_publish_from_worker_thread_reaches_subscriber():
    async def _run():
        bus.set_main_loop(asyncio.get_running_loop())
        q = bus.subscribe()
        try:
            done = threading.Event()

            def worker():
                bus.publish({"type": "probe", "ok": True})
                done.set()

            t = threading.Thread(target=worker)
            t.start()
            t.join(timeout=2)
            assert done.is_set(), "worker không chạy xong"

            # cho call_soon_threadsafe kịp chạy
            for _ in range(50):
                if not q.empty():
                    break
                await asyncio.sleep(0.02)

            assert not q.empty(), "event không tới queue (publish không thread-safe?)"
            ev = q.get_nowait()
            assert ev.get("type") == "probe"
        finally:
            bus.unsubscribe(q)

    asyncio.run(_run())


if __name__ == "__main__":
    test_publish_from_worker_thread_reaches_subscriber()
    print("PASS test_bus_threadsafe")
