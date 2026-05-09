"""
Engine Nhận dạng Cử chỉ.
Phát hiện cử chỉ bàn tay và chuyển đổi chúng thành các sự kiện điều khiển chuột.
"""

import logging
import math
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class GestureEngine:
    """
    Nhận dạng cử chỉ bàn tay và kích hoạt các sự kiện chuột tương ứng.
    Xử lý: Click Trái, Click Phải, phát hiện Cuộn.
    Bao gồm cơ chế debounce để ngăn kích hoạt nhiều lần.
    """

    # ID các điểm mốc để tham khảo
    WRIST = 0
    THUMB_TIP = 4
    INDEX_TIP = 8
    MIDDLE_TIP = 12
    RING_TIP = 16
    PINKY_TIP = 20
    INDEX_BASE = 5
    MIDDLE_BASE = 9

    # Ngưỡng phát hiện cử chỉ (tính bằng pixel)
    LEFT_CLICK_THRESHOLD = 50  # Khoảng cách giữa ngón cái và ngón trỏ
    RIGHT_CLICK_THRESHOLD = 50  # Khoảng cách giữa ngón cái và ngón giữa
    SCROLL_STRAIGHTNESS_THRESHOLD = 30  # Độ lệch tối đa cho các ngón tay thẳng

    # Thời gian debounce tính bằng giây
    DEBOUNCE_TIME = 0.3

    def __init__(self) -> None:
        """Khởi tạo engine nhận dạng cử chỉ."""
        self.last_left_click_time: float = 0.0
        self.last_right_click_time: float = 0.0
        self.last_scroll_time: float = 0.0
        self.last_scroll_direction: Optional[str] = None

        logger.info(
            f"Khởi tạo GestureEngine: NGƯỠNG_CLICK_TRÁI={self.LEFT_CLICK_THRESHOLD}, "
            f"NGƯỠNG_CLICK_PHẢI={self.RIGHT_CLICK_THRESHOLD}, "
            f"THỜI_GIAN_DEBOUNCE={self.DEBOUNCE_TIME}s"
        )

    def detect_gestures(self, landmarks: list) -> Dict[str, any]:
        """
        Phát hiện tất cả các cử chỉ có thể từ các điểm mốc bàn tay.

        Tham số:
            landmarks: Danh sách 21 tuple (x, y) điểm mốc bàn tay

        Trả về:
            Từ điển với các cử chỉ được phát hiện:
                - 'left_click': bool
                - 'right_click': bool
                - 'scroll': dict với 'direction' ('up'/'down') và 'magnitude'
        """
        if not landmarks or len(landmarks) < 21:
            return {
                "left_click": False,
                "right_click": False,
                "scroll": {"direction": None, "magnitude": 0},
            }

        current_time = time.time()

        # Phát hiện click trái (ngón cái + ngón trỏ)
        left_click = self._detect_left_click(landmarks, current_time)

        # Phát hiện click phải (ngón cái + ngón giữa)
        right_click = self._detect_right_click(landmarks, current_time)

        # Phát hiện cuộn (ngón trỏ + ngón giữa duỗi thẳng)
        scroll_result = self._detect_scroll(landmarks, current_time)

        return {
            "left_click": left_click,
            "right_click": right_click,
            "scroll": scroll_result,
        }

    def _detect_left_click(self, landmarks: list, current_time: float) -> bool:
        """
        Phát hiện cử chỉ click trái: đầu ngón cái gần đầu ngón trỏ.

        Tham số:
            landmarks: Danh sách 21 điểm mốc
            current_time: Thời gian hiện tại để kiểm tra debounce

        Trả về:
            True nếu click trái được phát hiện và thời gian debounce đã qua
        """
        # Lấy đầu ngón cái và ngón trỏ
        thumb_tip = landmarks[self.THUMB_TIP]
        index_tip = landmarks[self.INDEX_TIP]

        if not thumb_tip or not index_tip:
            return False

        # Tính khoảng cách
        distance = self._calculate_distance(thumb_tip, index_tip)

        # Kiểm tra xem có trong ngưỡng và thời gian debounce đã qua chưa
        if distance < self.LEFT_CLICK_THRESHOLD:
            if current_time - self.last_left_click_time >= self.DEBOUNCE_TIME:
                self.last_left_click_time = current_time
                logger.debug(f"Phát hiện click trái (khoảng cách: {distance:.1f})")
                return True

        return False

    def _detect_right_click(self, landmarks: list, current_time: float) -> bool:
        """
        Phát hiện cử chỉ click phải: đầu ngón cái gần đầu ngón giữa.

        Tham số:
            landmarks: Danh sách 21 điểm mốc
            current_time: Thời gian hiện tại để kiểm tra debounce

        Trả về:
            True nếu click phải được phát hiện và thời gian debounce đã qua
        """
        # Lấy đầu ngón cái và ngón giữa
        thumb_tip = landmarks[self.THUMB_TIP]
        middle_tip = landmarks[self.MIDDLE_TIP]

        if not thumb_tip or not middle_tip:
            return False

        # Tính khoảng cách
        distance = self._calculate_distance(thumb_tip, middle_tip)

        # Kiểm tra xem có trong ngưỡng và thời gian debounce đã qua chưa
        if distance < self.RIGHT_CLICK_THRESHOLD:
            if current_time - self.last_right_click_time >= self.DEBOUNCE_TIME:
                self.last_right_click_time = current_time
                logger.debug(f"Phát hiện click phải (khoảng cách: {distance:.1f})")
                return True

        return False

    def _detect_scroll(self, landmarks: list, current_time: float) -> Dict[str, any]:
        """
        Phát hiện cử chỉ cuộn: ngón trỏ và ngón giữa duỗi thẳng.
        Hướng được xác định bởi vị trí dọc tương đối.

        Tham số:
            landmarks: Danh sách 21 điểm mốc
            current_time: Thời gian hiện tại để kiểm tra debounce

        Trả về:
            Từ điển với 'direction' ('up'/'down'/'None') và 'magnitude'
        """
        # Lấy đầu ngón trỏ và ngón giữa
        index_tip = landmarks[self.INDEX_TIP]
        middle_tip = landmarks[self.MIDDLE_TIP]
        index_base = landmarks[self.INDEX_BASE]
        middle_base = landmarks[self.MIDDLE_BASE]

        if not all([index_tip, middle_tip, index_base, middle_base]):
            return {"direction": None, "magnitude": 0}

        # Kiểm tra xem cả hai ngón có duỗi ra không (đầu ngón ở dưới gốc ngón)
        index_extended = index_tip[1] > index_base[1]
        middle_extended = middle_tip[1] > middle_base[1]

        if not (index_extended and middle_extended):
            return {"direction": None, "magnitude": 0}

        # Kiểm tra xem các ngón có gần thẳng không (khoảng cách giữa đầu và gốc ngón)
        index_straightness = abs(index_tip[0] - index_base[0])
        middle_straightness = abs(middle_tip[0] - middle_base[0])

        if (
            index_straightness > self.SCROLL_STRAIGHTNESS_THRESHOLD
            or middle_straightness > self.SCROLL_STRAIGHTNESS_THRESHOLD
        ):
            return {"direction": None, "magnitude": 0}

        # Xác định hướng cuộn dựa trên vị trí đầu ngón tay
        avg_y = (index_tip[1] + middle_tip[1]) / 2
        avg_base_y = (index_base[1] + middle_base[1]) / 2

        # Nếu đầu ngón cao hơn gốc ngón, cuộn lên; ngược lại cuộn xuống
        if avg_y < avg_base_y:
            direction = "up"
        else:
            direction = "down"

        # Tính độ lớn cuộn (khoảng cách di chuyển)
        magnitude = abs(avg_y - avg_base_y)

        # Áp dụng debounce cho cuộn để tránh kích hoạt liên tục
        if current_time - self.last_scroll_time >= self.DEBOUNCE_TIME:
            if direction != self.last_scroll_direction:
                self.last_scroll_time = current_time
                self.last_scroll_direction = direction
                logger.debug(f"Phát hiện cuộn: {direction} (độ lớn: {magnitude:.1f})")
                return {"direction": direction, "magnitude": int(magnitude)}

        return {"direction": None, "magnitude": 0}

    @staticmethod
    def _calculate_distance(point1: Tuple[int, int], point2: Tuple[int, int]) -> float:
        """
        Tính khoảng cách Euclid giữa hai điểm.

        Tham số:
            point1: Tuple (x, y)
            point2: Tuple (x, y)

        Trả về:
            Khoảng cách Euclid
        """
        if not point1 or not point2:
            return float("inf")

        return math.sqrt((point1[0] - point2[0]) ** 2 + (point1[1] - point2[1]) ** 2)

    def reset_debounce(self) -> None:
        """Đặt lại tất cả bộ đếm thời gian debounce."""
        self.last_left_click_time = 0.0
        self.last_right_click_time = 0.0
        self.last_scroll_time = 0.0
        self.last_scroll_direction = None
        logger.info("Đã đặt lại bộ đếm thời gian debounce")
