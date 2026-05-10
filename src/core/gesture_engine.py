"""
Engine Nhận dạng Cử chỉ Bàn tay.
Phát hiện cử chỉ và chuyển đổi thành các sự kiện điều khiển chuột.
Hỗ trợ: rê chuột, cuộn chuột, click trái/phải, click đúp, dừng chương trình.
"""

import logging
import math
import time
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GestureMode(Enum):
    """Chế độ cử chỉ hiện tại của bàn tay."""
    NONE = auto()      # Không có bàn tay trong khung hình
    HOVER = auto()     # Rê chuột bình thường (di chuyển, không nhấn)
    SCROLL = auto()    # Cuộn chuột giữa (nắm đấm di chuyển lên/xuống)
    STOP = auto()      # Tín hiệu dừng chương trình


class GestureEngine:
    """
    Nhận dạng cử chỉ bàn tay và kích hoạt các sự kiện chuột tương ứng.

    Các cử chỉ được hỗ trợ:
    - 5 ngón duỗi thẳng → Dừng chương trình ngay lập tức
    - 5 ngón nắm thành nắm đấm → Cuộn chuột giữa lên/xuống
    - Ngón cái + ngón trỏ duỗi (các ngón khác co) → Rê chuột bình thường
    - Ngón cái + ngón trỏ chụm lại rồi thả ra nhanh → Click trái (có thể click đúp)
    - Ngón cái co, ngón trỏ duỗi → Click phải
    """

    # ── ID các điểm mốc bàn tay MediaPipe ──────────────────────────────
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20

    # ── Định nghĩa từng ngón: (id_đầu_ngón, id_khớp_giữa) ──────────────
    # Khớp giữa: PIP cho ngón dài, IP cho ngón cái
    FINGER_DEFS = [
        (THUMB_TIP, THUMB_IP),    # Ngón cái
        (INDEX_TIP, INDEX_PIP),   # Ngón trỏ
        (MIDDLE_TIP, MIDDLE_PIP), # Ngón giữa
        (RING_TIP, RING_PIP),     # Ngón áp út
        (PINKY_TIP, PINKY_PIP),   # Ngón út
    ]

    # ── Ngưỡng phát hiện (pixel) ───────────────────────────────────────
    PINCH_THRESHOLD = 40           # Khoảng cách tối đa coi là chụm ngón
    PINCH_RELEASE_THRESHOLD = 55   # Khoảng cách tối thiểu coi là thả ngón
    FINGER_EXTEND_RATIO = 0.88     # Tỉ lệ dist(tip,wrist)/dist(pip,wrist) để coi là duỗi

    # ── Thời gian debounce (giây) ──────────────────────────────────────
    CLICK_DEBOUNCE = 0.25          # Debounce cơ bản cho click đơn
    DOUBLE_CLICK_WINDOW = 0.4      # Khoảng thời gian tối đa giữa 2 lần click để tính là click đúp
    DOUBLE_CLICK_COOLDOWN = 1.0    # Thời gian chờ sau click đúp trước khi cho phép click tiếp
    RIGHT_CLICK_DEBOUNCE = 0.5     # Debounce cho click phải

    # ── Ngưỡng khung hình cho cử chỉ dừng (tránh kích hoạt nhầm) ──────
    STOP_FRAME_THRESHOLD = 5       # Số khung hình liên tiếp cần giữ 5 ngón duỗi

    def __init__(self) -> None:
        """Khởi tạo engine nhận dạng cử chỉ với đầy đủ trạng thái."""
        # ── Trạng thái máy pinch (phát hiện click qua chụm/thả ngón) ──
        self._pinch_state: str = "idle"  # idle → pinching → (click khi thả)

        # ── Lịch sử click để phát hiện click đúp ───────────────────────
        self._click_times: List[float] = []

        # ── Bộ đếm thời gian debounce ──────────────────────────────────
        self._last_right_click_time: float = 0.0

        # ── Bộ đếm khung hình cho cử chỉ dừng ──────────────────────────
        self._stop_frame_count: int = 0

        # ── Chế độ hiện tại ────────────────────────────────────────────
        self._current_mode: GestureMode = GestureMode.NONE

        logger.info(
            "Khởi tạo GestureEngine: NGƯỠNG_CHỤM=%dpx, NGƯỠNG_THẢ=%dpx, "
            "TỈ_LỆ_DUỖI=%.2f, KHUNG_DỪNG=%d",
            self.PINCH_THRESHOLD, self.PINCH_RELEASE_THRESHOLD,
            self.FINGER_EXTEND_RATIO, self.STOP_FRAME_THRESHOLD,
        )

    # ────────────────────────────────────────────────────────────────────
    # GIAO DIỆN CHÍNH
    # ────────────────────────────────────────────────────────────────────

    def detect_gestures(self, landmarks: List[Tuple[int, int]]) -> Dict:
        """
        Phát hiện tất cả các cử chỉ từ danh sách 21 điểm mốc bàn tay.

        Tham số:
            landmarks: Danh sách 21 tuple (x, y) trong không gian khung hình camera.

        Trả về:
            Từ điển với các khóa:
            - 'mode': GestureMode - chế độ hiện tại (HOVER/SCROLL/STOP/NONE)
            - 'left_click': bool - sự kiện click trái đơn
            - 'double_click': bool - sự kiện click đúp
            - 'right_click': bool - sự kiện click phải
            - 'stop': bool - tín hiệu dừng chương trình
            - 'scroll': dict - giữ lại để tương thích (hiện không dùng)
        """
        result = {
            "mode": GestureMode.NONE,
            "left_click": False,
            "double_click": False,
            "right_click": False,
            "stop": False,
            "scroll": {"direction": None, "magnitude": 0},
        }

        # ── Không có bàn tay → đặt lại toàn bộ trạng thái ──────────────
        if not landmarks or len(landmarks) < 21:
            self._reset_state()
            return result

        current_time = time.time()

        # ── Bước 1: Xác định ngón nào đang duỗi ────────────────────────
        fingers_extended = self._get_extended_fingers(landmarks)
        num_extended = sum(fingers_extended)

        thumb_ext = fingers_extended[0]
        index_ext = fingers_extended[1]
        middle_ext = fingers_extended[2]
        ring_ext = fingers_extended[3]
        pinky_ext = fingers_extended[4]

        # ── Bước 2: Phát hiện 5 ngón duỗi → DỪNG CHƯƠNG TRÌNH ──────────
        if num_extended == 5:
            self._stop_frame_count += 1
            if self._stop_frame_count >= self.STOP_FRAME_THRESHOLD:
                result["mode"] = GestureMode.STOP
                result["stop"] = True
                self._current_mode = GestureMode.STOP
                logger.info(">>> Phát hiện 5 ngón duỗi thẳng - DỪNG CHƯƠNG TRÌNH <<<")
                return result
        else:
            self._stop_frame_count = 0

        # ── Bước 3: Phát hiện nắm đấm (0 ngón duỗi) → CUỘN CHUỘT ─────
        if num_extended == 0:
            result["mode"] = GestureMode.SCROLL
            self._current_mode = GestureMode.SCROLL
            logger.debug("Chế độ cuộn chuột (nắm đấm)")
            # Khi đang cuộn, không phát hiện các cử chỉ khác
            return result

        # ── Bước 4: Phát hiện ngón cái + ngón trỏ duỗi, các ngón khác co → RÊ CHUỘT ──
        only_index_thumb = (
            thumb_ext and index_ext
            and not middle_ext and not ring_ext and not pinky_ext
        )

        if only_index_thumb:
            result["mode"] = GestureMode.HOVER
            self._current_mode = GestureMode.HOVER

            # Phát hiện click qua chụm/thả ngón cái + ngón trỏ
            thumb_tip = landmarks[self.THUMB_TIP]
            index_tip = landmarks[self.INDEX_TIP]
            pinch_dist = self._calculate_distance(thumb_tip, index_tip)

            click_info = self._detect_pinch_click(pinch_dist, current_time)
            result["left_click"] = click_info["left_click"]
            result["double_click"] = click_info["double_click"]

        # ── Bước 5: Phát hiện ngón cái co + ngón trỏ duỗi → CLICK PHẢI ─
        only_index = (
            index_ext and not thumb_ext
            and not middle_ext and not ring_ext and not pinky_ext
        )

        if only_index:
            result["mode"] = GestureMode.HOVER
            self._current_mode = GestureMode.HOVER
            if current_time - self._last_right_click_time >= self.RIGHT_CLICK_DEBOUNCE:
                self._last_right_click_time = current_time
                result["right_click"] = True
                logger.info("Cử chỉ: Click Phải (ngón cái co, ngón trỏ duỗi)")

        # ── Bước 6: Mặc định → RÊ CHUỘT nếu có bàn tay ─────────────────
        if result["mode"] == GestureMode.NONE:
            result["mode"] = GestureMode.HOVER
            self._current_mode = GestureMode.HOVER

        return result

    # ────────────────────────────────────────────────────────────────────
    # PHÁT HIỆN NGÓN DUỖI
    # ────────────────────────────────────────────────────────────────────

    def _get_extended_fingers(self, landmarks: List[Tuple[int, int]]) -> List[bool]:
        """
        Xác định từng ngón có đang duỗi thẳng hay không.

        Nguyên lý: So sánh khoảng cách từ đầu ngón đến cổ tay với khoảng cách
        từ khớp giữa (PIP/IP) đến cổ tay. Nếu đầu ngón xa cổ tay hơn đáng kể
        (vượt ngưỡng FINGER_EXTEND_RATIO), ngón đó đang duỗi.
        Cách này hoạt động ổn định với nhiều góc nghiêng bàn tay khác nhau,
        không phụ thuộc vào hướng tuyệt đối của trục Y.
        """
        wrist = landmarks[self.WRIST]
        extended = []

        for tip_id, pip_id in self.FINGER_DEFS:
            tip = landmarks[tip_id]
            pip = landmarks[pip_id]

            dist_tip_wrist = self._calculate_distance(tip, wrist)
            dist_pip_wrist = self._calculate_distance(pip, wrist)

            # Tránh chia cho 0 khi khớp trùng cổ tay (không xảy ra thực tế)
            if dist_pip_wrist < 1.0:
                extended.append(False)
                continue

            ratio = dist_tip_wrist / dist_pip_wrist
            extended.append(ratio > self.FINGER_EXTEND_RATIO)

        return extended

    # ────────────────────────────────────────────────────────────────────
    # PHÁT HIỆN CLICK QUA CHỤM/THẢ NGÓN (PINCH)
    # ────────────────────────────────────────────────────────────────────

    def _detect_pinch_click(self, pinch_distance: float, current_time: float) -> Dict:
        """
        Phát hiện sự kiện click thông qua cử chỉ chụm và thả ngón cái + ngón trỏ.

        Máy trạng thái đơn giản:
            idle ──(khoảng cách < PINCH_THRESHOLD)──▶ pinching
            pinching ──(khoảng cách > PINCH_RELEASE_THRESHOLD)──▶ idle + click!

        Hỗ trợ click đúp: nếu 2 lần click xảy ra trong DOUBLE_CLICK_WINDOW,
        gộp thành click đúp. Sau click đúp, áp dụng DOUBLE_CLICK_COOLDOWN
        để tránh click liên tục gây lỗi.
        """
        result = {"left_click": False, "double_click": False}

        if self._pinch_state == "idle":
            # Bắt đầu chụm ngón: khoảng cách giảm xuống dưới ngưỡng
            if pinch_distance < self.PINCH_THRESHOLD:
                self._pinch_state = "pinching"

        elif self._pinch_state == "pinching":
            # Thả ngón: khoảng cách tăng lên trên ngưỡng thả
            if pinch_distance > self.PINCH_RELEASE_THRESHOLD:
                self._pinch_state = "idle"

                # ── Kiểm tra debounce cơ bản ───────────────────────────
                if self._click_times:
                    time_since_last = current_time - self._click_times[-1]
                    if time_since_last < self.CLICK_DEBOUNCE:
                        return result  # Bỏ qua, quá gần lần click trước

                # ── Kiểm tra cooldown sau click đúp ────────────────────
                if self._click_times and len(self._click_times) >= 2:
                    # Nếu 2 lần click gần nhất đã tạo thành click đúp
                    last_two = self._click_times[-2:]
                    if len(last_two) == 2 and (last_two[1] - last_two[0]) <= self.DOUBLE_CLICK_WINDOW:
                        time_since_double = current_time - last_two[1]
                        if time_since_double < self.DOUBLE_CLICK_COOLDOWN:
                            return result  # Đang trong thời gian chờ sau click đúp

                # ── Ghi nhận thời điểm click ───────────────────────────
                self._click_times.append(current_time)

                # Dọn dẹp lịch sử cũ (> 2 giây) để tránh rò rỉ bộ nhớ
                self._click_times = [
                    t for t in self._click_times
                    if current_time - t < 2.0
                ]

                # ── Phát hiện click đúp ────────────────────────────────
                if len(self._click_times) >= 2:
                    interval = self._click_times[-1] - self._click_times[-2]
                    if interval <= self.DOUBLE_CLICK_WINDOW:
                        result["double_click"] = True
                        logger.info("Cử chỉ: Click Đúp!")
                        return result

                # ── Click đơn ──────────────────────────────────────────
                result["left_click"] = True
                logger.debug("Cử chỉ: Click Trái (chụm/thả ngón)")

        return result

    # ────────────────────────────────────────────────────────────────────
    # TIỆN ÍCH
    # ────────────────────────────────────────────────────────────────────

    def _reset_state(self) -> None:
        """Đặt lại toàn bộ trạng thái khi không phát hiện thấy bàn tay."""
        self._pinch_state = "idle"
        self._stop_frame_count = 0
        self._current_mode = GestureMode.NONE

    @property
    def current_mode(self) -> GestureMode:
        """Trả về chế độ cử chỉ hiện tại."""
        return self._current_mode

    @staticmethod
    def _calculate_distance(p1: Tuple[int, int], p2: Tuple[int, int]) -> float:
        """Tính khoảng cách Euclid giữa hai điểm trong mặt phẳng 2D."""
        if not p1 or not p2:
            return float("inf")
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)
