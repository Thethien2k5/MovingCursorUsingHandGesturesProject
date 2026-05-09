# ARCH_MAP - BẢN ĐỒ KIẾN TRÚC HỆ THỐNG

> **Mục đích:** Tài liệu sống đóng vai trò là nguồn sự thật duy nhất cho bối cảnh kỹ thuật của dự án. AI phải đọc trước mỗi tác vụ lập trình và cập nhật ngay sau đó.

---

## 1. Tổng quan Công nghệ (Tech Stack)

- **Ngôn ngữ/Framework:** Python 3 – thuần Python, không dùng framework web.
- **Thị giác máy tính:** OpenCV (`opencv-python >= 4.8.0`) – đọc luồng camera, xử lý khung hình BGR.
- **Theo dõi bàn tay:** MediaPipe Tasks API (`mediapipe >= 0.10.30`) – dùng HandLandmarker, tự động tải mô hình, trích xuất 21 điểm mốc.
- **Điều khiển chuột:** PyAutoGUI (`pyautogui >= 0.9.54`) – di chuyển, click, cuộn chuột hệ điều hành.
- **Xử lý tín hiệu:** Bộ lọc One Euro (tự triển khai) – làm mượt tọa độ, giảm rung lắc.
- **Tính toán:** NumPy, SciPy, FilterPy (phụ trợ), Math (thư viện chuẩn).
- **Đa luồng:** `threading.Thread` + `queue.Queue` – tách biệt luồng camera và luồng điều khiển.

---

## 2. Bản đồ Thư mục & Trách nhiệm

- `src/`: Thư mục gốc mã nguồn chính.
  - `main.py`: **Điểm vào ứng dụng.** Điều phối hai luồng (Camera + Điều khiển Chuột), cấu hình logging, xử lý tín hiệu dừng.
  - `core/`: Các module lõi của engine.
    - `hand_tracker.py`: Bao bọc MediaPipe Tasks API (HandLandmarker), tự động tải mô hình, trích xuất 21 điểm mốc, chuyển đổi tọa độ chuẩn hóa → tọa độ khung hình camera.
    - `gesture_engine.py`: Nhận dạng cử chỉ (click trái/phải, cuộn) từ danh sách điểm mốc, kèm cơ chế debounce.
    - `mouse_controller.py`: Điều khiển chuột hệ thống qua PyAutoGUI, triển khai ROI động và bộ lọc One Euro làm mượt tín hiệu.
  - `utils/`: Tiện ích (hiện tại để trống, sẵn sàng mở rộng).
- `.agent/`: Thư mục chứa tài liệu kiến trúc cho AI (`ARCH_MAP.md`).
- `requirements.txt`: Danh sách các gói Python phụ thuộc.
- `test_phase2.py`: Script kiểm tra độc lập cho bộ theo dõi bàn tay (HandTracker).
- `IMPLEMENTATION_SUMMARY.md`: Tài liệu tổng quan triển khai (bằng tiếng Anh, chưa dịch).

---

## 3. Các Thực thể Dữ liệu Cốt lõi

- **HandTrackerResult:** `{ "detected": bool, "landmarks": list[tuple[int,int]] | None, "handedness": str | None, "confidence": float }`
  - Kết quả đầu ra của `HandTracker.process_frame()`. Mảng `landmarks` gồm 21 tuple (x, y) trong không gian khung hình camera (pixel).

- **GestureResult:** `{ "left_click": bool, "right_click": bool, "scroll": { "direction": str | None, "magnitude": int } }`
  - Kết quả đầu ra của `GestureEngine.detect_gestures()`. `direction` nhận giá trị `"up"`, `"down"`, hoặc `None`.

- **QueueMessage:** `{ "timestamp": float, "frame": np.ndarray, "hand_result": HandTrackerResult }`
  - Đối tượng được đẩy qua `queue.Queue` giữa luồng camera và luồng điều khiển chuột.

- **OneEuroFilter:** `{ "freq": float, "mincutoff": float, "beta": float, "dcutoff": float }`
  - Bộ lọc thích ứng cho tín hiệu tọa độ X/Y. Tham số mặc định: `freq=120Hz`, `mincutoff=1.0Hz`, `beta=0.5`, `dcutoff=1.0Hz`.

