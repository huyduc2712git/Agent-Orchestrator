# Cách Xây Dựng Một AI Orchestrator (Kiểu Jarvis)

Tài liệu này tổng hợp từ hai nguồn:
1. **Bằng chứng thực tế** — log task `jts-0001` (Jtshop Account Dashboard), cho thấy hệ thống multi-agent này *đã* vận hành thế nào trong thực tế. Log gốc lưu tại [`docs/evidence/jts-0001-task-log.md`](evidence/jts-0001-task-log.md).
2. **Mô tả cơ chế** — 6 phase do bạn cung cấp, mô tả *cách Jarvis nghĩ và ra quyết định* ở từng bước.

Ghép hai cái lại, đây là bản thiết kế đầy đủ để build một orchestrator AI tương tự.

---

## 1. Orchestrator là gì trong hệ thống này?

Jarvis **không phải agent thực thi** — nó là **chat orchestrator**: một AI đứng giữa bạn (người giao việc) và các agent chuyên môn (Stark = build, Banner = API/backend, Hawkeye = QA, Pepper = quản lý/report, Heimdall = giám sát hạ tầng/môi trường).

Bằng chứng từ log thực tế:
- Task được giao với mô tả chi tiết → **Stark** build, không phải Jarvis.
- **Pepper** là người assign QA và tổng hợp báo cáo cuối, không code.
- **Hawkeye** chỉ làm QA — chụp ảnh, diff Figma, verify CSS, không sửa code.
- **Heimdall** chỉ cảnh báo hạ tầng (dev environment chưa đăng ký), không chặn việc, không tự sửa.
- **Jarvis xuất hiện ở đầu và cuối** — review cuối cùng, tổng hợp evidence chain, đóng task.

→ Vậy: **Orchestrator = bộ não điều phối + trí nhớ dài hạn + người ra quyết định phân công**, còn agent = tay chân chuyên môn.

---

## 2. Các thành phần bắt buộc phải có

Để build được một orchestrator như Jarvis, hệ thống cần các thành phần sau (suy ra từ cả log thực tế lẫn 6 phase):

| Thành phần | Vai trò | Bằng chứng / căn cứ |
|---|---|---|
| **Kênh nhận task** | Chat UI, Telegram, tạo task trực tiếp trên board | Phase 1 |
| **Bộ nhớ dài hạn (Memory)** | Lưu quyết định, pattern, bài học (`MEMORY.md`) | Phase 2, Phase 6 |
| **Wiki nội bộ** | Lưu architecture, connections, conventions, feature docs | Phase 2, Phase 6 (`connections.md`, `features/{slug}.md`) |
| **Bộ phân tích & lập kế hoạch** | Đọc task, quyết định nhỏ/lớn, chia subtask, gắn dependency | Phase 2 |
| **Registry agent chuyên môn** | Danh sách agent + chuyên môn (Stark=UI, Banner=API, Hawkeye=QA...) | Log thực tế + Phase 3 |
| **Hệ thống task/subtask có dependency** | Task chain kiểu `blocked_on`, ví dụ Hawkeye bị block bởi Stark+Banner | Phase 2, Phase 3 |
| **Giám sát môi trường (env manager)** | Kiểm tra dev environment đã đăng ký chưa trước khi cho QA chạy | Log thực tế (Heimdall), lệnh `ab env register` |
| **Daemon theo dõi trạng thái** | Tự động bắt sự kiện đổi status (`in_progress`, `blocked`, `review`, `done`) và push update | Phase 4 |
| **Cơ chế thông báo định kỳ (Board Patrol)** | Quét board mỗi X giờ, gửi digest nếu có task cần người thật xử lý | Phase 4 |
| **QA / verification pipeline** | Screenshot, diff, kiểm tra từng acceptance criteria | Log thực tế (Hawkeye), Phase 5 |
| **Bug ticket system tách biệt** | Không parse bug tự động từ text — phải tạo ticket chính thức có evidence | Log thực tế (`ab task create --type bug`) |
| **Review gate có phân loại** | Task thường → agent review; task nhạy cảm (DB migration, security, deploy) → operator review (con người duyệt) | Log thực tế + Phase 5 |
| **State machine enforce bởi hệ thống** | Chuyển trạng thái sai bị tự động normalize (vd: `review` → `testing` khi project chỉ cho operator review) — không dựa vào agent tự giác | Log thực tế (Heimdall normalize status của Hawkeye) |
| **Cơ chế tự-cấm approve** | Orchestrator không được tự duyệt task do chính nó tạo/làm | Phase 5 |

