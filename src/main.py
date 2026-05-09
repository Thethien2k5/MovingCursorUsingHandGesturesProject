"""
Engine Lõi Chuột Ảo AI - Vòng lặp Chính.
Kiến trúc đa luồng: Luồng Camera + Luồng điều khiển Chuột.
"""

import io
import logging
import sys
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Dict, Optional

import cv2

# Sửa lỗi mã hóa Unicode trên Windows console (cp1252 không hỗ trợ tiếng Việt)
# Mở lại stdout/stderr với encoding UTF-8 rõ ràng, tránh dùng stream cũ
if sys.platform == 'win32':
    sys.stdout = open(sys.stdout.fileno(), 'w', encoding='utf-8', errors='replace', closefd=False)
    sys.stderr = open(sys.stderr.fileno(), 'w', encoding='utf-8', errors='replace', closefd=False)

# Thêm src vào đường dẫn
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.hand_tracker import HandTracker
from core.gesture_engine import GestureEngine
from core.mouse_controller import MouseController

# Định cấu hình ghi nhật ký với định dạng chi tiết
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ai_mouse_core.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class CameraThread(threading.Thread):
    """
    Luồng chuyên dụng để đọc khung hình camera và theo dõi bàn tay.
    Đưa dữ liệu bàn tay đã xử lý vào hàng đợi cho luồng chính.
    """

    def __init__(self, queue: Queue, camera_index: int = 0) -> None:
        """
        Khởi tạo luồng camera.

        Tham số:
            queue: Hàng đợi để đẩy kết quả theo dõi bàn tay vào
            camera_index: Chỉ số thiết bị camera (thường là 0 cho mặc định)
        """
        super().__init__(daemon=True, name="CameraThread")
        self.queue = queue
        self.camera_index = camera_index
        self.running = False

    def run(self) -> None:
        """Vòng lặp chính của luồng camera."""
        logger.info(f"Đang khởi động luồng camera (chỉ_số_thiết_bị: {self.camera_index})")

        cap = None
        tracker = None

        try:
            # Khởi tạo camera
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                logger.error(f"Không mở được camera {self.camera_index}")
                return

            # Đặt thuộc tính camera để tối ưu hiệu năng
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_FPS, 30)

            # Khởi tạo bộ theo dõi bàn tay
            tracker = HandTracker(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7,
                screen_width=1920,
                screen_height=1080,
            )

            self.running = True
            frame_count = 0
            start_time = time.time()

            logger.info("Luồng camera đang chạy. Nhấn 'q' trong cửa sổ camera để dừng.")

            while self.running:
                ret, frame = cap.read()
                if not ret:
                    logger.warning("Không đọc được khung hình từ camera")
                    continue

                # Xử lý khung hình bằng bộ theo dõi bàn tay
                result = tracker.process_frame(frame)

                # Đẩy kết quả vào hàng đợi
                self.queue.put(
                    {
                        "timestamp": time.time(),
                        "frame": frame,
                        "hand_result": result,
                    }
                )

                frame_count += 1

                # Ghi nhật ký FPS mỗi 30 khung hình
                if frame_count % 30 == 0:
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed
                    logger.info(f"FPS camera: {fps:.2f}")

                # Kiểm tra phím 'q' để dừng (nếu hiển thị cửa sổ)
                # Bỏ chú thích để gỡ lỗi với hiển thị cửa sổ
                cv2.imshow("Hand Tracker", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    self.running = False

        except Exception as e:
            logger.error(f"Lỗi trong luồng camera: {e}")
        finally:
            self.running = False
            if tracker:
                tracker.close()
            if cap:
                cap.release()
            cv2.destroyAllWindows()
            logger.info("Đã dừng luồng camera")


class MouseControlThread(threading.Thread):
    """
    Luồng chính để phát hiện cử chỉ và điều khiển chuột.
    Tiêu thụ dữ liệu theo dõi bàn tay từ hàng đợi và thực thi lệnh chuột.
    """

    def __init__(self, queue: Queue) -> None:
        """
        Khởi tạo luồng điều khiển chuột.

        Tham số:
            queue: Hàng đợi để nhận kết quả theo dõi bàn tay
        """
        super().__init__(name="MouseControlThread")
        self.queue = queue
        self.running = False

    def run(self) -> None:
        """Vòng lặp chính của luồng điều khiển chuột."""
        logger.info("Đang khởi động luồng điều khiển chuột")

        gesture_engine = GestureEngine()
        mouse_controller = MouseController(
            screen_width=1920,
            screen_height=1080,
            roi_width_ratio=0.4,
            roi_height_ratio=0.4,
            smoothing_enabled=True,
        )

        self.running = True
        frame_count = 0
        hand_detected_count = 0
        start_time = time.time()

        try:
            while self.running:
                # Lấy kết quả theo dõi bàn tay từ hàng đợi (không chặn, timeout 1 giây)
                try:
                    data = self.queue.get(timeout=1.0)
                except:
                    # Timeout - không có dữ liệu, tiếp tục chờ
                    continue

                timestamp = data["timestamp"]
                frame = data["frame"]
                hand_result = data["hand_result"]

                frame_count += 1

                if hand_result["detected"]:
                    hand_detected_count += 1

                    # Trích xuất các điểm mốc
                    landmarks = hand_result["landmarks"]

                    # Đặt kích thước camera cho bộ điều khiển chuột ở lần phát hiện đầu tiên
                    if mouse_controller.camera_width is None:
                        h, w = frame.shape[:2]
                        mouse_controller.set_camera_dimensions(w, h)

                    # Lấy đầu ngón trỏ (điểm mốc 8)
                    index_tip = landmarks[8]

                    # Di chuyển chuột đến vị trí ngón trỏ
                    mouse_controller.move_mouse(index_tip, timestamp)

                    # Phát hiện cử chỉ
                    gesture_result = gesture_engine.detect_gestures(landmarks)

                    # Thực thi lệnh chuột dựa trên cử chỉ
                    mouse_controller.execute_gesture(gesture_result)

                    # Ghi nhật ký các cử chỉ được phát hiện
                    if gesture_result["left_click"]:
                        logger.info("Cử chỉ: Click Trái")
                    if gesture_result["right_click"]:
                        logger.info("Cử chỉ: Click Phải")
                    if gesture_result["scroll"]["direction"]:
                        logger.info(f"Cử chỉ: Cuộn {gesture_result['scroll']['direction']}")

                # Ghi nhật ký thống kê mỗi 100 khung hình
                if frame_count % 100 == 0:
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed
                    detection_rate = (hand_detected_count / frame_count * 100) if frame_count > 0 else 0
                    logger.info(
                        f"Vòng điều khiển - FPS: {fps:.2f}, Tỉ lệ phát hiện bàn tay: {detection_rate:.1f}%"
                    )

        except KeyboardInterrupt:
            logger.info("Luồng điều khiển chuột bị người dùng ngắt")
        except Exception as e:
            logger.error(f"Lỗi trong luồng điều khiển chuột: {e}")
        finally:
            self.running = False
            logger.info("Đã dừng luồng điều khiển chuột")


def main() -> int:
    """
    Hàm chính điều phối Engine Lõi Chuột Ảo AI.

    Trả về:
        Mã thoát (0 cho thành công, 1 cho thất bại)
    """
    logger.info("=== Khởi động Engine Lõi Chuột Ảo AI ===")

    # Tạo hàng đợi để giao tiếp giữa các luồng
    hand_data_queue: Queue = Queue(maxsize=5)

    # Tạo và khởi động luồng camera
    camera_thread = CameraThread(hand_data_queue, camera_index=0)
    camera_thread.start()

    # Cho luồng camera thời gian để khởi tạo
    time.sleep(1)

    # Tạo và khởi động luồng điều khiển chuột
    control_thread = MouseControlThread(hand_data_queue)
    control_thread.start()

    try:
        logger.info("Engine lõi đang chạy. Nhấn Ctrl+C để dừng.")
        # Giữ luồng chính tồn tại
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Đã nhận tín hiệu tắt")
    finally:
        # Dừng các luồng một cách nhẹ nhàng
        camera_thread.running = False
        control_thread.running = False

        # Chờ các luồng kết thúc (có timeout)
        camera_thread.join(timeout=5)
        control_thread.join(timeout=5)

        logger.info("=== Đã dừng Engine Lõi Chuột Ảo AI ===")

    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
