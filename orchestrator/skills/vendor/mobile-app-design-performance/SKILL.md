---
name: mobile-app-design-performance
description: Mobile UI/UX ergonomics (touch targets, safe areas, thumb zone) & 60fps performance optimization for React Native, Expo, Flutter, and Mobile Web.
source: vendor
runAs: inline
invocation: auto
allowed-tools: [read_file, write_file, edit_file, list_dir, search_files, run_command, http_get, post_message, run_skill]
agents: [kid, heiji, haibara, conan]
---

# Mobile App Design & 60fps Performance Optimization Guide

Khi xây dựng giao diện ứng dụng di động (React Native / Expo / Flutter / Mobile Web), Agent **BẮT BUỘC** tuân thủ các nguyên tắc sau:

---

## 1. Công thái học Di động (Touch Ergonomics & Thumb Zone)

1. **Kích thước vùng chạm tối thiểu (Touch Targets)**:
   - Tất cả nút bấm, icon button, input, thẻ bấm được phải đạt tối thiểu **≥ 44×44 pt (iOS)** hoặc **≥ 48×48 dp (Android)**.
   - Đối với icon nhỏ hơn 44px (ví dụ icon 20×20px), sử dụng `hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}` hoặc padding bao quanh để mở rộng diện tích chạm.

2. **Bố cục Vùng ngón cái (Thumb Zone)**:
   - Đặt các nút hành động chính (Primary CTA, Buy, Submit, Floating Action Button), thanh điều hướng Bottom Navigation Bar hoặc Bottom Sheet ở **1/3 dưới màn hình** — nơi ngón tay cái người dùng dễ tiếp cận nhất khi cầm máy 1 tay.
   - Các hành động phá hủy / ít dùng (Delete, Settings phụ) có thể đặt ở góc trên.

3. **Safe Area Insets (Tai thỏ, Dynamic Island, Home Bar)**:
   - Luôn sử dụng `SafeAreaProvider` và `useSafeAreaInsets()` (từ `react-native-safe-area-context`) hoặc `env(safe-area-inset-top)` / `env(safe-area-inset-bottom)`.
   - Tuyệt đối không để nội dung text hoặc nút bấm bị đè bởi Notch (tai thỏ), Dynamic Island phía trên hoặc thanh gạt Home Indicator phía đáy màn hình.

4. **Xử lý Bàn phím ảo (Keyboard Handling)**:
   - Sử dụng `KeyboardAvoidingView` (với `behavior={Platform.OS === 'ios' ? 'padding' : 'height'}`) cho các màn hình có Form đăng ký / đăng nhập / chat.
   - Bọc form trong `ScrollView` với `keyboardShouldPersistTaps="handled"` để không bị che khuất ô nhập liệu khi bàn phím bật lên.

---

## 2. Tối ưu Hiệu năng 60fps / 120fps (Mobile Performance)

1. **Danh sách cuộn mượt (Virtualized Lists)**:
   - Tránh dùng `ScrollView` cho danh sách có nhiều hơn 20 items.
   - Sử dụng `@shopify/flash-list` hoặc `FlatList` tối ưu:
     * Cung cấp `estimatedItemSize` (cho FlashList) hoặc `getItemLayout` (cho FlatList).
     * Thiết lập `windowSize={5}`, `maxToRenderPerBatch={10}`, `initialNumToRender={8}`, `removeClippedSubviews={true}`.
     * Tránh inline arrow functions trong `renderItem` (dùng `useCallback` hoặc component con độc lập).

2. **Xử lý Hình ảnh & Asset (Image Optimization)**:
   - Dùng `expo-image` hoặc `react-native-fast-image` thay vì thẻ `Image` mặc định.
   - Bật memory & disk caching, định dạng ảnh hiện đại (WebP), nén kích thước ảnh tương ứng với màn hình hiển thị.
   - Sử dụng Skeleton placeholder trong khi ảnh đang tải để tránh giật layout (Layout Shift).

3. **Giảm thiểu Re-render không cần thiết**:
   - Sử dụng `React.memo` cho các List Item và Card Components.
   - Lưu trữ callback và giá trị tính toán bằng `useCallback`, `useMemo`.
   - Các animation chuyển động (vuốt, trượt, fade) phải chạy trên Native UI Thread qua `react-native-reanimated` (`useSharedValue`, worklets) hoặc `useNativeDriver: true`.

4. **Thời gian Khởi động & Bộ nhớ (Startup & Memory)**:
   - Kích hoạt Hermes JavaScript Engine.
   - Lazy load các màn hình sâu trong stack navigation để giảm thời gian tải ban đầu (Cold Start time).

---

## 3. Checklist Nghiệm thu Mobile UI (Kid, Heiji, Haibara)

- [ ] Vùng chạm tất cả nút bấm và icon đều ≥ 44×44 pt / dp.
- [ ] Safe Area Insets chuẩn trên cả màn hình có tai thỏ và Dynamic Island.
- [ ] Bàn phím ảo bật lên không che ô nhập liệu hoặc nút gửi.
- [ ] Danh sách cuộn mượt mà ở 60fps không bị giật khung hình (frame drop).
- [ ] Hỗ trợ hiển thị chuẩn Dark Mode và Light Mode.
- [ ] Text không bị vỡ hoặc cắt khi người dùng bật phóng to cỡ chữ hệ thống (Dynamic Type).