---

## 3. Luồng vận hành đầy đủ (kết hợp 6 phase + evidence)

### Phase 1 — Tiếp nhận
- Nhận task qua chat/Telegram/board.
- Đọc yêu cầu, check wiki + memory để hiểu context có sẵn.
- Nếu có `--source: direct_chat` → lưu session ID để tự động push update sau này.
- Chưa rõ → hỏi lại. Rõ → sang Phase 2 ngay, không delay.

### Phase 2 — Phân tích & lên kế hoạch (bước quan trọng nhất)
- **Không bao giờ code ngay.**
- Đọc toàn bộ: description, comment, attachment, docs, wiki liên quan.
- Check memory xem có pattern/bài học cũ áp dụng được không.
- Phân loại:
  - Task nhỏ, 1 bước → tự xử lý hoặc gán thẳng 1 agent.
  - Task phức tạp → chia thành **subtask chain** có dependency rõ ràng (A chờ B, C chờ A+B...).
- Trả lời người dùng ngay để họ biết đã nhận và đang xử lý — không để họ chờ trong im lặng.

### Phase 3 — Phân công / thực thi
- Task kỹ thuật → tạo subtask, gán agent đúng chuyên môn, gửi **steer message** đầy đủ context (giống mô tả task jts-0001: design reference, stack, requirement chi tiết, ràng buộc kỹ thuật).
- Trước khi agent bắt đầu: kiểm tra môi trường dev đã đăng ký chưa (nếu chưa, cảnh báo + hướng dẫn đăng ký hoặc chạy tạm thời local).
- Agent build → tạo branch `ab/{short-id}-{slug}` → code + commit → set status `testing`.
- Orchestrator **quản lý, không làm thay.**

### Phase 4 — Theo dõi (fire-and-forget)
- Không đứng chờ từng agent — nhận update qua daemon khi trạng thái đổi.
- Chỉ chủ động gửi rich update ở mốc quan trọng: sau khi lên kế hoạch, khi xong hết, khi bị block cần người can thiệp.
- Board Patrol định kỳ (2h) quét toàn bộ, gom các task cần người xử lý thành 1 digest gửi qua Telegram — tránh spam từng thông báo nhỏ lẻ.

### Phase 5 — Kiểm tra & hoàn tất
- QA agent verify theo **từng acceptance criteria cụ thể** (không chỉ "trông ổn"): screenshot, diff với reference, đo giá trị CSS thực tế, đếm console error, đếm ảnh vỡ.
- Lỗi phát hiện → **luôn tạo bug ticket riêng** kèm bằng chứng (evidence, expected vs actual, severity, repro steps) — không được tự suy diễn rồi bỏ qua.
  - Trước khi tạo: **search trước để tránh trùng lặp** (`ab search "<key symptom>"`), sau đó link bug vào task gốc bằng dependency `--type related`.
  - **Hai đường route tách biệt**: bug sản phẩm → tạo trong project đang làm, assign về Jarvis/Pepper; bug của chính nền tảng (CLI, daemon, env manager...) → route vào Default inbox, *không* assignee, chỉ tạo system notification để triage.
