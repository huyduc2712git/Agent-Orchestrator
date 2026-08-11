# AI Orchestrator

Hệ thống multi-agent hiện thực hóa quy trình điều phối dự án thông minh:
**Conan** (orchestrator) nhận task qua chat, phân tích và chia subtask có dependency, giao cho
các agent chuyên môn **thực thi thật** trên máy (đọc/ghi file, chạy lệnh), QA có bằng chứng,
review gate bảo mật (Akai/Amuro), và ghi nhớ bài học vào memory/wiki.

## Đội hình Agent

| Agent | Vai trò | Chuyên môn |
|---|---|---|
| **Conan** | Orchestrator / Planner | Lập kế hoạch, điều phối subtask, review độc lập, đóng task. Không code. |
| **Kaito Kid** | Frontend Builder | UI/UX, ảo thuật thị giác, scaffolding, viết code giao diện chính. |
| **Agasa** | Backend Specialist | API, logic server, data, script backend, gadget công nghệ. |
| **Heiji** | Visual QA | Quan sát sắc bén, chụp màn hình live, so sánh Figma spec, kiểm tra CSS. |
| **Ai Haibara** | Quality Reviewer | Cẩn trọng, logic, tổng hợp báo cáo QA Complete, đánh giá rủi ro. |
| **Shuichi Akai** | Security Reviewer | Rà soát bảo mật mã nguồn, auth/authz, SQLi, XSS, CVE dependency. |
| **Rei Furuya (Amuro)** | Penetration Tester | Thử nghiệm tấn công pentest trên preview/staging, kiểm thử hạ tầng. |

## Cài đặt & Khởi chạy

Dự án sử dụng môi trường ảo `.venv`:

```powershell
# 1. Kích hoạt môi trường ảo:
.\.venv\Scripts\Activate.ps1
python -m orchestrator.main

# Hoặc chạy trực tiếp qua Python trong .venv:
.\.venv\Scripts\python.exe -m orchestrator.main
```

Mở giao diện tại: http://127.0.0.1:8600 (Chat điều phối bên trái, Kanban realtime bên phải).

Cấu hình trong `.env` hoặc trên UI: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `HOST`, `PORT`.

## Luồng Vận Hành (6 Phase)

1. **Tiếp nhận** — Chat gửi vào `/api/chat`, Conan đọc memory + wiki + board trước khi lập kế hoạch.
2. **Phân tích & Lập kế hoạch** — Task phức tạp được chia subtask chain có dependency, luôn kèm subtask QA (Heiji) với acceptance criteria rõ ràng.
3. **Phân công & Thực thi** — Scheduler tự động chạy worker khi dependency đã thỏa mãn (`blocks` thỏa mãn khi task nguồn đạt `testing`+).
4. **Theo dõi** — Event bus WebSocket realtime; Board Patrol tự động quét phát hiện task stale / blocked.
5. **Kiểm tra & Review Gate** — Heiji kiểm tra giao diện/API -> Akai rà soát bảo mật -> Amuro thử pentest -> Conan Final Review.
6. **Ghi nhớ** — Cập nhật `workspace/memory/MEMORY.md` và `workspace/wiki/`.

## Kiểm Thử (Tests)

Các bài test được thiết kế cô lập hoàn toàn (sử dụng database và workspace tạm, **không tạo project rác trong `workspace/projects/` và không làm ô nhiễm `workspace/board.db`**).

```powershell
# Chạy toàn bộ test suite:
.\.venv\Scripts\python.exe scripts\run_all_tests.py

# Hoặc chạy riêng từng test:
.\.venv\Scripts\python.exe tests\test_tools.py
```

## Cấu Trúc Dự Án

- `orchestrator/agents/` — Registry persona, runtime tool-calling, bộ tools
- `orchestrator/board/` — SQLite store, models, state machine guards, review cards
- `orchestrator/core/` — Orchestrator 6 phase, scheduler worker loop, patrol, handoff
- `orchestrator/links/` — Bộ parser và registry liên kết (Git, Figma, Jira)
- `orchestrator/mcp/` — MCP client & Figma shim
- `orchestrator/memory/` — Persistent memory store & wiki
- `orchestrator/qa/` — Playwright browser inspector & Visual QA
- `orchestrator/routes/` — FastAPI endpoints (chat, board, projects, preview, settings)
- `orchestrator/skills/` — Reasonix skill playbooks & agent prompts
- `tests/` — Bộ test suite chuẩn (unit, integration, state machine, safety)
- `web/` — Giao diện web UI (HTML, CSS, JS modular)
- `workspace/` — Dữ liệu runtime (board.db, settings.json, memory, wiki)
