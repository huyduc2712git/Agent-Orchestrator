---
name: mobile-visual-qa-emulation
description: Multi-device mobile viewport emulation & visual QA checklist for Heiji & Haibara — testing safe areas, keyboard overlays, font scaling, and mockup pixel comparisons.
source: vendor
runAs: inline
invocation: auto
allowed-tools: [read_file, write_file, edit_file, list_dir, search_files, run_command, http_get, post_message, run_skill]
agents: [heiji, haibara, conan]
---

# Mobile Multi-Device Visual QA & Emulation Guide

Khi Agent **Heiji** và **Haibara** thực hiện kiểm thử chất lượng giao diện ứng dụng Mobile (Visual QA), tuân thủ quy trình sau:

---

## 1. Thiết lập Cấu hình Giả lập Thiết bị (Device Viewport Presets)

Sử dụng Playwright hoặc Browser Emulation với các kích thước tiêu chuẩn:

| Preset ID | Kích thước Viewport | Tỷ lệ Scale | Mục đích kiểm thử |
|---|---|---|---|
| `iphone-15-pro` | `393 × 852` | 3.0 | Màn hình tiêu chuẩn iOS có Dynamic Island & Safe Area đáy 34px |
| `iphone-se` | `375 × 667` | 2.0 | Màn hình nhỏ (Compact) — kiểm tra tràn chữ, tràn nút |
| `pixel-7-android` | `412 × 915` | 2.625 | Màn hình Android tiêu chuẩn có thanh điều hướng ảo |
| `ipad-mini` | `744 × 1133` | 2.0 | Tablet — kiểm tra bố cục mở rộng (Grid/Columns) |

---

## 2. Tiêu chí Đánh giá Chất lượng (Visual QA Checklist)

1. **Kiểm tra Vùng an toàn (Safe Area Check)**:
   - Header không bị chèn bởi Status Bar hoặc Dynamic Island.
   - Nút hành động đáy (Sticky CTA / Bottom Bar) cách mép dưới tối thiểu `34px` trên iPhone có Home Indicator.

2. **Kiểm tra Bàn phím ảo & Form (Keyboard Overlay Check)**:
   - Khi focus vào `TextInput`, màn hình tự động cuộn đẩy input lên trên bàn phím.
   - Nút Submit/Tiếp tục không bị bàn phím che lấp.

3. **Kiểm tra Tương thích Font chữ Hệ thống (Dynamic Type Check)**:
   - Thử nghiệm tăng kích thước font lên 120% / 150%:
     * Chữ không bị cắt cụt (`...`) ở các tiêu đề quan trọng.
     * Nút bấm tự động mở rộng chiều cao theo nội dung chữ bên trong.

4. **So sánh với Mockup Thiết kế (Pixel Diff Comparison)**:
   - Sử dụng tool `diff_images` để so sánh ảnh chụp màn hình giả lập `desktop-top.png` / `mobile-top.png` với file mockup thiết kế gốc trong `assets/user-uploads/`.
   - Báo cáo chỉ số tương đồng (Similarity Score) và phân tích các điểm lệch bố cục (nếu có).

---

## 3. Báo cáo Kết quả (Visual QA Verdict)

Báo cáo nghiệm thu của Heiji phải nêu rõ:
- Tình trạng hiển thị trên từng Viewport (`iPhone 15 Pro`, `iPhone SE`, `Android`).
- Danh sách ảnh chụp màn hình artifacts và ảnh so sánh diff.
- Kết luận: **PASS** ✅ hoặc **FAIL** ❌ kèm danh sách bug cụ thể để Kid sửa chữa.
