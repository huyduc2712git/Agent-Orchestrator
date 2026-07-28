# MEMORY.md — Trí nhớ dài hạn của Jarvis

Ghi lại quyết định, pattern, bài học sau mỗi task. Mỗi entry một bullet, kèm ngày và task id.

## Entries
- **2026-07-27** [tsk-0001]: Khi tạo landing page tĩnh, cần đảm bảo header, menu, footer đúng yêu cầu, CSS tông màu ấm và không dùng inline style.
- **2026-07-27** [tsk-0004]: Khi build từ Figma, cần tránh dùng nth-child trên các phần tử không đồng nhất, thay bằng first-of-type để tránh crash. Luôn kiểm tra selector với nhiều breakpoint.
- **2026-07-27** [tsk-0007]: Khi review task frontend từ Figma, always verify độc lập chuỗi bằng chứng: tồn tại file, live URL hoạt động, và nội dung code hợp lệ (BEM, responsive, color match). QA trước đó không thay thế verification cuối cùng.
- **2026-07-27** [tsk-0010]: Luôn verify toàn bộ chain (build → QA → review) trước khi approve: check file tồn tại, HTTP 200, BEM/CSS variables/JS interactions đúng yêu cầu. Pattern approve có thể tái sử dụng cho mọi static site build task.
