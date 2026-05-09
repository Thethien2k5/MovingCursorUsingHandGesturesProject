"""
Mô-đun theo dõi bàn tay sử dụng MediaPipe Tasks API (mới).
Chịu trách nhiệm trích xuất các điểm mốc bàn tay từ khung hình camera.
Đã chuyển từ API cũ (mp.solutions) sang API mới (HandLandmarker) vì mediapipe>=0.10.30 đã loại bỏ solutions.
"""

import logging
import cv2
import numpy as np
import time
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple, List

from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
import mediapipe as mp

# Cấu hình logging
logger = logging.getLogger(__name__)

# URL tải mô hình Hand Landmarker (phiên bản float16, nhỏ hơn)
_HAND_LANDMARKER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)


class HandTracker:
    """
    Bao bọc MediaPipe HandLandmarker (Tasks API) để trích xuất và xử lý các điểm mốc bàn tay.
    Chuyển đổi tọa độ điểm mốc sang không gian màn hình.
    """

    def __init__(
        self,
        static_image_mode: bool = False,
        max_num_hands: int = 1,
        min_detection_confidence: float = 0.7,
        min_tracking_confidence: float = 0.7,
        screen_width: int = 1920,
        screen_height: int = 1080,
    ) -> None:
        """
        Khởi tạo HandTracker với cấu hình MediaPipe Tasks API.

        Tham số:
            static_image_mode: Nếu True, dùng chế độ IMAGE; False dùng VIDEO.
            max_num_hands: Số lượng bàn tay tối đa cần phát hiện.
            min_detection_confidence: Ngưỡng tin cậy tối thiểu cho phát hiện bàn tay.
            min_tracking_confidence: Ngưỡng tin cậy tối thiểu cho theo dõi bàn tay.
            screen_width: Chiều rộng của màn hình đích để chia tỷ lệ tọa độ.
            screen_height: Chiều cao của màn hình đích để chia tỷ lệ tọa độ.
        """
        self.screen_width = screen_width
        self.screen_height = screen_height

        # Lưu kích thước khung hình để chuyển đổi tọa độ
        self.frame_width: Optional[int] = None
        self.frame_height: Optional[int] = None

        # Bộ đếm khung hình và thời gian cho API dạng VIDEO
        self._frame_counter: int = 0
        self._start_time: float = time.time()

        # Tải mô hình nếu cần, rồi khởi tạo HandLandmarker
        model_path = self._get_model_path()
        base_options = BaseOptions(model_asset_path=model_path)
        running_mode = RunningMode.IMAGE if static_image_mode else RunningMode.VIDEO

        options = HandLandmarkerOptions(
            base_options=base_options,
            running_mode=running_mode,
            num_hands=max_num_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self.landmarker = HandLandmarker.create_from_options(options)

        logger.info(
            f"Khởi tạo HandTracker (Tasks API): số_bàn_tay_tối_đa={max_num_hands}, "
            f"ngưỡng_phát_hiện={min_detection_confidence}, "
            f"ngưỡng_theo_dõi={min_tracking_confidence}, "
            f"chế_độ={'IMAGE' if static_image_mode else 'VIDEO'}"
        )

    def _get_model_path(self) -> str:
        """
        Trả về đường dẫn tệp mô hình hand_landmarker.task.
        Tự động tải về từ Google Storage nếu chưa có.
        """
        model_dir = Path(__file__).parent / "models"
        model_dir.mkdir(exist_ok=True)
        model_path = model_dir / "hand_landmarker.task"

        if not model_path.exists():
            logger.info("Đang tải mô hình MediaPipe Hand Landmarker (khoảng 15MB)...")
            try:
                urllib.request.urlretrieve(_HAND_LANDMARKER_MODEL_URL, model_path)
                logger.info(f"Đã tải mô hình vào: {model_path}")
            except Exception as e:
                logger.error(f"Không thể tải mô hình: {e}")
                raise RuntimeError(
                    f"Không thể tải mô hình Hand Landmarker. "
                    f"Hãy tải thủ công từ:\n{_HAND_LANDMARKER_MODEL_URL}\n"
                    f"và đặt vào: {model_path}"
                )

        return str(model_path)

    def process_frame(self, frame: np.ndarray) -> Dict[str, any]:
        """
        Xử lý một khung hình từ camera và trích xuất các điểm mốc bàn tay.

        Tham số:
            frame: Khung hình BGR từ camera OpenCV (H, W, 3)

        Trả về:
            Từ điển chứa:
                - 'detected': bool, liệu có phát hiện thấy bàn tay không
                - 'landmarks': Danh sách 21 điểm mốc (tuple (x,y)) nếu phát hiện, ngược lại None
                - 'handedness': 'Left' hoặc 'Right', ngược lại None
                - 'confidence': float trong khoảng 0 đến 1
        """
        if frame is None:
            logger.error("Nhận khung hình None")
            return {
                "detected": False,
                "landmarks": None,
                "handedness": None,
                "confidence": 0.0,
            }

        # Lưu kích thước khung hình nếu chưa được lưu
        if self.frame_height is None or self.frame_width is None:
            self.frame_height, self.frame_width = frame.shape[:2]
            logger.debug(f"Kích thước khung hình: {self.frame_width}x{self.frame_height}")

        # Chuyển đổi BGR sang RGB cho MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Tạo MediaPipe Image từ numpy array (bắt buộc với Tasks API để tránh lỗi _image_ptr)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        # Xử lý khung hình với HandLandmarker (Tasks API)
        # Tính timestamp dạng mili giây cho VIDEO mode
        timestamp_ms = int((time.time() - self._start_time) * 1000)

        try:
            result = self.landmarker.detect_for_video(mp_image, timestamp_ms)
        except Exception as e:
            logger.error(f"Lỗi khi phát hiện bàn tay: {e}")
            return {
                "detected": False,
                "landmarks": None,
                "handedness": None,
                "confidence": 0.0,
            }

        # Kiểm tra kết quả
        if result.hand_landmarks and len(result.hand_landmarks) > 0:
            # Trích xuất bàn tay đầu tiên (chỉ theo dõi 1 bàn tay)
            hand_landmarks_list: List = result.hand_landmarks[0]
            handedness_label: str = result.handedness[0][0].category_name
            confidence_score: float = result.handedness[0][0].score

            # Chuyển đổi điểm mốc sang tọa độ khung hình camera
            landmarks = self._landmarks_to_frame_coords(hand_landmarks_list)

            logger.debug(
                f"Phát hiện bàn tay: {handedness_label}, độ tin cậy={confidence_score:.2f}, "
                f"số điểm mốc={len(landmarks)}"
            )

            return {
                "detected": True,
                "landmarks": landmarks,
                "handedness": handedness_label,
                "confidence": float(confidence_score),
            }
        else:
            return {
                "detected": False,
                "landmarks": None,
                "handedness": None,
                "confidence": 0.0,
            }

    def _landmarks_to_frame_coords(
        self,
        hand_landmarks: List,
    ) -> List[Tuple[int, int]]:
        """
        Chuyển đổi danh sách NormalizedLandmark (có thuộc tính x, y) sang tọa độ khung hình camera.

        Tham số:
            hand_landmarks: Danh sách 21 NormalizedLandmark từ kết quả HandLandmarker

        Trả về:
            Danh sách 21 tuple (x, y) trong hệ tọa độ khung hình camera (pixel)
        """
        landmarks = []
        for lm in hand_landmarks:
            # Chia tỷ lệ tọa độ chuẩn hóa (0-1) sang kích thước khung hình camera
            x = int(lm.x * self.frame_width)
            y = int(lm.y * self.frame_height)
            landmarks.append((x, y))

        return landmarks

    def get_landmark_by_id(self, landmarks: list, landmark_id: int) -> Optional[Tuple[int, int]]:
        """
        Lấy một điểm mốc cụ thể theo ID của nó.

        Tham số:
            landmarks: Danh sách 21 điểm mốc
            landmark_id: ID của điểm mốc (0-20)

        Trả về:
            Tuple tọa độ (x, y) hoặc None nếu ID không hợp lệ
        """
        if not landmarks or landmark_id < 0 or landmark_id >= len(landmarks):
            return None
        return landmarks[landmark_id]

    def close(self) -> None:
        """Dọn dẹp tài nguyên."""
        if hasattr(self, 'landmarker') and self.landmarker:
            self.landmarker.close()
            logger.info("Đã đóng HandTracker")


# ID các điểm mốc bàn tay MediaPipe để tham khảo:
# 0: Cổ tay
# 1-4: Ngón cái (gốc, giữa, xa, đầu)
# 5-8: Ngón trỏ (gốc, giữa, xa, đầu)
# 9-12: Ngón giữa (gốc, giữa, xa, đầu)
# 13-16: Ngón áp út (gốc, giữa, xa, đầu)
# 17-20: Ngón út (gốc, giữa, xa, đầu)
