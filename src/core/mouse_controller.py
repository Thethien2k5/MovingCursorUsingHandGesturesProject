"""
Bộ Điều khiển Chuột với Xử lý Tín hiệu.
Xử lý làm mượt, ánh xạ ROI, và điều khiển chuột hệ điều hành.
"""

import logging
import math
import pyautogui
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Tắt failsafe của PyAutoGUI để tránh thoát ứng dụng ngoài ý muốn
pyautogui.FAILSAFE = False


class OneEuroFilter:
    """
    Bộ lọc One Euro để làm mượt tín hiệu tọa độ.
    Giảm rung lắc trong khi vẫn duy trì độ phản hồi.
    Tham khảo: "1€ Filter: A Simple Speed-based Low-pass Filter for Noisy Input in Interactive Systems"
    """

    def __init__(self, freq: float = 120.0, mincutoff: float = 1.0, beta: float = 0.5, dcutoff: float = 1.0) -> None:
        """
        Khởi tạo Bộ lọc One Euro.

        Tham số:
            freq: Tần số lấy mẫu tính bằng Hz
            mincutoff: Tần số cắt tối thiểu (Hz)
            beta: Tham số beta để làm mượt đạo hàm
            dcutoff: Tần số cắt cho đạo hàm (Hz)
        """
        self.freq = freq
        self.mincutoff = mincutoff
        self.beta = beta
        self.dcutoff = dcutoff

        self.x_filter: Optional["LowPassFilter"] = None
        self.dx_filter: Optional["LowPassFilter"] = None
        self.lasttime: Optional[float] = None

        logger.info(
            f"Khởi tạo OneEuroFilter: tần_số={freq}, ngưỡng_cắt_thấp_nhất={mincutoff}, "
            f"beta={beta}, ngưỡng_cắt_đạo_hàm={dcutoff}"
        )

    def process(self, x: float, timestamp: float) -> float:
        """
        Lọc một giá trị đơn.

        Tham số:
            x: Giá trị đầu vào cần lọc
            timestamp: Dấu thời gian hiện tại tính bằng giây

        Trả về:
            Giá trị đã được lọc
        """
        if self.lasttime is None:
            self.lasttime = timestamp
            self.x_filter = LowPassFilter(self._alpha_from_cutoff(self.mincutoff), x)
            self.dx_filter = LowPassFilter(self._alpha_from_cutoff(self.dcutoff), 0.0)
            return x

        # Tính delta time và đạo hàm
        delta_time = timestamp - self.lasttime
        self.lasttime = timestamp

        if delta_time <= 0:
            return x

        # Lấy đạo hàm đã lọc hiện tại
        dx = (x - self.x_filter.last_value) / delta_time if self.x_filter else 0.0
        dx_filtered = self.dx_filter.filter(dx, self._alpha_from_cutoff(self.dcutoff))

        # Tính tần số cắt thích ứng
        cutoff = self.mincutoff + self.beta * abs(dx_filtered)

        # Lọc vị trí
        return self.x_filter.filter(x, self._alpha_from_cutoff(cutoff))

    def _alpha_from_cutoff(self, cutoff: float) -> float:
        """Tính tham số alpha từ tần số cắt."""
        return 1.0 - math.exp(-2.0 * math.pi * cutoff / self.freq)


class LowPassFilter:
    """Thành phần bộ lọc thông thấp đơn giản."""

    def __init__(self, alpha: float, initial_value: float) -> None:
        """
        Khởi tạo bộ lọc thông thấp.

        Tham số:
            alpha: Hệ số làm mượt (0-1)
            initial_value: Giá trị đã lọc ban đầu
        """
        self.alpha = alpha
        self.last_value = initial_value

    def filter(self, value: float, alpha: Optional[float] = None) -> float:
        """
        Áp dụng bộ lọc thông thấp.

        Tham số:
            value: Giá trị đầu vào
            alpha: Alpha tùy chỉnh tùy chọn cho lần lặp này

        Trả về:
            Giá trị đã được lọc
        """
        if alpha is None:
            alpha = self.alpha

        self.last_value = alpha * value + (1.0 - alpha) * self.last_value
        return self.last_value


