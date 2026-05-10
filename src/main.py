"""
Engine Lõi Chuột Ảo AI - Vòng lặp Chính.
Kiến trúc đa luồng: Luồng Camera + Luồng điều khiển Chuột.
Hỗ trợ nhận dạng cử chỉ: rê chuột, cuộn chuột, click trái/phải, click đúp, dừng.
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
import numpy as np

# Sửa lỗi mã hóa Unicode trên Windows console (cp1252 không hỗ trợ tiếng Việt)
# Mở lại stdout/stderr với encoding UTF-8
if sys.platform == 'win32':
    sys.stdout = open(sys.stdout.fileno(), 'w', encoding='utf-8', errors='replace', closefd=False)
    sys.stderr = open(sys.stderr.fileno(), 'w', encoding='utf-8', errors='replace', closefd=False)

# Thêm src vào đường dẫn
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.hand_tracker import HandTracker
from core.gesture_engine import GestureEngine, GestureMode
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

# ── Hằng số vẽ khung xương bàn tay ─────────────────────────────────────
# Màu sắc BGR cho các đường nối
SKELETON_COLOR = (0, 255, 0)        # Xanh lá - đường nối chính
JOINT_COLOR = (0, 200, 200)         # Vàng - chấm khớp
FINGERTIP_COLOR = (0, 0, 255)       # Đỏ - đầu ngón tay
LINE_THICKNESS = 2
CIRCLE_RADIUS = 4
FINGERTIP_RADIUS = 6

# Các kết nối ngón tay: từ cổ tay 0 -> các đầu ngón tay 4 8 12 16 20
FINGER_CONNECTIONS = [
    [0, 1, 2, 3, 4],     # Ngón cái
    [0, 5, 6, 7, 8],     # Ngón trỏ
    [0, 9, 10, 11, 12],  # Ngón giữa
    [0, 13, 14, 15, 16], # Ngón áp út
    [0, 17, 18, 19, 20], # Ngón út
]


class CameraThread(threading.Thread):
    """
    Luồng chuyên dụng để đọc khung hình camera và theo dõi bàn tay.
    Đưa dữ liệu bàn tay đã xử lý vào hàng đợi cho luồng chính.
    Lật ngang khung hình để tạo hiệu ứng gương tự nhiên.
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
        ### ======= CAMERA ======= ###
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

            while self.running:
                ret, frame = cap.read()
                if not ret:
                    logger.warning("Không đọc được khung hình từ camera")
                    continue

                # ── Lật ngang khung hình để tạo hiệu ứng gương ──────────
                # Camera thường cho ảnh không gương, gây đảo ngược trái-phải.
                # Lật khung hình giúp di chuyển tay tự nhiên hơn.
                frame = cv2.flip(frame, 1)

                # Xử lý khung hình bằng bộ theo dõi bàn tay
                result = tracker.process_frame(frame)

                # ── Vẽ đường nối từ cổ tay đến các ngón tay ─────────────
                display_frame = frame.copy()
                if result["detected"] and result["landmarks"]:
                    landmarks = result["landmarks"]
                    self._draw_hand_skeleton(display_frame, landmarks)

                # Đẩy kết quả vào hàng đợi (kèm frame đã vẽ để hiển thị)
                self.queue.put(
                    {
                        "timestamp": time.time(),
                        "frame": display_frame,
                        "hand_result": result,
                    }
                )

                frame_count += 1

                # Ghi nhật ký FPS mỗi 30 khung hình
                if frame_count % 30 == 0:
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed
                    logger.info(f"FPS camera: {fps:.2f}")

                # Hiển thị cửa sổ camera với khung xương đã vẽ
                cv2.imshow("Hand Tracker", display_frame)
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

    @staticmethod
    def _draw_hand_skeleton(frame: np.ndarray, landmarks: list) -> None:
        """
        Vẽ khung xương bàn tay lên khung hình: đường nối từ cổ tay đến
        từng đầu ngón tay, chấm tròn tại khớp và đầu ngón.

        Tham số:
            frame: Khung hình BGR để vẽ lên (sửa đổi trực tiếp)
            landmarks: Danh sách 21 tuple (x, y) điểm mốc
        """
        if not landmarks or len(landmarks) < 21:
            return

        # ── Vẽ đường nối cho từng ngón ─────────────────────────────────
        for finger_ids in FINGER_CONNECTIONS:
            for i in range(len(finger_ids) - 1):
                pt1 = landmarks[finger_ids[i]]
                pt2 = landmarks[finger_ids[i + 1]]
                cv2.line(frame, pt1, pt2, SKELETON_COLOR, LINE_THICKNESS)

        # ── Vẽ chấm tròn tại các khớp ──────────────────────────────────
        for i, (x, y) in enumerate(landmarks):
            if i in (4, 8, 12, 16, 20):  # Đầu ngón tay
                cv2.circle(frame, (x, y), FINGERTIP_RADIUS, FINGERTIP_COLOR, -1)
            else:
                cv2.circle(frame, (x, y), CIRCLE_RADIUS, JOINT_COLOR, -1)


