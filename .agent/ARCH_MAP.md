# BẢN ĐỒ KIẾN TRÚC - AI Virtual Mouse

> **Dự án:** Điều khiển chuột máy tính bằng cử chỉ bàn tay qua webcam.
> **Ngày cập nhật:** 2026-05-10
> **Phiên bản kiến trúc:** 2.0 (Web)

---

## 1. TỔNG QUAN

Dự án chuyển đổi từ hiển thị cửa sổ OpenCV desktop sang giao diện web, với backend Python xử lý toàn bộ logic nhận dạng cử chỉ và điều khiển chuột, frontend HTML/CSS/JS hiển thị video stream và trạng thái theo thời gian thực.

**Nguyên tắc cốt lõi:** Backend luôn chạy độc lập, frontend web là tùy chọn. Nếu không mở được trình duyệt, hệ thống vẫn hoạt động bình thường với camera laptop mặc định.

---

## 2. CÂY THƯ MỤC

```
MovingCursorUsingHandGesturesProject/
├── .agent/                      # Tài liệu kiến trúc
│   └── ARCH_MAP.md              # File này
├── frontend/                    # Giao diện web (FE)
│   └── index.html               # Trang chính: video + trạng thái + hướng dẫn
├── src/                         # Backend Python
│   ├── main.py                  # Điểm vào chính, khởi động các luồng + web server
│   ├── shared_state.py          # Trạng thái dùng chung thread-safe
│   ├── web_server.py            # FastAPI server (MJPEG + WebSocket + static)
│   ├── core/
│   │   ├── hand_tracker.py      # Theo dõi bàn tay (MediaPipe Tasks API)
│   │   ├── gesture_engine.py    # Nhận dạng cử chỉ (click, cuộn, dừng)
│   │   ├── mouse_controller.py  # Điều khiển chuột hệ thống (PyAutoGUI)
│   │   └── models/
│   │       └── hand_landmarker.task  # Mô hình MediaPipe
│   └── utils/                   # Tiện ích (rỗng)
├── CameraMobile/                # App Android camera điện thoại (Kotlin + Compose)
│   ├── build.gradle.kts         # Cấu hình Gradle gốc
│   ├── settings.gradle.kts      # Thiết lập dự án
│   ├── gradle/libs.versions.toml # Phiên bản thư viện (CameraX 1.3.4, Compose)
│   ├── app/
│   │   ├── build.gradle.kts     # Cấu hình module app
│   │   └── src/main/
│   │       ├── AndroidManifest.xml  # Quyền CAMERA + INTERNET
│   │       └── java/com/example/cammeramobile/
│   │           ├── MainActivity.kt          # Giao diện Compose + CameraX
│   │           └── CameraStreamServer.kt    # Máy chủ TCP gửi luồng MJPEG
├── run.py                       # Lệnh duy nhất chạy toàn bộ dự án
├── requirements.txt             # Thư viện Python
└── README.md                    # Hướng dẫn sử dụng (cũ)
```

---

## 3. SƠ ĐỒ LUỒNG DỮ LIỆU

