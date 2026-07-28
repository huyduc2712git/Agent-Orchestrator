## Figma to Static Site Builder

**Là gì:** Quy trình xây dựng trang web tĩnh (HTML/CSS/JS) chính xác từ thiết kế Figma với đầy đủ responsive, BEM methodology và interactive effects.

**Files:**
- `index.html` — HTML structure dùng BEM, font Be Vietnam Pro
- `styles.css` — CSS dùng variables, responsive 3 breakpoints
- `script.js` — 11 hiệu ứng tương tác + localStorage persist

**Cách chạy:** Khởi động local server, truy cập `http://127.0.0.1:8600/preview/[project-name]/`

**Pattern:**
1. Nhận Figma link → analyze design tokens (color, font, spacing)
2. Build HTML với BEM class naming
3. CSS variables cho maintainability
4. JS interactions + localStorage cho state persistence
5. QA verify: file check + HTTP 200 + screenshot 3 viewports
6. Final review approve