class MouseController:
    """
    Điều khiển chuột hệ thống sử dụng tọa độ bàn tay đã lọc.
    Triển khai ROI động và làm mượt tín hiệu.
    """

    def __init__(
        self,
        screen_width: int = 1920,
        screen_height: int = 1080,
        roi_width_ratio: float = 0.4,
        roi_height_ratio: float = 0.4,
        smoothing_enabled: bool = True,
    ) -> None:
        """
        Khởi tạo MouseController.

        Tham số:
            screen_width: Chiều rộng màn hình hệ thống
            screen_height: Chiều cao màn hình hệ thống
            roi_width_ratio: Chiều rộng ROI theo tỷ lệ khung hình camera (0.0-1.0)
            roi_height_ratio: Chiều cao ROI theo tỷ lệ khung hình camera (0.0-1.0)
            smoothing_enabled: Bật làm mượt bằng Bộ lọc One Euro
        """
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.roi_width_ratio = roi_width_ratio
        self.roi_height_ratio = roi_height_ratio
        self.smoothing_enabled = smoothing_enabled

        # Khởi tạo Bộ lọc One Euro cho tọa độ X và Y
        self.x_filter = OneEuroFilter(freq=120.0, mincutoff=1.0, beta=0.5, dcutoff=1.0)
        self.y_filter = OneEuroFilter(freq=120.0, mincutoff=1.0, beta=0.5, dcutoff=1.0)

        # Kích thước khung hình camera (sẽ được đặt ở lần sử dụng đầu tiên)
        self.camera_width: Optional[int] = None
        self.camera_height: Optional[int] = None

        # Ranh giới ROI (tính từ kích thước camera)
        self.roi_left: Optional[int] = None
        self.roi_top: Optional[int] = None
        self.roi_right: Optional[int] = None
        self.roi_bottom: Optional[int] = None

        logger.info(
            f"Khởi tạo MouseController: màn_hình={screen_width}x{screen_height}, "
            f"tỉ_lệ_ROI={roi_width_ratio}x{roi_height_ratio}, làm_mượt={smoothing_enabled}"
        )

    def set_camera_dimensions(self, width: int, height: int) -> None:
        """
        Đặt kích thước khung hình camera và tính toán ROI.

        Tham số:
            width: Chiều rộng khung hình camera
            height: Chiều cao khung hình camera
        """
        self.camera_width = width
        self.camera_height = height

        # Tính toán ROI (hình vuông dựa trên trung tâm)
        roi_width = int(width * self.roi_width_ratio)
        roi_height = int(height * self.roi_height_ratio)

        self.roi_left = (width - roi_width) // 2
        self.roi_top = (height - roi_height) // 2
        self.roi_right = self.roi_left + roi_width
        self.roi_bottom = self.roi_top + roi_height

        logger.info(
            f"Đã đặt ROI: ({self.roi_left}, {self.roi_top}) đến ({self.roi_right}, {self.roi_bottom})"
        )

    def move_mouse(self, index_tip: Tuple[int, int], timestamp: float) -> None:
        """
        Di chuyển chuột hệ thống dựa trên vị trí ngón trỏ.

        Tham số:
            index_tip: (x, y) của đầu ngón trỏ từ khung hình camera
            timestamp: Dấu thời gian hiện tại cho bộ lọc
        """
        if not index_tip or not all([self.roi_left, self.roi_top, self.roi_right, self.roi_bottom]):
            return

        try:
            # Giới hạn trong ROI
            x_roi = max(self.roi_left, min(index_tip[0], self.roi_right))
            y_roi = max(self.roi_top, min(index_tip[1], self.roi_bottom))

            # Ánh xạ ROI sang tọa độ màn hình
            roi_width = self.roi_right - self.roi_left
            roi_height = self.roi_bottom - self.roi_top

            # Chuẩn hóa về phạm vi 0-1 trong ROI
            x_normalized = (x_roi - self.roi_left) / roi_width if roi_width > 0 else 0.5
            y_normalized = (y_roi - self.roi_top) / roi_height if roi_height > 0 else 0.5

            # Chia tỷ lệ sang tọa độ màn hình
            x_screen = x_normalized * self.screen_width
            y_screen = y_normalized * self.screen_height

            # Áp dụng bộ lọc làm mượt nếu được bật
            if self.smoothing_enabled:
                x_screen = self.x_filter.process(x_screen, timestamp)
                y_screen = self.y_filter.process(y_screen, timestamp)

            # Đảm bảo tọa độ nằm trong giới hạn màn hình
            x_screen = max(0, min(int(x_screen), self.screen_width - 1))
            y_screen = max(0, min(int(y_screen), self.screen_height - 1))

            # Di chuyển chuột
            pyautogui.moveTo(x_screen, y_screen, duration=0.0)

        except Exception as e:
            logger.error(f"Lỗi di chuyển chuột: {e}")

    def click_left(self) -> None:
        """Thực hiện click chuột trái đơn."""
        try:
            pyautogui.click(button='left')
            logger.debug("Đã thực hiện click trái")
        except Exception as e:
            logger.error(f"Lỗi thực hiện click trái: {e}")

    def double_click(self) -> None:
        """Thực hiện click đúp chuột trái."""
        try:
            pyautogui.doubleClick(button='left')
            logger.debug("Đã thực hiện click đúp trái")
        except Exception as e:
            logger.error(f"Lỗi thực hiện click đúp: {e}")

    def click_right(self) -> None:
        """Thực hiện click chuột phải."""
        try:
            pyautogui.click(button='right')
            logger.debug("Đã thực hiện click phải")
        except Exception as e:
            logger.error(f"Lỗi thực hiện click phải: {e}")

    def mouse_down(self) -> None:
        """Nhấn và giữ chuột trái (bắt đầu kéo thả)."""
        try:
            pyautogui.mouseDown(button='left')
            logger.debug("Đã nhấn giữ chuột trái")
        except Exception as e:
            logger.error(f"Lỗi nhấn giữ chuột: {e}")

    def mouse_up(self) -> None:
        """Thả chuột trái (kết thúc kéo thả)."""
        try:
            pyautogui.mouseUp(button='left')
            logger.debug("Đã thả chuột trái")
        except Exception as e:
            logger.error(f"Lỗi thả chuột: {e}")

    def release_all(self) -> None:
        """Thả tất cả các nút chuột đang giữ. Dùng khi bàn tay rời khỏi camera."""
        try:
            pyautogui.mouseUp(button='left')
            pyautogui.mouseUp(button='right')
            logger.debug("Đã thả toàn bộ nút chuột")
        except Exception as e:
            logger.error(f"Lỗi thả toàn bộ chuột: {e}")

    def scroll(self, direction: str, amount: int = 3) -> None:
        """
        Thực hiện cuộn chuột.

        Tham số:
            direction: 'up' hoặc 'down'
            amount: Số đơn vị cuộn (dương cho xuống, âm cho lên)
        """
        try:
            if direction == 'down':
                pyautogui.scroll(-amount)  # Âm là cuộn xuống
                logger.debug(f"Cuộn xuống: {amount} đơn vị")
            elif direction == 'up':
                pyautogui.scroll(amount)  # Dương là cuộn lên
                logger.debug(f"Cuộn lên: {amount} đơn vị")
        except Exception as e:
            logger.error(f"Lỗi thực hiện cuộn: {e}")

    def execute_gesture(self, gesture_result: Dict[str, any]) -> None:
        """
        Thực thi hành động chuột dựa trên các cử chỉ được phát hiện.

        Tham số:
            gesture_result: Từ điển từ GestureEngine.detect_gestures()
        """
        # Click trái đơn
        if gesture_result.get("left_click"):
            self.click_left()

        # Click đúp
        if gesture_result.get("double_click"):
            self.double_click()

        # Click phải
        if gesture_result.get("right_click"):
            self.click_right()

        # Cuộn (giữ lại để tương thích)
        scroll_info = gesture_result.get("scroll", {})
        if scroll_info.get("direction"):
            self.scroll(scroll_info["direction"], amount=3)
