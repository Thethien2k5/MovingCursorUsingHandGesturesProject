# ARCH_MAP - BẢN ĐỒ KIẾN TRÚC HỆ THỐNG

> **Mục đích:** Tài liệu sống đóng vai trò là nguồn sự thật duy nhất cho bối cảnh kỹ thuật của dự án. AI phải đọc trước mỗi tác vụ lập trình và cập nhật ngay sau đó.

---

## 1. Tổng quan Công nghệ (Tech Stack)

- **Ngôn ngữ/Framework:** Python 3 – thuần Python, không dùng framework web.
- **Thị giác máy tính:** OpenCV (`opencv-python >= 4.8.0`) – đọc luồng camera, xử lý khung hình BGR, lật ngang tạo hiệu ứng gương, vẽ khung xương bàn tay.
- **Theo dõi bàn tay:** MediaPipe Tasks API (`mediapipe >= 0.10.30`) – dùng HandLandmarker, tự động tải mô hình, trích xuất 21 điểm mốc.
- **Điều khiển chuột:** PyAutoGUI (`pyautogui >= 0.9.54`) – di chuyển, click trái, click đúp, cuộn.
- **Xử lý tín hiệu:** Bộ lọc One Euro (tự triển khai) – làm mượt tọa độ, giảm rung lắc.
- **Tính toán:** NumPy, Math (thư viện chuẩn).
- **Đa luồng:** `threading.Thread` + `queue.Queue` – tách biệt luồng camera và luồng điều khiển.

---

## 2. Bản đồ Thư mục & Trách nhiệm

- `src/`: Thư mục gốc mã nguồn chính.
  - `main.py`: **Điểm vào ứng dụng.** Điều phối hai luồng (Camera + Điều khiển Chuột), cấu hình logging, xử lý tín hiệu dừng. Vẽ khung xương bàn tay lên khung hình camera.
  - `core/`: Các module lõi của engine.
    - `hand_tracker.py`: Bao bọc MediaPipe Tasks API (HandLandmarker), tự động tải mô hình, trích xuất 21 điểm mốc, chuyển đổi tọa độ chuẩn hóa → tọa độ khung hình camera.
    - `gesture_engine.py`: **Nhận dạng cử chỉ nâng cao.** Phát hiện cử chỉ: dừng chương trình, rê chuột (1 ngón trỏ duỗi), click trái/đúp qua co/duỗi nhanh ngón trỏ hoặc ngón cái, nắm tay (đứng yên), cuộn chuột (nắm tay giữ 2 giây).
    - `mouse_controller.py`: Điều khiển chuột hệ thống qua PyAutoGUI. Triển khai ROI động, bộ lọc One Euro.
  - `utils/`: Tiện ích (hiện tại để trống, sẵn sàng mở rộng).
- `.agent/`: Thư mục chứa tài liệu kiến trúc cho AI (`ARCH_MAP.md`).
- `requirements.txt`: Danh sách các gói Python phụ thuộc.

---

## 3. Các Thực thể Dữ liệu Cốt lõi

- **HandTrackerResult:** `{ "detected": bool, "landmarks": list[tuple[int,int]] | None, "handedness": str | None, "confidence": float }`
  - Kết quả đầu ra của `HandTracker.process_frame()`. Mảng `landmarks` gồm 21 tuple (x, y) trong không gian khung hình camera (pixel), đã qua lật gương.

- **GestureResult:** `{ "mode": GestureMode, "left_click": bool, "double_click": bool, "right_click": bool, "stop": bool, "scroll": dict, "fist_hold": bool }`
  - Kết quả đầu ra của `GestureEngine.detect_gestures()`.
  - `mode` thuộc enum `GestureMode`: `NONE`, `HOVER` (rê chuột), `SCROLL` (cuộn), `STOP` (dừng).
  - `fist_hold`: True khi 5 ngón co (chưa đủ 2 giây) → chuột đứng yên.
  - Click trái/đúp được phát hiện qua co/duỗi nhanh ngón trỏ hoặc ngón cái.

- **GestureMode (Enum):** `NONE | HOVER | SCROLL | STOP`
  - `NONE`: Không có bàn tay.
  - `HOVER`: Rê chuột bình thường, con trỏ di chuyển theo lòng bàn tay.
  - `SCROLL`: Nắm đấm giữ 2 giây → cuộn chuột giữa (tay lên = cuộn xuống, tay xuống = cuộn lên).
  - `STOP`: 5 ngón duỗi → dừng chương trình ngay.

