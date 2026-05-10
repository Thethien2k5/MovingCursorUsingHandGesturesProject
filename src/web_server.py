"""
Máy chủ web FastAPI cung cấp giao diện web cho dự án Chuột Ảo AI.
- MJPEG streaming: truyền khung hình camera (đã vẽ khung xương) tới frontend
- WebSocket: gửi trạng thái bàn tay + cử chỉ theo thời gian thực
- Static files: phục vụ giao diện frontend (HTML/CSS/JS)
"""

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import FileResponse
from typing import Optional

from shared_state import shared_state

logger = logging.getLogger("web_server")

# ── Khởi tạo ứng dụng FastAPI ──────────────────────────────────────────
app = FastAPI(
    title="AI Virtual Mouse - Web Interface",
    description="Giao diện web hiển thị camera và trạng thái cử chỉ bàn tay",
    version="2.0.0",
)

# ── Danh sách các WebSocket client đang kết nối ────────────────────────
# Dùng set để tránh trùng lặp, thread-safe qua khóa asyncio
_ws_clients: set = set()

# ── Đường dẫn frontend ─────────────────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ════════════════════════════════════════════════════════════════════════
# ENDPOINTS HTTP
# ════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    """Trang chủ - giao diện web chính."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "AI Virtual Mouse API đang chạy. Frontend chưa được build."}


@app.get("/api/health")
async def health_check():
    """Endpoint kiểm tra trạng thái server."""
    return {
        "status": "running",
        "ws_clients": len(_ws_clients),
        "frontend_available": (FRONTEND_DIR / "index.html").exists(),
    }


@app.get("/video")
async def video_feed():
    """
    Endpoint MJPEG stream cho video camera.
    Frontend dùng thẻ <img src="/video"> để hiển thị.
    """

    async def generate_frames():
        """Generator bất đồng bộ tạo MJPEG stream."""
        while True:
            frame_bytes, _ = shared_state.get_frame()

            if frame_bytes is None:
                # Chưa có frame → gửi ảnh đen placeholder
                placeholder = _generate_placeholder_frame()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + placeholder
                    + b"\r\n"
                )
            else:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame_bytes
                    + b"\r\n"
                )

            # Điều khiển tốc độ stream ~30 FPS
            await asyncio.sleep(0.033)

    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/status")
async def get_status():
    """Endpoint REST trả về trạng thái hiện tại (dùng cho polling nếu không dùng WebSocket)."""
    return shared_state.get_full_status()


class CameraSwitchRequest(BaseModel):
    """Yêu cầu chuyển đổi nguồn camera từ frontend."""
    source: str  # "0" cho laptop, hoặc URL HTTP cho điện thoại
    label: str   # Nhãn hiển thị (vd: "Laptop", "Điện thoại")


@app.post("/api/switch-camera")
async def switch_camera(request: CameraSwitchRequest):
    """
    Endpoint chuyển đổi nguồn camera.
    Frontend gọi API này khi người dùng chọn camera khác.
    CameraThread sẽ nhận yêu cầu và thực hiện chuyển đổi.
    """
    shared_state.request_camera_switch(request.source, request.label)
    logger.info(f"Yêu cầu chuyển camera: source={request.source}, label={request.label}")
    return {"status": "ok", "message": f"Đang chuyển sang camera: {request.label}", "source": request.source, "label": request.label}


# ════════════════════════════════════════════════════════════════════════
# ENDPOINT WEBSOCKET
# ════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """
    WebSocket endpoint gửi trạng thái bàn tay + cử chỉ theo thời gian thực.
    Tần suất gửi: ~10 lần/giây (mỗi 100ms).
    """
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.info(f"WebSocket client kết nối. Tổng: {len(_ws_clients)}")

    try:
        while True:
            # Lấy trạng thái mới nhất từ shared_state
            status = shared_state.get_full_status()

            # Gửi qua WebSocket dạng JSON
            await websocket.send_json(status)

            # Đợi 100ms trước khi gửi cập nhật tiếp theo
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        logger.info("WebSocket client ngắt kết nối")
    except Exception as e:
        logger.error(f"Lỗi WebSocket: {e}")
    finally:
        _ws_clients.discard(websocket)
        logger.info(f"WebSocket client rời đi. Tổng: {len(_ws_clients)}")


# ════════════════════════════════════════════════════════════════════════
# TIỆN ÍCH
# ════════════════════════════════════════════════════════════════════════

def _generate_placeholder_frame() -> bytes:
    """
    Tạo khung hình placeholder màu đen với chữ "Đang chờ camera...".
    Trả về bytes JPEG.
    """
    import cv2
    import numpy as np

    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(
        placeholder,
        "Dang cho camera...",
        (120, 250),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
    )
    _, jpeg = cv2.imencode(".jpg", placeholder, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return jpeg.tobytes()


def setup_static_files():
    """Gắn thư mục frontend để phục vụ file tĩnh (CSS, JS)."""
    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Gắn static files ngay khi module được import ───────────────────────
setup_static_files()