class MouseControlThread(threading.Thread):
    """
    Luồng chính để phát hiện cử chỉ và điều khiển chuột.
    Tiêu thụ dữ liệu theo dõi bàn tay từ hàng đợi và thực thi lệnh chuột.
    Xử lý chuyển đổi chế độ: rê chuột, cuộn chuột, dừng chương trình.
    """

    def __init__(self, queue: Queue, stop_event: threading.Event) -> None:
        """
        Khởi tạo luồng điều khiển chuột.

        Tham số:
            queue: Hàng đợi để nhận kết quả theo dõi bàn tay
            stop_event: Sự kiện để báo hiệu dừng toàn bộ chương trình
        """
        super().__init__(name="MouseControlThread")
        self.queue = queue
        self.stop_event = stop_event
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

        # ── Theo dõi chế độ trước đó để phát hiện chuyển đổi ──────────
        prev_mode: GestureMode = GestureMode.NONE
        hand_was_detected: bool = False

        # ── Neo cho chế độ cuộn chuột (nắm đấm) ─────────────────────────
        self._scroll_base_y: float = 0.0

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

                # ────────────────────────────────────────────────────────
                # XỬ LÝ KHI KHÔNG PHÁT HIỆN BÀN TAY
                # ────────────────────────────────────────────────────────
                if not hand_result["detected"]:
                    # Khi bàn tay rời khỏi camera, thả mọi nút chuột đang giữ
                    if hand_was_detected:
                        mouse_controller.release_all()
                        logger.debug("Bàn tay rời khỏi camera - Thả toàn bộ chuột")

                    hand_was_detected = False
                    prev_mode = GestureMode.NONE

                    # Gọi detect_gestures với None để đặt lại trạng thái engine
                    gesture_engine.detect_gestures([])

                    # Ghi nhật ký thống kê mỗi 100 khung hình
                    if frame_count % 100 == 0:
                        elapsed = time.time() - start_time
                        fps = frame_count / elapsed
                        detection_rate = (hand_detected_count / frame_count * 100) if frame_count > 0 else 0
                        logger.info(
                            f"Vòng điều khiển - FPS: {fps:.2f}, Tỉ lệ phát hiện bàn tay: {detection_rate:.1f}%"
                        )
                    continue

                # ────────────────────────────────────────────────────────
                # XỬ LÝ KHI PHÁT HIỆN BÀN TAY
                # ────────────────────────────────────────────────────────
                hand_was_detected = True
                hand_detected_count += 1

                # Trích xuất các điểm mốc
                landmarks = hand_result["landmarks"]

                # Đặt kích thước camera cho bộ điều khiển chuột ở lần phát hiện đầu tiên
                if mouse_controller.camera_width is None:
                    h, w = frame.shape[:2]
                    mouse_controller.set_camera_dimensions(w, h)

                # Lấy vị trí trung tâm lòng bàn tay (trung điểm cổ tay và khớp giữa ngón giữa)
                # Dùng midpoint để tránh chuột bị kẹt ở góc khi chỉ dùng cổ tay
                wrist = landmarks[0]
                middle_mcp = landmarks[9]
                palm_center = ((wrist[0] + middle_mcp[0]) // 2,
                               (wrist[1] + middle_mcp[1]) // 2)

                # ── Phát hiện cử chỉ ───────────────────────────────────
                gesture_result = gesture_engine.detect_gestures(landmarks)
                current_mode = gesture_result["mode"]

                # ── Xử lý tín hiệu DỪNG ────────────────────────────────
                if gesture_result.get("stop"):
                    logger.info(">>> NHẬN TÍN HIỆU DỪNG TỪ CỬ CHỈ <<<")
                    # Báo hiệu dừng chương trình hoàn toàn
                    self.stop_event.set()
                    self.running = False
                    break

                # ── Xử lý chế độ CUỘN CHUỘT (nắm đấm) ─────────────────
                if current_mode == GestureMode.SCROLL:
                    # Khi mới vào chế độ cuộn, lưu vị trí Y ban đầu
                    if prev_mode != GestureMode.SCROLL:
                        self._scroll_base_y = palm_center[1]
                        logger.info("Chế độ: Cuộn chuột (nắm đấm)")
                    else:
                        # Tính delta Y so với vị trí trước đó để xác định hướng cuộn
                        delta_y = palm_center[1] - self._scroll_base_y
                        if abs(delta_y) > 5:  # Ngưỡng kích hoạt cuộn (pixel)
                            # Tay đi xuống → cuộn lên, tay đi lên → cuộn xuống
                            direction = "up" if delta_y > 0 else "down"
                            amount = max(2, int(abs(delta_y) / 10))  # 10px = 1 bước cuộn, tối thiểu 2 bước
                            mouse_controller.scroll(direction, amount)
                            self._scroll_base_y = palm_center[1]  # Cập nhật gốc
                elif prev_mode == GestureMode.SCROLL:
                    # Thoát chế độ cuộn
                    logger.info("Chế độ: Thoát cuộn chuột")

                prev_mode = current_mode

                # ── Di chuyển chuột (bám theo lòng bàn tay, đứng yên khi cuộn hoặc nắm tay) ──
                if current_mode != GestureMode.SCROLL and not gesture_result.get("fist_hold"):
                    mouse_controller.move_mouse(palm_center, timestamp)

                # ── Thực thi lệnh chuột dựa trên cử chỉ ────────────────
                mouse_controller.execute_gesture(gesture_result)

                # ── Ghi nhật ký các cử chỉ được phát hiện ──────────────
                if gesture_result.get("left_click"):
                    logger.info("Cử chỉ: Click Trái")
                if gesture_result.get("double_click"):
                    logger.info("Cử chỉ: Click Đúp")

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
            # ── Dọn dẹp: thả mọi nút chuột trước khi thoát ────────────
            try:
                mouse_controller.release_all()
            except:
                pass
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

    # Tạo stop_event để dừng chương trình hoàn toàn khi nhận cử chỉ 5 ngón duỗi
    stop_event = threading.Event()

    # Tạo và khởi động luồng camera
    camera_thread = CameraThread(hand_data_queue, camera_index=0)
    camera_thread.start()

    # Cho luồng camera thời gian để khởi tạo
    time.sleep(1)

    # Tạo và khởi động luồng điều khiển chuột
    control_thread = MouseControlThread(hand_data_queue, stop_event)
    control_thread.start()

    try:
        logger.info("Engine lõi đang chạy. Duỗi 5 ngón để dừng, hoặc nhấn Ctrl+C.")
        # Giữ luồng chính tồn tại, kiểm tra tín hiệu dừng
        while not stop_event.is_set():
            time.sleep(0.5)

        logger.info("Đã nhận tín hiệu dừng từ cử chỉ bàn tay")

    except KeyboardInterrupt:
        logger.info("Đã nhận tín hiệu tắt (Ctrl+C)")
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
