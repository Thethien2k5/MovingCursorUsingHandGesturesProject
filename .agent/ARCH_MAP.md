# ARCH_MAP - BẢN ĐỒ KIẾN TRÚC HỆ THỐNG

> **Mục đích:** Tài liệu sống đóng vai trò là nguồn sự thật duy nhất cho bối cảnh kỹ thuật của dự án. AI phải đọc trước mỗi tác vụ lập trình và cập nhật ngay sau đó.

---

## 1. Tổng quan Công nghệ (Tech Stack)

- **Ngôn ngữ/Framework:** Python 3 – thuần Python, không dùng framework web.
- **Thị giác máy tính:** OpenCV (`opencv-python >= 4.8.0`) – đọc luồng camera, xử lý khung hình BGR, lật ngang tạo hiệu ứng gương, vẽ khung xương bàn tay.
- **Theo dõi bàn tay:** MediaPipe Tasks API (`mediapipe >= 0.10.30`) – dùng HandLandmarker, tự động tải mô hình, trích xuất 21 điểm mốc.
- **Điều khiển chuột:** PyAutoGUI (`pyautogui >= 0.9.54`) – di chuyển, click trái/phải, click đúp, nhấn giữ/thả chuột (mouseDown/Up), cuộn.
- **Xử lý tín hiệu:** Bộ lọc One Euro (tự triển khai) – làm mượt tọa độ, giảm rung lắc.
- **Tính toán:** NumPy, Math (thư viện chuẩn).
- **Đa luồng:** `threading.Thread` + `queue.Queue` – tách biệt luồng camera và luồng điều khiển.

---

## 2. Bản đồ Thư mục & Trách nhiệm

- `src/`: Thư mục gốc mã nguồn chính.
  - `main.py`: **Điểm vào ứng dụng.** Điều phối hai luồng (Camera + Điều khiển Chuột), cấu hình logging, xử lý tín hiệu dừng. Vẽ khung xương bàn tay lên khung hình camera.
  - `core/`: Các module lõi của engine.
    - `hand_tracker.py`: Bao bọc MediaPipe Tasks API (HandLandmarker), tự động tải mô hình, trích xuất 21 điểm mốc, chuyển đổi tọa độ chuẩn hóa → tọa độ khung hình camera.
    - `gesture_engine.py`: **Nhận dạng cử chỉ nâng cao.** Phát hiện 5 loại cử chỉ: dừng chương trình, kéo thả, rê chuột, click trái/đúp (qua chụm/thả ngón), click phải. Dùng máy trạng thái pinch, phát hiện ngón duỗi/co qua tỉ lệ khoảng cách, debounce và chống click liên tục.
    - `mouse_controller.py`: Điều khiển chuột hệ thống qua PyAutoGUI. Triển khai ROI động, bộ lọc One Euro, sửa lỗi đảo ngược trục X (lật `1 - x_normalized`). Hỗ trợ: `move_mouse`, `click_left`, `double_click`, `click_right`, `mouse_down`, `mouse_up`, `release_all`, `scroll`.
  - `utils/`: Tiện ích (hiện tại để trống, sẵn sàng mở rộng).
- `.agent/`: Thư mục chứa tài liệu kiến trúc cho AI (`ARCH_MAP.md`).
- `requirements.txt`: Danh sách các gói Python phụ thuộc.

---

## 3. Các Thực thể Dữ liệu Cốt lõi

- **HandTrackerResult:** `{ "detected": bool, "landmarks": list[tuple[int,int]] | None, "handedness": str | None, "confidence": float }`
  - Kết quả đầu ra của `HandTracker.process_frame()`. Mảng `landmarks` gồm 21 tuple (x, y) trong không gian khung hình camera (pixel), đã qua lật gương.

- **GestureResult (mới):** `{ "mode": GestureMode, "left_click": bool, "double_click": bool, "right_click": bool, "stop": bool, "scroll": dict }`
  - Kết quả đầu ra của `GestureEngine.detect_gestures()`. 
  - `mode` thuộc enum `GestureMode`: `NONE`, `HOVER` (rê chuột), `DRAG` (kéo thả), `STOP` (dừng).
  - Các sự kiện click được phát hiện qua máy trạng thái pinch (chụm/thả ngón cái + trỏ).

