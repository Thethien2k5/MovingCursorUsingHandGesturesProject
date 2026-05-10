"""
Trạng thái dùng chung thread-safe giữa các luồng Camera, Mouse Control, và Web Server.
Dùng threading.Lock để bảo vệ dữ liệu khỏi race condition khi đọc/ghi từ nhiều luồng.
"""

import threading
import time
from typing import Dict, List, Optional, Tuple


class SharedState:
    """
    Lưu trữ trạng thái mới nhất từ camera và điều khiển chuột.
    Web server đọc từ đây để stream video + trạng thái cho frontend.

    Tất cả các phương thức đều thread-safe nhờ khóa _lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # ── Dữ liệu khung hình ──────────────────────────────────────
        self._latest_frame_bytes: Optional[bytes] = None  # JPEG bytes của frame mới nhất (đã vẽ khung xương)
        self._frame_timestamp: float = 0.0

        # ── Dữ liệu phát hiện bàn tay ───────────────────────────────
        self._hand_detected: bool = False
        self._hand_landmarks: Optional[List[Tuple[int, int]]] = None  # 21 điểm mốc
        self._handedness: Optional[str] = None  # "Left" hoặc "Right"
        self._hand_confidence: float = 0.0

        # ── Dữ liệu cử chỉ / trạng thái điều khiển ─────────────────
        self._current_mode: str = "NONE"  # Tên chế độ hiện tại (NONE, HOVER, SCROLL, STOP)
        self._last_gesture: Optional[str] = None  # Cử chỉ gần nhất: "Click Trái", "Click Phải", "Click Đúp", "Cuộn Lên", "Cuộn Xuống"
        self._last_gesture_time: float = 0.0
        self._fist_hold: bool = False  # Có đang nắm tay (đứng yên) không
        self._scroll_active: bool = False  # Có đang ở chế độ cuộn không

        # ── Thống kê ────────────────────────────────────────────────
        self._fps_camera: float = 0.0
        self._fps_control: float = 0.0
        self._detection_rate: float = 0.0  # Tỉ lệ phát hiện bàn tay (%)

        # ── Nguồn camera ───────────────────────────────────────────
        self._camera_source: str = "0"           # "0" = laptop, URL = điện thoại
        self._camera_source_label: str = "Laptop" # Nhãn hiển thị nguồn hiện tại
        self._pending_camera_source: Optional[str] = None   # Nguồn mới được yêu cầu
        self._pending_camera_label: Optional[str] = None    # Nhãn của nguồn mới

    # ──────────────────────────────────────────────────────────────────
    # PHƯƠNG THỨC GHI (dùng bởi CameraThread và MouseControlThread)
    # ──────────────────────────────────────────────────────────────────

    def update_frame(self, jpeg_bytes: bytes, timestamp: float) -> None:
        """Cập nhật frame JPEG mới nhất từ camera."""
        with self._lock:
            self._latest_frame_bytes = jpeg_bytes
            self._frame_timestamp = timestamp

    def update_hand_data(
        self,
        detected: bool,
        landmarks: Optional[List[Tuple[int, int]]] = None,
        handedness: Optional[str] = None,
        confidence: float = 0.0,
    ) -> None:
        """Cập nhật dữ liệu phát hiện bàn tay."""
        with self._lock:
            self._hand_detected = detected
            self._hand_landmarks = landmarks
            self._handedness = handedness
            self._hand_confidence = confidence

    def update_gesture_status(
        self,
        mode: str = "NONE",
        last_gesture: Optional[str] = None,
        fist_hold: bool = False,
        scroll_active: bool = False,
    ) -> None:
        """Cập nhật trạng thái cử chỉ hiện tại."""
        with self._lock:
            self._current_mode = mode
            self._fist_hold = fist_hold
            self._scroll_active = scroll_active
            if last_gesture:
                self._last_gesture = last_gesture
                self._last_gesture_time = time.time()

    def update_stats(self, fps_camera: float = 0.0, fps_control: float = 0.0, detection_rate: float = 0.0) -> None:
        """Cập nhật thống kê FPS và tỉ lệ phát hiện."""
        with self._lock:
            if fps_camera > 0:
                self._fps_camera = fps_camera
            if fps_control > 0:
                self._fps_control = fps_control
            if detection_rate > 0:
                self._detection_rate = detection_rate

    # ── Quản lý nguồn camera ──────────────────────────────────────

    def request_camera_switch(self, source: str, label: str) -> None:
        """
        Yêu cầu CameraThread chuyển sang nguồn camera mới.
        CameraThread sẽ kiểm tra và thực hiện chuyển đổi trong vòng lặp chính.

        Tham số:
            source: Chuỗi nguồn camera ("0", "1", hoặc URL HTTP)
            label: Nhãn hiển thị cho frontend ("Laptop", "Điện thoại", ...)
        """
        with self._lock:
            self._pending_camera_source = source
            self._pending_camera_label = label

    def fetch_pending_camera_source(self) -> Optional[Tuple[str, str]]:
        """
        Lấy nguồn camera đang chờ chuyển đổi (nếu có) và xóa yêu cầu.
        Dùng bởi CameraThread để biết khi nào cần chuyển camera.

        Trả về:
            Tuple (source, label) nếu có yêu cầu chuyển đổi, ngược lại None.
        """
        with self._lock:
            if self._pending_camera_source is not None:
                source = self._pending_camera_source
                label = self._pending_camera_label
                self._pending_camera_source = None
                self._pending_camera_label = None
                return (source, label)
            return None

    def set_active_camera_source(self, source: str, label: str) -> None:
        """Cập nhật nguồn camera đang hoạt động sau khi chuyển đổi thành công."""
        with self._lock:
            self._camera_source = source
            self._camera_source_label = label

    def get_camera_source_info(self) -> Dict:
        """Lấy thông tin nguồn camera hiện tại."""
        with self._lock:
            return {
                "source": self._camera_source,
                "label": self._camera_source_label,
            }

    # ──────────────────────────────────────────────────────────────────
    # PHƯƠNG THỨC ĐỌC (dùng bởi Web Server)
    # ──────────────────────────────────────────────────────────────────

    def get_frame(self) -> Tuple[Optional[bytes], float]:
        """Lấy frame JPEG mới nhất và timestamp. Trả về (bytes, timestamp)."""
        with self._lock:
            return self._latest_frame_bytes, self._frame_timestamp

    def get_hand_data(self) -> Dict:
        """Lấy dữ liệu phát hiện bàn tay mới nhất."""
        with self._lock:
            return {
                "detected": self._hand_detected,
                "landmarks": list(self._hand_landmarks) if self._hand_landmarks else None,
                "handedness": self._handedness,
                "confidence": self._hand_confidence,
            }

    def get_gesture_status(self) -> Dict:
        """Lấy trạng thái cử chỉ + điều khiển hiện tại."""
        with self._lock:
            return {
                "mode": self._current_mode,
                "mode_label": self._mode_label(self._current_mode),
                "last_gesture": self._last_gesture,
                "last_gesture_time": self._last_gesture_time,
                "fist_hold": self._fist_hold,
                "scroll_active": self._scroll_active,
            }

    def get_full_status(self) -> Dict:
        """Lấy toàn bộ trạng thái để gửi qua WebSocket."""
        with self._lock:
            return {
                "hand": {
                    "detected": self._hand_detected,
                    "handedness": self._handedness,
                    "confidence": round(self._hand_confidence, 2),
                },
                "gesture": {
                    "mode": self._current_mode,
                    "mode_label": self._mode_label(self._current_mode),
                    "last_gesture": self._last_gesture,
                    "fist_hold": self._fist_hold,
                    "scroll_active": self._scroll_active,
                },
                "stats": {
                    "fps_camera": round(self._fps_camera, 1),
                    "fps_control": round(self._fps_control, 1),
                    "detection_rate": round(self._detection_rate, 1),
                },
                "camera": {
                    "source": self._camera_source,
                    "label": self._camera_source_label,
                },
            }

    # ──────────────────────────────────────────────────────────────────
    # TIỆN ÍCH
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _mode_label(mode: str) -> str:
        """Chuyển đổi tên mode kỹ thuật sang nhãn hiển thị tiếng Việt."""
        labels = {
            "NONE": "Không nhận diện",
            "HOVER": "Rê chuột",
            "SCROLL": "Cuộn chuột",
            "STOP": "Dừng",
        }
        return labels.get(mode, mode)


# ── Instance toàn cục ────────────────────────────────────────────────
# Được import và dùng chung bởi main.py (các luồng) và web_server.py
shared_state = SharedState()