```
┌──────────────────────────────────────────────────────────┐
│                      WEB FRONTEND                         │
│  ┌──────────────┐  ┌─────────────────┐  ┌─────────────┐  │
│  │ Video Stream │  │ Gesture Status  │  │ FPS Stats   │  │
│  │ (MJPEG img)  │  │ (WebSocket JSON)│  │ (WS)        │  │
│  └──────┬───────┘  └────────┬────────┘  └──────┬──────┘  │
└─────────┼───────────────────┼──────────────────┼─────────┘
          │                   │                   │
     HTTP │/video        WS /ws/status            │
          │                   │                   │
┌─────────┼───────────────────┼───────────────────┼─────────┐
│         ▼                   ▼                   ▼          │
│                    BACKEND PYTHON                           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Web Server (FastAPI + uvicorn)                     │   │
│  │  - /video      → MJPEG stream                       │   │
│  │  - /ws/status  → WebSocket (10 lần/giây)            │   │
│  │  - /api/status → REST endpoint                      │   │
│  │  - /           → Static frontend (index.html)       │   │
│  └───────────────────────┬─────────────────────────────┘   │
│                          │ Đọc                            │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  SharedState (threading.Lock)                       │   │
│  │  - latest_frame: bytes (JPEG)                       │   │
│  │  - hand_data: (detected, landmarks, handedness)     │   │
│  │  - gesture_status: (mode, last_gesture, fist_hold)  │   │
│  │  - stats: (fps_camera, fps_control, detection_rate) │   │
│  └────┬──────────────────────────────────┬─────────────┘   │
│       │ Ghi                              │ Ghi              │
│       ▼                                  ▼                  │
│  ┌──────────────────┐        ┌──────────────────────────┐   │
│  │  CameraThread    │        │  MouseControlThread      │   │
│  │  (daemon)        │        │  (non-daemon)            │   │
│  │                  │        │                          │   │
│  │  Vòng lặp:       │ Queue  │  Vòng lặp:               │   │
│  │  1. Đọc webcam   │───────▶│  1. Lấy từ Queue         │   │
│  │  2. MediaPipe    │        │  2. Phát hiện cử chỉ     │   │
│  │  3. Vẽ khung     │        │  3. Điều khiển chuột     │   │
│  │     xương        │        │  4. Cập nhật SharedState │   │
│  │  4. Mã hóa JPEG  │        │                          │   │
│  │  5. Cập nhật     │        │  stop_event ← dừng       │   │
│  │     SharedState  │        └──────────────────────────┘   │
│  └──────────────────┘                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. THÀNH PHẦN CHI TIẾT

### 4.1 Backend (Python)

| Module                     | Vai trò                                                                                  | Thay đổi v2.0                                                                            |
| -------------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `main.py`                  | Điểm vào chính, tạo 3 luồng (camera, điều khiển, web server)                             | Đã thay `cv2.imshow` bằng mã hóa JPEG + `shared_state`; thêm luồng uvicorn; sửa sys.path |
| `shared_state.py`          | Lưu trữ thread-safe frame, dữ liệu bàn tay, trạng thái cử chỉ, thống kê                  | **Mới**                                                                                  |
| `web_server.py`            | FastAPI: MJPEG stream `/video`, WebSocket `/ws/status`, REST `/api/status`, static files | **Mới**                                                                                  |
| `core/hand_tracker.py`     | MediaPipe Tasks API – trích xuất 21 điểm mốc bàn tay                                     | Không đổi                                                                                |
| `core/gesture_engine.py`   | Nhận dạng cử chỉ: rê chuột, click trái/phải, click đúp, cuộn, dừng                       | Không đổi                                                                                |
| `core/mouse_controller.py` | Điều khiển chuột hệ thống qua PyAutoGUI + bộ lọc One Euro                                | Không đổi                                                                                |

### 4.2 Frontend (HTML/CSS/JS)

| Thành phần        | Mô tả                                                                                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Video Panel**   | Hiển thị MJPEG stream từ `/video`, tự động fallback khi mất tín hiệu                                                                                                           |
| **Status Panel**  | Card "Nhận Diện Bàn Tay" (có/không, tay trái/phải, độ tin cậy), Card "Chế Độ Hiện Tại" (Rê chuột/Cuộn/Dừng/Không nhận diện), Card "Cử Chỉ Gần Nhất" (badge tự biến mất sau 3s) |
| **Stats Grid**    | FPS Camera, FPS Điều Khiển, Tỉ Lệ Nhận Diện, Trạng Thái WebSocket                                                                                                              |
| **Gesture Guide** | Hướng dẫn 5 cử chỉ cơ bản                                                                                                                                                      |
| **WebSocket**     | Kết nối `/ws/status`, tự động reconnect mỗi 3 giây nếu mất kết nối, kiểm tra định kỳ 10 giây                                                                                   |

### 4.3 Luồng Dữ Liệu

1. **CameraThread** đọc webcam, chạy MediaPipe, vẽ khung xương, mã hóa JPEG → ghi vào `shared_state` (frame + hand data)
2. **MouseControlThread** lấy dữ liệu từ Queue, phát hiện cử chỉ, điều khiển chuột, ghi trạng thái + thống kê vào `shared_state`
3. **Web Server** (FastAPI) đọc từ `shared_state`:
   - `/video`: gửi MJPEG stream frame JPEG mới nhất
   - `/ws/status`: gửi JSON trạng thái mỗi 100ms qua WebSocket
   - `/api/status`: REST endpoint cho polling

### 4.4 Camera Điện Thoại (CameraMobile)

Dự án Android (Kotlin + Jetpack Compose + CameraX) truyền luồng MJPEG từ camera điện thoại tới PC qua USB Type-C. Đã triển khai đầy đủ.

#### Kiến trúc

- **CameraX**: Preview + ImageAnalysis (chiến lược KEEP_ONLY_LATEST)
- **CameraStreamServer**: Máy chủ TCP gửi MJPEG (multipart/x-mixed-replace) qua cổng 8080
- **MainActivity**: Giao diện Compose với PreviewView, nút chuyển camera trước/sau, chỉ báo trạng thái stream
- **Luồng dữ liệu**: CameraX ImageAnalysis → YUV-to-Bitmap → JPEG nén 85% → CameraStreamServer.broadcastFrame() → TCP socket → PC

#### Các tệp chính

| Tệp                     | Vai trò                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------- |
| `MainActivity.kt`       | Activity Compose, xin quyền camera, gắn CameraX vào PreviewView, nút chuyển camera, hiển thị trạng thái |
| `CameraStreamServer.kt` | ServerSocket lắng nghe cổng 8080, quản lý nhiều client, gửi MJPEG stream (HTTP header + boundary)       |
| `libs.versions.toml`    | Khai báo phiên bản CameraX 1.3.4                                                                        |
| `app/build.gradle.kts`  | Thêm camera-core, camera-camera2, camera-lifecycle, camera-view, coroutines                             |
| `AndroidManifest.xml`   | Quyền CAMERA, INTERNET; khai báo Activity                                                               |

#### Cách kết nối với PC

```bash
# 1. Bật USB Debugging trên điện thoại, cắm cáp Type-C
# 2. Forward cổng TCP từ điện thoại sang PC
adb forward tcp:8080 tcp:8080

