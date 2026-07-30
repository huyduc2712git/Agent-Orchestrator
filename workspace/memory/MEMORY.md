# MEMORY.md — Trí nhớ dài hạn của Jarvis

Ghi lại quyết định, pattern, bài học sau mỗi task. Mỗi entry một bullet, kèm ngày và task id.

## Entries
- **2026-07-27** [tsk-0001]: Khi tạo landing page tĩnh, cần đảm bảo header, menu, footer đúng yêu cầu, CSS tông màu ấm và không dùng inline style.
- **2026-07-27** [tsk-0004]: Khi build từ Figma, cần tránh dùng nth-child trên các phần tử không đồng nhất, thay bằng first-of-type để tránh crash. Luôn kiểm tra selector với nhiều breakpoint.
- **2026-07-27** [tsk-0007]: Khi review task frontend từ Figma, always verify độc lập chuỗi bằng chứng: tồn tại file, live URL hoạt động, và nội dung code hợp lệ (BEM, responsive, color match). QA trước đó không thay thế verification cuối cùng.
- **2026-07-27** [tsk-0010]: Luôn verify toàn bộ chain (build → QA → review) trước khi approve: check file tồn tại, HTTP 200, BEM/CSS variables/JS interactions đúng yêu cầu. Pattern approve có thể tái sử dụng cho mọi static site build task.
- **2026-07-28** [tsk-0013]: Khi build responsive UI từ Figma, cần đảm bảo đầy đủ 3 breakpoints ngay từ đầu (mobile/tablet/desktop) thay vì chỉ 1 breakpoint. CSS nên chi tiết hơn để tránh phải refactor sau.
- **2026-07-28** [tsk-0013]: Task xây dựng giao diện web từ Figma đã được duyệt thành công với pattern: tạo đủ 3 file HTML/CSS/JS, áp dụng BEM, responsive theo breakpoints, và tích hợp font từ Google Fonts.
- **2026-07-28** [tsk-0016]: Việc tuân thủ nghiêm ngặt BEM và CSS Variables giúp code UI dễ bảo trì và đồng bộ màu sắc thương hiệu. Sử dụng placehold.co thay vì các dịch vụ cũ giúp tăng tốc độ tải trang và độ ổn định cho demo.
- **2026-07-29** [tsk-0022]: Task clone repo thành công: VoxBeat là Vietnamese Music Player (React 19 + Vite 6 + Tailwind 4 + PWA), dùng ZingMP3 API + Gemini server-side. App chạy tại /preview/voxbeat/, remote path là D:\AI Orchestrator\workspace\projects\voxbeat.
- **2026-07-29** [tsk-0022]: Repo VoxBeat clone thành công vào D:\AI Orchestrator\workspace\projects\voxbeat, branch main. Đây là app nhạc Việt React + Vite + Express với ZingMP3 API, chạy live tại http://127.0.0.1:8600/preview/voxbeat/.
- **2026-07-29** [tsk-0027]: VoxBeat Music Player: Express backend (port 3000) + Vite/React frontend build → serve qua preview (port 8600). Pattern: npm install → npm run build → start server → smoke test /api/health + /preview/voxbeat/. Warning postcss @import order thường là cosmetic, không block.
- **2026-07-29** [tsk-0030]: Khi verify app, cần kiểm tra đủ 3 lớp: UI Live URL (200), API Health (200), và API Endpoints trả dữ liệu thật. CSS PostCSS warning về @import/@variant ordering là cosmetic, không block chức năng — đã biết từ tsk-0032.
- **2026-07-29** [preview-api]: Pattern bug: FE fetch('/api/...') + Live URL /preview/{slug}/ trên Orchestrator → request đập host preview, không phải Express :3000. Smoke đúng = API direct + API same-origin trên Live host. Direct OK / same-origin 404 → FAIL + hướng fix (proxy/api_base/rewrite). Stark/Banner/Hawkeye/Jarvis đều phải bắt.
- **2026-07-29** [lifecycle]: Pipeline đúng: Build → QA (Hawkeye). FAIL thì QA create_bug_ticket → Stark fix → QA lại. Chỉ khi QA PASS mới Jarvis Final Review. Jarvis không tạo bug; REJECT thì trả QA tạo ticket.
- **2026-07-29** [tsk-0037]: Khi implement caching cho dữ liệu API trong React, pattern hiệu quả là kết hợp localStorage với stale time (5 phút), hydrate đồng bộ để tránh flash skeleton, và background refetch để dữ liệu luôn mới. Cần xử lý error khi fetch mới để giữ cache cũ.
- **2026-07-30** [tsk-8153]: Đã fix skeleton loading khi re-entry bằng cách tăng stale time lên 30 phút, thêm in-memory cache và hasEverLoaded flag trong useCachedHomeData.ts.
