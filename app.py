import sys
import time
import threading
from flask import Flask, request, g
from flask_socketio import SocketIO

# Import hệ thống quản lý log HTTP và Báo cáo độc lập
from core.http_reporter import http_reporter
from core.error_handlers import register_error_handlers
from core.routes import register_routes
from core.camera_service import start_camera_loop
from core.arduino_node import arduino_node
from core.state import system_config

app = Flask(__name__)
app.config["SECRET_KEY"] = "yolo26_fleet_secret_ai_iot"

# [THIẾT KẾ: GIAO TIẾP THỜI GIAN THỰC WEBSOCKET]
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# =========================================================================
# [BỘ LỌC HTTP CHUYÊN BIỆT: CHUYỂN TOÀN BỘ LOG REQUEST VÀO FILE NHẬT KÝ BÁO CÁO]
# Giữ cho Terminal console hoàn toàn sạch sẽ, không bị tràn dòng mỗi giây
# =========================================================================
@app.before_request
def start_timer():
    g.start_time = time.time()

@app.after_request
def log_http_quietly(response):
    duration_ms = (time.time() - getattr(g, "start_time", time.time())) * 1000
    http_reporter.log_request(
        method=request.method,
        path=request.path,
        ip=request.remote_addr or "127.0.0.1",
        status_code=response.status_code,
        duration_ms=duration_ms
    )
    return response

# Nạp hệ thống bắt lỗi (Middleware)
register_error_handlers(app)

# Nạp các đường dẫn (Routing API, Web & Báo cáo)
register_routes(app, socketio)

if __name__ == "__main__":
    # 1. Bật luồng Camera AI Siêu tốc (Zero-Lag Frame Grabber + Inference 320px)
    start_camera_loop(socketio)
    
    # 2. BẬT TIẾN TRÌNH KẾT NỐI PHẦN CỨNG ARDUINO THẬT (ĐỌC CẢM BIẾN MQ-135)
    # Đã loại bỏ hoàn toàn module giả lập ngẫu nhiên
    arduino_node.set_socketio(socketio)
    arduino_node.start()

    print("\n" + "="*70)
    print(">> [YOLO26] HỆ THỐNG GIÁM SÁT AN TOÀN TÀI XẾ & CẢM BIẾN MQ-135 THẬT <<")
    print("="*70)
    print(">> Đã cấu hình và tối ưu hóa:")
    print("   [+] Camera Zero-Lag: Tách luồng Grabber, imgsz 320x320 triệt tiêu độ trễ")
    print("   [+] Phần cứng thật: Đọc trực tiếp cảm biến MQ-135 qua Arduino IDE (Serial COM)")
    print("   [+] Điều khiển ngược: Tự động gửi SLEEP/ALERT xuống còi/buzzer trên board mạch")
    print("   [+] AI Vision: Nhắm mắt (best.pt), Điện thoại (yolov8n.pt), Tư thế (Pose)")
    print("   [+] Clean Console: Toàn bộ log HTTP lưu ngầm vào logs/http_access.log")
    print("-"*70)
    print(">> Web Dashboard Trực Tuyến:   http://127.0.0.1:5000")
    print(">> Bảng Lịch Sử Vi Phạm:       http://127.0.0.1:5000/history")
    print(">> API Báo Cáo Tổng Hợp:       http://127.0.0.1:5000/api/report/summary")
    print("="*70 + "\n")

    # Khởi chạy Web Server
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