- **QueueMessage:** `{ "timestamp": float, "frame": np.ndarray, "hand_result": HandTrackerResult }`
  - `frame` là khung hình đã lật gương và đã vẽ khung xương bàn tay.

- **OneEuroFilter:** `{ "freq": 120Hz, "mincutoff": 1.0Hz, "beta": 0.5, "dcutoff": 1.0Hz }`
  - Bộ lọc thích ứng cho tín hiệu tọa độ X/Y.

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
│  - Nếu không có tay: release_all()       │
│  - Chạy GestureEngine.detect()           │
│  - Xử lý chế độ:                         │
│    • fist_hold → không di chuyển chuột   │
│    • SCROLL → cuộn chuột theo delta Y    │
│    • STOP → dừng luồng                   │
│  - Gọi MouseController:                  │
│    • move_mouse() + OneEuro              │
│    • click_left / double_click           │
│    • scroll                              │
│  - Ghi thống kê mỗi 100 khung            │
└──────────────────────────────────────────┘
```

### Luồng Nhận dạng Cử chỉ

1. **Xác định ngón duỗi/co:** Tỉ lệ `dist(tip, wrist) / dist(pip, wrist) > 0.70` + kiểm tra trục Y (tip_y < pip_y) → duỗi. Ngón cái co khi khoảng cách đến INDEX_MCP < 70px.
2. **Dừng chương trình:** 5 ngón duỗi liên tiếp 5 khung hình → `mode=STOP, stop=True`.
3. **Nắm tay – Đứng yên:** 0 ngón duỗi → `fist_hold=True`, chuột không di chuyển. Giữ 2 giây → `mode=SCROLL`, cuộn chuột giữa.
4. **Rê chuột:** Khi có bàn tay và không thuộc các trường hợp trên → `mode=HOVER`, chuột di chuyển theo lòng bàn tay.
5. **Click trái (cách 1):** Ngón trỏ đang duỗi → co → duỗi trong vòng 0.4s → `left_click=True`. Hai lần liên tục trong 0.4s → `double_click=True`.
6. **Click trái (cách 2):** Khi ngón trỏ duỗi, ngón cái co → duỗi → co trong 0.4s → `left_click=True`.
7. **Debounce click:** 0.25s giữa các click đơn; cooldown 1.0s sau click đúp.

### Luồng Điều khiển Chuột

1. Tọa độ lòng bàn tay (midpoint cổ tay – khớp ngón giữa) → giới hạn trong ROI.
2. Chuẩn hóa về 0-1 → ánh xạ sang tọa độ màn hình (`x_screen = x_normalized * screen_width`).
3. Áp dụng bộ lọc One Euro để làm mượt.
4. Gọi `pyautogui.moveTo()` (chỉ khi không ở chế độ SCROLL hoặc fist_hold).
5. Khi không phát hiện bàn tay: gọi `release_all()` để thả mọi nút chuột.

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

- `[2026-05-10]` - `[Tái cấu trúc]`: **Thay đổi hoàn toàn cách nhận diện cử chỉ.** Xóa pinch-to-click, thêm click qua co/duỗi nhanh ngón trỏ (extend → curl → extend) và ngón cái (curl → extend → curl). Nắm tay (0 ngón duỗi) lập tức dừng di chuyển chuột; giữ 2 giây → cuộn chuột giữa. Chế độ rê chuột mặc định khi có bàn tay. Cập nhật `gesture_engine.py` với máy trạng thái mới, `main.py` xóa log chuột phải, cập nhật `ARCH_MAP.md`.
- `[2026-05-09]` - `[Tái cấu trúc]`: **Đại tu hệ thống cử chỉ lần 1.** Viết lại `gesture_engine.py`: thêm `GestureMode` enum, phát hiện dừng, kéo thả, rê chuột, pinch-click, click phải. Cập nhật `mouse_controller.py` (mouse_down/up, double_click), `main.py` (flip camera, vẽ skeleton).
- `[2026-05-09]` - `[Sửa lỗi]`: Chuyển từ API `mp.solutions` sang MediaPipe Tasks API (HandLandmarker); tự động tải mô hình; sửa lỗi `_image_ptr`; sửa ánh xạ tọa độ.
- `[2026-05-08]` - `[Khởi tạo]`: AI quét dự án, dịch comment sang tiếng Việt, tạo bản đồ hệ thống.
- `[2026-05-06]` - `[Khởi tạo]`: Hoàn thành triển khai 5 giai đoạn của engine.