- Review:
  - Task thường → agent khác review.
  - Task rủi ro cao (DB migration, security, deploy production) → bắt buộc **operator review** (người thật duyệt).
  - Review gate được **enforce ở tầng hệ thống, không phụ thuộc agent tự giác**: trong log jts-0001, Hawkeye set status `review` và Heimdall tự động ép về `testing` vì project dùng chế độ agent-only review — trạng thái `review` được dành riêng cho operator. Quy trình đúng: tester post PASS evidence dạng message, rồi orchestrator complete task từ `testing`.
- Orchestrator không tự approve task của chính mình — luôn cần một bên thứ ba (agent khác hoặc người) xác nhận.
- **Closure flow đầy đủ** (theo đúng trình tự trong log): QA PASS → file các bug follow-up thành ticket → builder fix + archive bug → builder post final verification (screenshot + CSS check + trạng thái server) → orchestrator **verify độc lập lần cuối** (tự check live URL trả 200, rà lại evidence chain) → mark done. Orchestrator không đóng task chỉ dựa vào lời khai của agent.

### Phase 6 — Ghi nhớ
- Cập nhật `MEMORY.md`: quyết định đã ra, pattern đã dùng, bài học rút ra.
- Cập nhật wiki: port mới → `connections.md`; feature mới → `features/{slug}.md`.
- Mục tiêu: lần sau agent nào nhận task liên quan cũng có context sẵn, không cần hỏi lại người dùng.

---

## 4. Nguyên tắc thiết kế cốt lõi (rút ra từ cả hai nguồn)

1. **Tách vai trò rạch ròi** — orchestrator điều phối, agent chuyên môn thực thi. Không để một AI vừa code vừa tự QA vừa tự duyệt.
2. **Không bao giờ hành động mù** — luôn đọc context (wiki, memory, task history) trước khi quyết định.
3. **Bằng chứng thay vì khẳng định suông** — QA phải có screenshot/số liệu cụ thể, không nói "đã test" mà không kèm gì.
4. **Bug phải thành ticket, không chôn trong comment** — để tránh mất dấu và tạo trùng lặp.
5. **Rủi ro cao → bắt buộc người thật duyệt** — orchestrator không có quyền tự quyết với việc có thể phá hệ thống (migration, security, deploy prod).
6. **Không làm phiền người dùng liên tục** — gom update theo mốc quan trọng + digest định kỳ, thay vì báo cáo từng bước nhỏ.
7. **Ghi nhớ để không lặp lại câu hỏi** — mọi quyết định/pattern đều được lưu lại có cấu trúc (memory + wiki), không dựa vào trí nhớ ngữ cảnh của một phiên chat.

---

## 5. Gợi ý các khối cần code khi triển khai thực tế

- **Task/Board API**: CRUD task, subtask, dependency graph, status transitions.
- **Agent registry**: mapping tên agent ↔ chuyên môn ↔ prompt/persona riêng.
- **Memory store**: file hoặc DB dạng key-value/markdown, có thể search được (semantic hoặc keyword).
- **Wiki store**: markdown theo cấu trúc thư mục cố định (`architecture/`, `connections.md`, `features/`).
- **Notification daemon**: subscribe theo status change event → gửi Telegram/chat message.
- **Cron job "Board Patrol"**: chạy định kỳ, query task ở trạng thái `blocked`/`review`/`done`, gộp thành digest.
- **Bug ticket CLI/API**: enforce schema bắt buộc (title, description, repro-steps, severity, tags) — không cho tạo bug từ regex-parse tự động. Có bước search-trước-khi-tạo để chống trùng lặp, và hỗ trợ 2 route: bug sản phẩm (vào project, có assignee) vs bug nền tảng (vào Default inbox, không assignee).
- **Review gate config**: mapping loại task (theo tag: `db-migration`, `security`, `deploy-prod`...) → `review_type: operator` bắt buộc.
- **Status transition guard**: middleware ở tầng board API chặn/normalize các chuyển trạng thái không hợp lệ theo config của project (vd: agent không được set `review` khi project ở chế độ agent-only review), kèm message giải thích để agent tự sửa hành vi.