- **Cấu hình ROI:** `{ "roi_width_ratio": 0.4, "roi_height_ratio": 0.4 }`
  - Vùng quan tâm chiếm 40% khung hình camera, làm neo di chuyển chuột.

---

## 4. Luồng Dữ liệu Quan trọng

### Luồng Chính (Runtime)

```
┌─────────────────────────────────┐
│   CameraThread (Daemon)         │
│  - Đọc khung hình từ camera     │
│  - Chạy HandTracker.process()   │
│  - Đẩy kết quả vào Queue (max 5)│
│  - Ghi FPS mỗi 30 khung         │
└─────────────────┬───────────────┘
                  │
              Queue (maxsize=5)
                  │
┌─────────────────▼───────────────┐
│  MouseControlThread (Main)      │
│  - Lấy dữ liệu từ Queue         │
│  - Chạy GestureEngine.detect()  │
│  - Gọi MouseController:         │
│    • move_mouse() + OneEuro     │
│    • click_left/right()         │
│    • scroll()                   │
│  - Ghi thống kê mỗi 100 khung   │
└─────────────────────────────────┘
```

### Luồng Nhận dạng Cử chỉ

1. `GestureEngine.detect_gestures(landmarks)` nhận 21 điểm mốc → tính khoảng cách Euclid.
2. **Click Trái:** `thumb_tip ↔ index_tip < 50px` + debounce 0.3s.
3. **Click Phải:** `thumb_tip ↔ middle_tip < 50px` + debounce 0.3s.
4. **Cuộn:** Ngón trỏ & ngón giữa duỗi thẳng (độ lệch ngang < 30px). Hướng dựa trên vị trí dọc: đầu ngón cao hơn gốc → cuộn lên.

### Luồng Điều khiển Chuột

1. Tọa độ ngón trỏ → giới hạn trong ROI (40% khung hình trung tâm).
2. Chuẩn hóa về 0-1 → chia tỷ lệ ra tọa độ màn hình.
3. Áp dụng bộ lọc One Euro trên từng trục X, Y (nếu bật `smoothing_enabled`).
4. Gọi `pyautogui.moveTo()` với tọa độ đã lọc.

---

## 5. Quy ước & Ràng buộc

- **Ngôn ngữ:** Tất cả chú thích và giải thích trong mã nguồn phải bằng **Tiếng Việt**. Tên biến, hàm, lớp giữ nguyên tiếng Anh.
- **Xử lý Lỗi:** Mọi thao tác với phần cứng (camera, chuột) được bọc trong `try-except`. Dọn dẹp tài nguyên trong khối `finally`.
- **Logging:** Sử dụng module `logging` với định dạng `timestamp - thread - module - level - message`. Xuất ra cả console và file `ai_mouse_core.log`.
- **Đa luồng:** Giao tiếp giữa các luồng CHỈ qua `queue.Queue` (thread-safe). Cờ `running` dùng để dừng luồng một cách nhẹ nhàng.
- **Hiệu năng:** Queue giới hạn 5 phần tử để tránh tràn bộ nhớ. Timeout 1 giây khi đọc queue. FPS camera ghi nhận mỗi 30 khung, thống kê mỗi 100 khung.
- **An toàn Chuột:** `pyautogui.FAILSAFE = False` để tránh thoát ứng dụng khi chuột chạm góc màn hình.

---

## 6. Nhật ký Thay đổi & Lộ trình

- `[2026-05-08]` - `[Khởi tạo]`: AI thực hiện quét toàn bộ dự án, dịch tất cả comment sang tiếng Việt, và tạo bản đồ hệ thống.
- `[2026-05-06]` - `[Khởi tạo]`: Hoàn thành triển khai 5 giai đoạn của engine (theo IMPLEMENTATION_SUMMARY.md).
- `[2026-05-09]` - `[Sửa lỗi]`: Chuyển từ API `mp.solutions` sang MediaPipe Tasks API (HandLandmarker) do mediapipe>=0.10.30 đã loại bỏ solutions; thêm tự động tải mô hình hand_landmarker.task; dùng `mp.Image` để tránh lỗi `_image_ptr`; sửa ánh xạ tọa độ (dùng kích thước khung hình camera thay vì kích thước màn hình) để khắc phục lỗi chuột nhảy về góc dưới trái; cập nhật requirements.txt lên `mediapipe>=0.10.30`.