# 3. Mở app CameraMobile trên điện thoại, chọn camera (trước/sau)
# 4. PC Python backend có thể đọc luồng MJPEG từ:
#    http://localhost:8080 (dùng cv2.VideoCapture hoặc requests)
```

---

## 5. CÁCH CHẠY

```bash
# Cài đặt thư viện
pip install -r requirements.txt

# Chạy toàn bộ dự án (BE + FE)
python run.py
```

- Backend tự động khởi động web server tại `http://localhost:8000`
- Trình duyệt sẽ được mở tự động; nếu thất bại, backend vẫn chạy bình thường
- Dừng chương trình: duỗi 5 ngón tay hoặc nhấn `Ctrl+C`

---

## 6. NHẬT KÝ THAY ĐỔI

- `[2026-05-10]` - `[Thêm]` **Chuyển đổi sang giao diện web**: Thêm `shared_state.py`, `web_server.py`, `frontend/index.html`; sửa `main.py` để thay `cv2.imshow` bằng web server; thêm `run.py` để khởi chạy một lệnh duy nhất; cập nhật `requirements.txt` với FastAPI + uvicorn. Logic lõi (hand_tracker, gesture_engine, mouse_controller) không thay đổi.
- `[2026-05-10]` - `[Thêm]` **CameraMobile Android**: Cấu hình dự án Kotlin + Compose + CameraX; viết MainActivity (giao diện, chuyển camera trước/sau) và CameraStreamServer (máy chủ TCP MJPEG cổng 8080); cập nhật build.gradle, libs.versions.toml, AndroidManifest.xml. Cho phép truyền camera điện thoại qua USB Type-C tới PC backend.
- `[2026-05-10]` - `[Thêm]` **Chọn nguồn camera trên web**: Thêm quản lý nguồn camera vào `shared_state.py` (request_camera_switch, fetch_pending_camera_source); thêm API `POST /api/switch-camera` vào `web_server.py`; sửa `CameraThread` trong `main.py` để hỗ trợ chuyển đổi động giữa camera laptop và điện thoại (qua URL HTTP); thêm dropdown chọn camera (Laptop / Điện thoại) vào `frontend/index.html` kèm JavaScript gọi API và đồng bộ trạng thái qua WebSocket.
- `[Trước 2026-05-10]` - Phiên bản 1.0: Kiến trúc desktop với `cv2.imshow` và multi-threading (CameraThread + MouseControlThread).

---

_Được duy trì bởi: Giao thức Kiến trúc sư AI v1.0_