- **GestureMode (Enum):** `NONE | HOVER | DRAG | STOP`
  - `NONE`: Không có bàn tay.
  - `HOVER`: Rê chuột bình thường, không nhấn nút nào.
  - `DRAG`: Nắm đấm → giữ chuột trái, di chuyển để kéo thả.
  - `STOP`: 5 ngón duỗi → dừng chương trình ngay.

- **QueueMessage:** `{ "timestamp": float, "frame": np.ndarray, "hand_result": HandTrackerResult }`
  - `frame` là khung hình đã lật gương và đã vẽ khung xương bàn tay.

- **OneEuroFilter:** `{ "freq": float, "mincutoff": float, "beta": float, "dcutoff": float }`
  - Bộ lọc thích ứng cho tín hiệu tọa độ X/Y. Tham số mặc định: `freq=120Hz`, `mincutoff=1.0Hz`, `beta=0.5`, `dcutoff=1.0Hz`.

- **Cấu hình ROI:** `{ "roi_width_ratio": 0.4, "roi_height_ratio": 0.4 }`
  - Vùng quan tâm chiếm 40% khung hình camera, làm neo di chuyển chuột.

---

## 4. Luồng Dữ liệu Quan trọng

### Luồng Chính (Runtime)

```
┌──────────────────────────────────────────┐
│   CameraThread (Daemon)                  │
│  - Đọc khung hình từ camera              │
│  - Lật ngang (cv2.flip) tạo hiệu ứng gương│
│  - Chạy HandTracker.process()            │
│  - Vẽ khung xương bàn tay (nếu phát hiện) │
│  - Đẩy kết quả vào Queue (max 5)         │
│  - Ghi FPS mỗi 30 khung                  │
└─────────────────┬────────────────────────┘
                  │
              Queue (maxsize=5)
                  │
┌─────────────────▼────────────────────────┐
│  MouseControlThread (Main)               │
│  - Lấy dữ liệu từ Queue                  │
│  - Nếu không có tay: release_all() chuột │
│  - Chạy GestureEngine.detect()           │
│  - Xử lý chế độ:                         │
│    • DRAG mới → mouse_down()             │
│    • Thoát DRAG → mouse_up()             │
│    • STOP → dừng luồng                   │
│  - Gọi MouseController:                  │
│    • move_mouse() + OneEuro + lật X      │
│    • click_left / double_click           │
│    • click_right / scroll                │
│  - Ghi thống kê mỗi 100 khung            │
└──────────────────────────────────────────┘
```

### Luồng Nhận dạng Cử chỉ (mới)

1. `GestureEngine.detect_gestures(landmarks)` nhận 21 điểm mốc.
2. **Xác định ngón duỗi/co:** So sánh tỉ lệ `dist(tip, wrist) / dist(pip, wrist)`. Nếu > `FINGER_EXTEND_RATIO` (0.88) → duỗi.
3. **Dừng chương trình:** 5 ngón duỗi liên tiếp 5 khung hình → `mode=STOP, stop=True`.
4. **Kéo thả:** 0 ngón duỗi (nắm đấm) → `mode=DRAG`. Khi chuyển sang DRAG: `mouse_down()`; khi rời DRAG: `mouse_up()`.
5. **Rê chuột:** Ngón cái + trỏ duỗi, các ngón khác co → `mode=HOVER`.
6. **Click trái/đúp:** Trong chế độ HOVER, máy trạng thái pinch phát hiện chụm (<40px) rồi thả (>55px):
   - 2 lần thả trong 0.4s → click đúp.
   - Sau click đúp, khóa 1.0s để tránh click liên tục.
   - Debounce cơ bản 0.25s.
7. **Click phải:** Ngón trỏ duỗi, ngón cái và các ngón khác co → `right_click=True` (debounce 0.5s).

### Luồng Điều khiển Chuột (đã cập nhật)

