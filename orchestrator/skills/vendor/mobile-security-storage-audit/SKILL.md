---
name: mobile-security-storage-audit
description: Mobile application security audit for Akai & Amuro — verifying secure token storage (SecureStore/KeyStore/Keychain), scanning for leaked client secrets, and deep link validation.
source: vendor
runAs: inline
invocation: auto
allowed-tools: [read_file, list_dir, search_files, grep, http_get, post_message, create_bug_ticket, run_skill]
agents: [akai, amuro, conan]
---

# Mobile Application Security & Storage Audit Standards

Khi Agent **Shuichi Akai** và **Amuro** thực hiện đánh giá an ninh ứng dụng Mobile, tiến hành kiểm tra theo 4 trụ cột sau:

---

## 1. Lưu trữ Thông tin Nhạy cảm (Secure Storage Verification)

- ❌ **CẤM**: Tuyệt đối không lưu trữ Access Token, Refresh Token, mật khẩu, thông tin thẻ tín dụng hoặc PII trong `AsyncStorage` / `localStorage` thô (dữ liệu dạng plain text rất dễ bị trích xuất trên thiết bị rooted/jailbroken).
- ✅ **BẮT BUỘC**: Sử dụng các giải pháp mã hóa phần cứng an toàn:
  * `expo-secure-store`
  * `react-native-keychain` (sử dụng iOS Keychain / Android KeyStore + EncryptedSharedPreferences).

---

## 2. Quét Lộ Secrets trong Client Bundle (Secret Leak Scanner)

- Quét toàn bộ mã nguồn Client (`src/`, `app/`, `.env`):
  * Đảm bảo **KHÔNG** chứa Private API Keys (AWS Secret, Firebase Admin Key, Database Connection String, JWT Signing Secret, Payment Gateway Private Keys).
  * Tất cả các thao tác nhạy cảm phải được thực hiện qua Backend Server (Dr. Agasa) thay vì gọi trực tiếp từ Mobile Client.

---

## 3. An toàn Kết nối Mạng & API (Network & API Security)

- Luôn sử dụng giao thức **HTTPS / TLS 1.3** cho tất cả các endpoint kết nối.
- Xử lý Token hết hạn mượt mà qua cơ chế Refresh Token xoay vòng (Token Rotation) thay vì giữ token vĩnh viễn.
- Kiểm tra tính hợp lệ của Header `Authorization: Bearer <token>` trên từng request.

---

## 4. Deep Link & URL Scheme Validation

- Xác thực và làm sạch (Sanitize) tất cả tham số đầu vào từ Deep Links (`myapp://...` hoặc Universal Links `https://myapp.com/...`).
- Ngăn chặn lỗ hổng điều hướng trái phép (Open Redirect) hoặc thực thi code trái phép từ link bên ngoài.

---

## 5. Kết luận & Tạo Bug Ticket

Nếu phát hiện bất kỳ lỗ hổng nào:
1. Tạo ngay Bug Ticket qua tool `create_bug_ticket` với mức độ nghiêm trọng tương ứng (`high` hoặc `critical` cho lộ secret / lưu token không an toàn).
2. Đưa ra khuyến nghị khắc phục cụ thể cho `Kid` hoặc `Agasa`.
