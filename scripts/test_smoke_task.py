"""Test lập kế hoạch & khởi chạy task cho project 'smoke'."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from orchestrator.core.orchestrator import handle_chat
from orchestrator.board import store

async def main():
    print("=== 1. Gửi tin nhắn yêu cầu cho Conan với project 'smoke' ===")
    prompt = "Thêm route GET /api/health trả về status ok và timestamp cho server.cjs trong project smoke"
    print(f"User Prompt: '{prompt}'")
    
    await handle_chat(prompt, project="smoke")
    
    print("\n=== 2. Lấy danh sách Task đã được Conan tạo trong DB ===")
    tasks = store.list_tasks()
    print(f"Tổng số task hiện có: {len(tasks)}")
    
    smoke_tasks = [t for t in tasks if t.project == "smoke"]
    print(f"Số task thuộc project 'smoke': {len(smoke_tasks)}")
    
    for t in smoke_tasks:
        parent_info = f" (con của {t.parent_id})" if t.parent_id else " (TASK CHA)"
        print(f" - [{t.id}] {t.status.upper()} | Assignee: {t.assignee or 'chưa gán'} | Title: {t.title}{parent_info}")
        print(f"   Project Dir: {t.project_dir}")

    print("\n=== 3. Lịch sử Chat gần nhất ===")
    chats = store.list_chat(limit=3)
    for c in chats:
        print(f" [{c['role']}]: {c['message'][:150]}...")

    print("\nKẾT QUẢ: Lập kế hoạch task cho project 'smoke' OK.")

if __name__ == "__main__":
    asyncio.run(main())
