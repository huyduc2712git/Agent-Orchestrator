## Feature: Figma to Static Web Implementation

**Mô tả:** Xây dựng trang web tĩnh (HTML/CSS/JS) chính xác từ thiết kế Figma, đảm bảo layout, màu sắc, font, kích thước và tương tác.

**Files:**
- `index.html`
- `styles.css`
- `script.js`

**Cách chạy:**
- Mở trực tiếp `index.html` trong trình duyệt.
- Hoặc truy cập live preview tại: `http://127.0.0.1:8600/preview/jtshop-figma-v2/`

**Đặc điểm kỹ thuật:**
- Sử dụng BEM naming convention, không inline style.
- CSS lấy tông màu trực tiếp từ Figma (`#f00633`, `#0c0c0c`, `#ff424e`, `#565564`, `#e7e7e9`, `#1162ff`...).
- Font: Be Vietnam Pro.
- Responsive 3 breakpoints (mobile, tablet, desktop).
- JS tích hợp 11 hiệu ứng tương tác: modal, toggle, loading, voucher, qty, scroll, cập nhật tổng tiền, v.v.
- Đã được QA (Hawkeye) và verify độc lập approve.