"""
Engine Nhận dạng Cử chỉ Bàn tay.
Phát hiện cử chỉ và chuyển đổi thành các sự kiện điều khiển chuột.
Hỗ trợ: rê chuột, cuộn chuột, click trái, click đúp, dừng chương trình.
"""

import logging
import math
import time
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GestureMode(Enum):
    # ======= Chế độ cử chỉ hiện tại của bàn tay =======
    NONE = auto()      # Không có bàn tay trong khung hình
    HOVER = auto()     # Rê chuột bình thường (di chuyển, không nhấn)
    SCROLL = auto()    # Cuộn chuột giữa (nắm đấm giữ 2s + di chuyển lên/xuống)
    STOP = auto()      # Tín hiệu dừng chương trình


class GestureEngine:
    """
    Nhận dạng cử chỉ bàn tay và kích hoạt các sự kiện chuột tương ứng.

    Các cử chỉ được hỗ trợ:
    - Chỉ có 1 ngón trỏ duỗi → Rê chuột bình thường
    - Ngón trỏ duỗi → co nhanh → duỗi = Click trái (2 lần = click đúp)
    - Ngón trỏ duỗi + ngón cái co → duỗi → co = Click phải
    - Cả 5 ngón co → Chuột đứng yên tại chỗ
    - Cả 5 ngón co + giữ 2 giây → Cuộn chuột giữa lên/xuống
    - 5 ngón duỗi thẳng → Dừng chương trình
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
    FINGER_EXTEND_RATIO = 0.70     # Tỉ lệ dist(tip,wrist)/dist(pip,wrist) để coi là duỗi

    # ── Ngưỡng phát hiện ngón cái co (pixel) ───────────────────────────
    THUMB_CURLED_THRESHOLD = 70    # Khoảng cách tối đa từ đầu ngón cái đến khớp ngón trỏ để coi là co

    # ── Thời gian debounce (giây) ──────────────────────────────────────
    CLICK_DEBOUNCE = 0.25          # Debounce cơ bản cho click đơn
    DOUBLE_CLICK_WINDOW = 0.4      # Khoảng thời gian tối đa giữa 2 lần click để tính là click đúp
    DOUBLE_CLICK_COOLDOWN = 1.0    # Thời gian chờ sau click đúp trước khi cho phép click tiếp
    RIGHT_CLICK_DEBOUNCE = 0.5     # Debounce cho click phải

    # ── Ngưỡng khung hình cho cử chỉ dừng (tránh kích hoạt nhầm) ──────
    STOP_FRAME_THRESHOLD = 5       # Số khung hình liên tiếp cần giữ 5 ngón duỗi

    # ── Thời gian giữ nắm đấm để vào chế độ cuộn ──────────────────────
    SCROLL_HOLD_TIME = 2.0         # Giây

    # ── Thời gian tối đa để coi là click nhanh ─────────────────────────
    QUICK_CLICK_WINDOW = 0.4       # Giây (phải hoàn thành co-duỗi trong khoảng này)

    def __init__(self) -> None:
        """Khởi tạo engine nhận dạng cử chỉ với đầy đủ trạng thái."""
        # ── Lịch sử click để phát hiện click đúp ───────────────────────
        self._click_times: List[float] = []

        # ── Bộ đếm khung hình cho cử chỉ dừng ──────────────────────────
        self._stop_frame_count: int = 0

        # ── Bộ đếm thời gian cho chế độ cuộn (nắm đấm) ────────────────
        self._scroll_hold_start: float = 0.0

        # ── Trạng thái trước đó của ngón trỏ và ngón cái (để phát hiện co/duỗi) ──
        self._prev_index_ext: bool = False
        self._prev_thumb_curled: bool = False

        # ── Thời điểm ngón trỏ co lại gần nhất (để phát hiện click nhanh) ──
        self._index_curled_time: float = 0.0

        # ── Thời điểm ngón cái duỗi ra gần nhất (để phát hiện click thay thế) ──
        self._thumb_extended_time: float = 0.0

        # ── Thời điểm click phải gần nhất (debounce) ──────────────────────
        self._last_right_click_time: float = 0.0

        # ── Chế độ hiện tại ────────────────────────────────────────────
        self._current_mode: GestureMode = GestureMode.NONE

        logger.info(
            "Khởi tạo GestureEngine: TỈ_LỆ_DUỖI=%.2f, KHUNG_DỪNG=%d, GIỮ_CUỘN=%.1fs",
            self.FINGER_EXTEND_RATIO, self.STOP_FRAME_THRESHOLD,
            self.SCROLL_HOLD_TIME,
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
            - 'scroll': dict - giữ lại để tương thích
            - 'fist_hold': bool - True khi đang nắm tay (dừng di chuyển chuột)
        """
        result = {
            "mode": GestureMode.NONE,
            "left_click": False,
            "double_click": False,
            "right_click": False,
            "stop": False,
            "scroll": {"direction": None, "magnitude": 0},
            "fist_hold": False,
        }

        # ── Không có bàn tay → đặt lại toàn bộ trạng thái ──────────────
        if not landmarks or len(landmarks) < 21:
            self._reset_state()
            return result

        current_time = time.time()

        # ── Bước 1: Xác định ngón nào đang duỗi và ngón cái co ─────────
        fingers_extended = self._get_extended_fingers(landmarks)
        num_extended = sum(fingers_extended)

        thumb_ext = fingers_extended[0]
        index_ext = fingers_extended[1]
        middle_ext = fingers_extended[2]
        ring_ext = fingers_extended[3]
        pinky_ext = fingers_extended[4]

        thumb_curled = self._is_thumb_curled(landmarks)

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

        # ── Bước 3: Phát hiện nắm đấm (0 ngón duỗi) → ĐỨNG YÊN / CUỘN ─
        if num_extended == 0:
            # Bắt đầu hoặc tiếp tục đếm thời gian giữ nắm đấm
            if self._scroll_hold_start == 0.0:
                self._scroll_hold_start = current_time
                logger.debug(f"Bắt đầu đếm giữ nắm đấm ({self.SCROLL_HOLD_TIME}s)")
            elif current_time - self._scroll_hold_start >= self.SCROLL_HOLD_TIME:
                # Đủ 2 giây → chế độ cuộn chuột
                result["mode"] = GestureMode.SCROLL
                self._current_mode = GestureMode.SCROLL
                logger.debug("Chế độ cuộn chuột (nắm đấm)")
                # Reset trạng thái click để tránh click khi thoát cuộn
                self._prev_index_ext = False
                self._prev_thumb_curled = False
                self._index_curled_time = 0.0
                self._thumb_extended_time = 0.0
                return result

            # Chưa đủ 2 giây → đứng yên, không di chuyển chuột
            result["mode"] = GestureMode.HOVER
            self._current_mode = GestureMode.HOVER
            result["fist_hold"] = True
            return result
        else:
            # Không còn nắm đấm → đặt lại bộ đếm giữ
            self._scroll_hold_start = 0.0

        # ── Bước 4: Chế độ rê chuột (HOVER) ────────────────────────────
        # Mặc định có bàn tay là rê chuột
        result["mode"] = GestureMode.HOVER
        self._current_mode = GestureMode.HOVER

        # ── Phát hiện click trái qua co/duỗi ngón trỏ ─────────────────
        # Ngón trỏ: đang duỗi → co → duỗi trong QUICK_CLICK_WINDOW = click
        if self._prev_index_ext and not index_ext:
            # Ngón trỏ vừa co lại → ghi nhận thời điểm
            self._index_curled_time = current_time
        elif not self._prev_index_ext and index_ext:
            # Ngón trỏ vừa duỗi ra → kiểm tra có phải click nhanh không
            if self._index_curled_time > 0.0:
                elapsed = current_time - self._index_curled_time
                if 0.05 < elapsed < self.QUICK_CLICK_WINDOW:
                    # Click nhanh hợp lệ
                    self._index_curled_time = 0.0
                    self._register_click(current_time, result)
                else:
                    self._index_curled_time = 0.0

        # ── Phát hiện click trái qua co/duỗi ngón cái (thay thế) ─────
        # Chỉ hoạt động khi ngón trỏ đang duỗi
        # Ngón cái: đang co → duỗi → co trong QUICK_CLICK_WINDOW = click
        if index_ext:
            if self._prev_thumb_curled and not thumb_curled:
                # Ngón cái vừa duỗi ra → ghi nhận thời điểm
                self._thumb_extended_time = current_time
            elif not self._prev_thumb_curled and thumb_curled:
                # Ngón cái vừa co lại → kiểm tra có phải click không
                if self._thumb_extended_time > 0.0:
                    elapsed = current_time - self._thumb_extended_time
                    if 0.05 < elapsed < self.QUICK_CLICK_WINDOW:
                        # Click phải hợp lệ (ngón cái co → duỗi → co)
                        self._thumb_extended_time = 0.0
                        if current_time - self._last_right_click_time >= self.RIGHT_CLICK_DEBOUNCE:
                            self._last_right_click_time = current_time
                            result["right_click"] = True
                            logger.info("Cử chỉ: Click Phải (ngón cái co → duỗi → co)")
                    else:
                        self._thumb_extended_time = 0.0
        else:
            # Nếu ngón trỏ không duỗi, đặt lại trạng thái ngón cái
            self._thumb_extended_time = 0.0

        # ── Cập nhật trạng thái trước đó ───────────────────────────────
        self._prev_index_ext = index_ext
        self._prev_thumb_curled = thumb_curled

        return result

    # ────────────────────────────────────────────────────────────────────
    # ĐĂNG KÝ CLICK (XỬ LÝ CLICK ĐƠN / CLICK ĐÚP)
    # ────────────────────────────────────────────────────────────────────

    def _register_click(self, current_time: float, result: Dict) -> None:
        """
        Ghi nhận một lần click và xác định click đơn hay click đúp.
        """
        # Debounce cơ bản
        if self._click_times:
            time_since_last = current_time - self._click_times[-1]
            if time_since_last < self.CLICK_DEBOUNCE:
                return

        # Kiểm tra cooldown sau click đúp
        if self._click_times and len(self._click_times) >= 2:
            last_two = self._click_times[-2:]
            if len(last_two) == 2 and (last_two[1] - last_two[0]) <= self.DOUBLE_CLICK_WINDOW:
                time_since_double = current_time - last_two[1]
                if time_since_double < self.DOUBLE_CLICK_COOLDOWN:
                    return

        # Ghi nhận click
        self._click_times.append(current_time)
        # Dọn dẹp lịch sử cũ
        self._click_times = [t for t in self._click_times if current_time - t < 2.0]

        # Kiểm tra click đúp
        if len(self._click_times) >= 2:
            interval = self._click_times[-1] - self._click_times[-2]
            if interval <= self.DOUBLE_CLICK_WINDOW:
                result["double_click"] = True
                logger.info("Cử chỉ: Click Đúp!")
                return

        result["left_click"] = True
        logger.debug("Cử chỉ: Click Trái (co/duỗi ngón)")

    # ────────────────────────────────────────────────────────────────────
    # PHÁT HIỆN NGÓN DUỖI
    # ────────────────────────────────────────────────────────────────────

    def _get_extended_fingers(self, landmarks: List[Tuple[int, int]]) -> List[bool]:
        """
        Xác định từng ngón có đang duỗi thẳng hay không.
        """
        wrist = landmarks[self.WRIST]
        extended = []

        for tip_id, pip_id in self.FINGER_DEFS:
            tip = landmarks[tip_id]
            pip = landmarks[pip_id]

            # Đối với các ngón dài (không phải ngón cái), kiểm tra thêm trục Y
            if tip_id != self.THUMB_TIP and tip[1] >= pip[1]:
                extended.append(False)
                continue

            dist_tip_wrist = self._calculate_distance(tip, wrist)
            dist_pip_wrist = self._calculate_distance(pip, wrist)

            if dist_pip_wrist < 1.0:
                extended.append(False)
                continue

            ratio = dist_tip_wrist / dist_pip_wrist
            extended.append(ratio > self.FINGER_EXTEND_RATIO)

        return extended

    # ────────────────────────────────────────────────────────────────────
    # PHÁT HIỆN NGÓN CÁI CO
    # ────────────────────────────────────────────────────────────────────

    def _is_thumb_curled(self, landmarks: List[Tuple[int, int]]) -> bool:
        """Xác định ngón cái có đang co lại hay không."""
        thumb_tip = landmarks[self.THUMB_TIP]
        index_mcp = landmarks[self.INDEX_MCP]
        distance = self._calculate_distance(thumb_tip, index_mcp)
        return distance < self.THUMB_CURLED_THRESHOLD

    # ────────────────────────────────────────────────────────────────────
    # TIỆN ÍCH
    # ────────────────────────────────────────────────────────────────────

    def _reset_state(self) -> None:
        """Đặt lại toàn bộ trạng thái khi không phát hiện thấy bàn tay."""
        self._click_times.clear()
        self._stop_frame_count = 0
        self._scroll_hold_start = 0.0
        self._prev_index_ext = False
        self._prev_thumb_curled = False
        self._index_curled_time = 0.0
        self._thumb_extended_time = 0.0
        self._last_right_click_time = 0.0
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