1. Tọa độ ngón trỏ → giới hạn trong ROI (40% khung hình trung tâm).
2. Chuẩn hóa về 0-1 → **Lật trục X**: `x_screen = (1 - x_normalized) * screen_width` để khắc phục đảo ngược trái-phải do camera không gương.
3. Áp dụng bộ lọc One Euro trên từng trục X, Y (nếu bật `smoothing_enabled`).
4. Gọi `pyautogui.moveTo()` với tọa độ đã lọc.
5. Khi không phát hiện bàn tay: gọi `release_all()` để thả mọi nút chuột đang giữ.

---

## 5. Quy ước & Ràng buộc

- **Ngôn ngữ:** Tất cả chú thích và giải thích trong mã nguồn phải bằng **Tiếng Việt**. Tên biến, hàm, lớp giữ nguyên tiếng Anh.
- **Xử lý Lỗi:** Mọi thao tác với phần cứng (camera, chuột) được bọc trong `try-except`. Dọn dẹp tài nguyên trong khối `finally`.
- **Logging:** Sử dụng module `logging` với định dạng `timestamp - thread - module - level - message`. Xuất ra cả console và file `ai_mouse_core.log`.
- **Đa luồng:** Giao tiếp giữa các luồng CHỈ qua `queue.Queue` (thread-safe). Cờ `running` dùng để dừng luồng một cách nhẹ nhàng.
- **Hiệu năng:** Queue giới hạn 5 phần tử để tránh tràn bộ nhớ. Timeout 1 giây khi đọc queue. FPS camera ghi nhận mỗi 30 khung, thống kê mỗi 100 khung.
- **An toàn Chuột:** `pyautogui.FAILSAFE = False` để tránh thoát ứng dụng khi chuột chạm góc màn hình.
- **Vẽ khung xương:** CameraThread vẽ đường nối xanh lá từ cổ tay đến từng đầu ngón, chấm vàng tại khớp, chấm đỏ tại đầu ngón.

---

## 6. Nhật ký Thay đổi & Lộ trình

- `[2026-05-09]` - `[Tái cấu trúc]`: **Đại tu hệ thống cử chỉ.** Viết lại `gesture_engine.py`: thêm `GestureMode` enum, phát hiện 5 ngón duỗi → dừng chương trình, nắm đấm → kéo thả, ngón cái+trỏ → rê chuột, chụm/thả ngón → click trái/đúp (máy trạng thái pinch, debounce 0.25s, cửa sổ click đúp 0.4s, cooldown 1.0s), ngón trỏ đơn → click phải. Cập nhật `mouse_controller.py`: thêm `mouse_down()`, `mouse_up()`, `double_click()`, `release_all()`; sửa lỗi đảo ngược trái-phải bằng cách lật `x_screen = (1 - x_normalized) * screen_width`. Cập nhật `main.py`: lật ngang khung hình camera (`cv2.flip`), vẽ khung xương bàn tay (đường nối xanh, chấm khớp vàng, đầu ngón đỏ), xử lý chuyển đổi chế độ DRAG (mouse_down/up), xử lý tín hiệu STOP, thả chuột khi bàn tay rời camera.
- `[2026-05-09]` - `[Sửa lỗi]`: Chuyển từ API `mp.solutions` sang MediaPipe Tasks API (HandLandmarker) do mediapipe>=0.10.30 đã loại bỏ solutions; thêm tự động tải mô hình hand_landmarker.task; dùng `mp.Image` để tránh lỗi `_image_ptr`; sửa ánh xạ tọa độ (dùng kích thước khung hình camera thay vì kích thước màn hình) để khắc phục lỗi chuột nhảy về góc dưới trái; cập nhật requirements.txt lên `mediapipe>=0.10.30`.
- `[2026-05-08]` - `[Khởi tạo]`: AI thực hiện quét toàn bộ dự án, dịch tất cả comment sang tiếng Việt, và tạo bản đồ hệ thống.
- `[2026-05-06]` - `[Khởi tạo]`: Hoàn thành triển khai 5 giai đoạn của engine (theo IMPLEMENTATION_SUMMARY.md).
