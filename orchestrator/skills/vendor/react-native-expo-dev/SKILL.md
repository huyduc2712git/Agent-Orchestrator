---
name: react-native-expo-dev
description: React Native & Expo mobile development guidelines — Expo Router file-based navigation, Native Device APIs, offline SQLite/MMKV storage, and Expo Web preview.
source: vendor
runAs: inline
invocation: auto
allowed-tools: [read_file, write_file, edit_file, list_dir, search_files, run_command, http_get, post_message, run_skill]
agents: [kid, agasa, conan]
---

# React Native & Expo Development Standards

Khi phát triển ứng dụng di động với **React Native / Expo**, Agent tuân thủ các quy chuẩn kiến trúc sau:

---

## 1. Cấu trúc Thư mục & Điều hướng (Expo Router & Navigation)

1. **File-based Routing (Expo Router v3 / v4)**:
   ```
   app/
   ├── (tabs)/
   │   ├── _layout.tsx      # Bottom Tab Bar Navigation
   │   ├── index.tsx        # Home Screen
   │   ├── explore.tsx      # Explore / Search Screen
   │   └── profile.tsx      # User Profile Screen
   ├── (auth)/
   │   ├── login.tsx        # Login Screen
   │   └── register.tsx     # Register Screen
   ├── modal.tsx            # Full-screen / Sheet Modal
   └── _layout.tsx          # Root Stack & Theme Providers
   ```

2. **Quy chuẩn Navigation**:
   - Sử dụng `Stack` cho các màn hình phân cấp sâu (Drill-down screens).
   - Sử dụng `Tabs` cho các phân hệ tính năng chính (3–5 tabs tối đa).
   - Sử dụng `Modal` hoặc `@gorhom/bottom-sheet` cho các hành động ngữ cảnh ngắn (Filter, Share, Quick actions).

---

## 2. Tích hợp Native Device APIs

- **Haptics Feedback (`expo-haptics`)**: Kích hoạt rung nhẹ khi người dùng nhấn nút quan trọng, hoàn thành hành động (Success), hoặc kéo Refresh (Pull-to-refresh).
- **Camera & Image Picker (`expo-image-picker`)**: Xử lý quyền truy cập rõ ràng, nén ảnh trước khi upload.
- **Offline Detection (`@react-native-community/netinfo`)**: Tự động thông báo và chuyển sang chế độ Offline mượt mà khi mất kết nối mạng.
- **Biometrics (`expo-local-authentication`)**: Hỗ trợ đăng nhập nhanh bằng FaceID / TouchID / Vân tay.

---

## 3. Lưu trữ Dữ liệu Offline-First (Local Storage & State)

1. **Key-Value Store**:
   - Sử dụng `react-native-mmkv` cho cấu hình người dùng, theme, cờ trạng thái (nhanh hơn AsyncStorage 30x).
2. **Cơ sở dữ liệu Quan hệ Cục bộ**:
   - Sử dụng `expo-sqlite` hoặc `WatermelonDB` cho các ứng dụng có lượng dữ liệu lớn cần tìm kiếm offline (Offline-First sync).
3. **Quản lý State Toàn cục**:
   - Sử dụng `Zustand` cho UI state gọn nhẹ.
   - Sử dụng `@tanstack/react-query` cho server state với cơ chế tự động cache, revalidate và optimistic UI updates.

---

## 4. Live Web Preview & Kiểm thử

- Chạy lệnh: `npx expo start --web` hoặc cấu hình bundler Vite/Metro để phục vụ Live URL trên Orchestrator (`/preview/<project>/`).
- Đảm bảo code tương thích đa nền tảng (iOS, Android và Mobile Web preview).
