# AI Orchestrator (kiểu Jarvis)

Hệ thống multi-agent hiện thực hóa bản thiết kế trong [docs/design.md](docs/design.md):
Jarvis (orchestrator) nhận task qua chat, phân tích và chia subtask có dependency, giao cho
các agent chuyên môn **thực thi thật** trên máy (đọc/ghi file, chạy lệnh), QA có bằng chứng,
review gate, và ghi nhớ bài học vào memory/wiki.

## Đội hình agent

| Agent | Vai trò |
|---|---|
| **Jarvis** | Orchestrator — lập kế hoạch, verify độc lập, đóng task. Không code. |
| **Stark** | Builder — UI/frontend, viết code chính |
| **Banner** | Backend — API, data, script |
| **Hawkeye** | QA — verify từng acceptance criteria, tạo bug ticket. Không sửa code. |
| **Pepper** | Manager — tổng hợp báo cáo |

## Chạy

```powershell
pip install -r requirements.txt
python -m orchestrator.main
```

Mở http://127.0.0.1:8600 — chat với Jarvis bên trái, Kanban board realtime bên phải.

Cấu hình trong `.env`: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` (endpoint OpenAI-compatible
bất kỳ), `HOST`, `PORT`.

## Luồng vận hành (6 phase)

1. **Tiếp nhận** — chat gửi vào `/api/chat`, Jarvis đọc memory + wiki + board trước khi quyết định.
2. **Phân tích & lập kế hoạch** — trả lời ngay; task phức tạp được chia subtask chain có
   dependency, luôn kèm subtask QA cuối gán Hawkeye với acceptance criteria cụ thể.
3. **Phân công** — scheduler tự chạy subtask khi dependency đã xong (`blocks` dep thỏa mãn
   khi task nguồn đạt `testing`+).
4. **Theo dõi** — event bus đẩy realtime qua WebSocket; Board Patrol quét định kỳ, gom
   task blocked/review/stale thành 1 digest, không spam.
5. **Kiểm tra & hoàn tất** — Hawkeye verify từng criteria và tạo bug ticket (schema bắt buộc,
   search chống trùng, link `related`); bug mở được giao fix round; Pepper tổng hợp;
   Jarvis **verify độc lập** bằng tool thật rồi mới đóng.
6. **Ghi nhớ** — cập nhật `workspace/memory/MEMORY.md` + `workspace/wiki/features/`.

## Nguyên tắc được enforce ở tầng hệ thống

- Mọi thay đổi status đi qua transition guard ([orchestrator/board/state_machine.py](orchestrator/board/state_machine.py)):
  - Agent set `review` trên task agent-only → tự normalize về `testing` kèm giải thích.
  - Task gắn tag `db-migration` / `security` / `deploy-prod` → bắt buộc **operator review**,
    chỉ người thật bấm Approve trên UI mới đóng được.
  - Agent không tự đóng task mình làm; Jarvis không approve việc của chính Jarvis.
- Agent bị giới hạn trong project directory của task (path sandbox), lệnh có timeout.

## Kiểm thử

```powershell
python scripts/test_board.py     # store + transition guard
python scripts/test_llm.py       # endpoint LLM + tool calling
python scripts/test_runtime.py   # agent thật ghi file thật
```

## Cấu trúc

- `orchestrator/board/` — SQLite store, models, state machine
- `orchestrator/agents/` — registry persona, runtime tool-calling, bộ tool
- `orchestrator/core/` — orchestrator 6 phase, scheduler, board patrol
- `orchestrator/memory/` — MEMORY.md + wiki store
- `web/` — UI chat + Kanban
- `workspace/` — dữ liệu runtime (board.db, memory, wiki, projects)
