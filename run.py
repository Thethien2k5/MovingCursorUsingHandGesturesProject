"""
Trình khởi chạy một lệnh duy nhất cho toàn bộ dự án Chuột Ảo AI.
- Khởi động Backend (xử lý camera + điều khiển chuột + web server).
- Thử mở trình duyệt frontend; nếu thất bại, BE vẫn chạy bình thường.
- Mặc định dùng camera laptop (camera_index=0).

Cách chạy:
    python run.py
"""

import sys
import threading
from pathlib import Path

# Thêm thư mục src vào đường dẫn để import các module nội bộ
sys.path.insert(0, str(Path(__file__).parent / "src"))

from main import main

if __name__ == "__main__":
    # ── Cố gắng mở trình duyệt sau khi server khởi động ────────────
    # Nếu không mở được (không có trình duyệt, headless, ...), bỏ qua
    try:
        import webbrowser

        def open_browser():
            import time
            # Chờ server khởi động (uvicorn chạy trong luồng riêng của main)
            time.sleep(2)
            webbrowser.open("http://localhost:8000")

        threading.Thread(target=open_browser, daemon=True, name="BrowserOpener").start()
    except Exception:
        pass

    # ── Chạy engine chính ─────────────────────────────────────────
    exit_code = main()
    sys.exit(exit_code)
