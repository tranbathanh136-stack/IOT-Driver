import os
import time
import json
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime

class HTTPReportManager:
    """
    [MÔ-ĐUN CHUYÊN BIỆT: XỬ LÝ HTTP VÀ BÁO CÁO HỆ THỐNG]
    - Ẩn toàn bộ log rác / spam định kỳ trên Terminal để giữ màn hình console sạch sẽ.
    - Chuyển hướng toàn bộ lưu lượng HTTP vào file nhật ký báo cáo xoay vòng (Rotating Log).
    - Lưu trữ lịch sử Telemetry và Alert để xuất báo cáo cho quản trị viên đội xe.
    """
    def __init__(self, log_dir=None):
        if log_dir is None:
            self.log_dir = Path(__file__).resolve().parent.parent / "logs"
        else:
            self.log_dir = Path(log_dir)

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.access_log_path = self.log_dir / "http_access.log"
        self.report_data_path = self.log_dir / "telemetry_reports.jsonl"
        
        # Thống kê bộ nhớ phục vụ báo cáo nhanh
        self.stats = {
            "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_http_requests": 0,
            "telemetry_packets_received": 0,
            "alerts_critical_count": 0,
            "alerts_warning_count": 0,
            "last_co2_ppm": 0.0,
            "max_co2_ppm": 0.0
        }

        self._init_http_logger()

    def _init_http_logger(self):
        # 1. Tắt log mặc định của Werkzeug trên Terminal (Ẩn spam HTTP 200 liên tục mỗi giây)
        werkzeug_logger = logging.getLogger("werkzeug")
        werkzeug_logger.setLevel(logging.ERROR)  # Chỉ hiện khi có lỗi nghiêm trọng

        # 2. Tạo logger chuyên biệt ghi vào file xoay vòng (Tối đa 5MB, lưu 3 bản sao lưu)
        self.http_logger = logging.getLogger("yolo26_http_reporter")
        self.http_logger.setLevel(logging.INFO)
        self.http_logger.propagate = False  # Không đẩy ngược ra Terminal console

        # Xóa các handler cũ nếu có
        if self.http_logger.hasHandlers():
            self.http_logger.handlers.clear()

        handler = RotatingFileHandler(
            str(self.access_log_path),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(formatter)
        self.http_logger.addHandler(handler)

    def log_request(self, method: str, path: str, ip: str, status_code: int, duration_ms: float):
        """Ghi nhận request HTTP vào file nhật ký ngầm"""
        self.stats["total_http_requests"] += 1
        log_line = f"{ip} - {method} {path} - Status: {status_code} - {duration_ms:.1f}ms"
        self.http_logger.info(log_line)

    def record_telemetry(self, device_id: str, co2_ppm: float, level: str):
        """Lưu trữ dữ liệu cảm biến vào hệ thống báo cáo"""
        self.stats["telemetry_packets_received"] += 1
        self.stats["last_co2_ppm"] = co2_ppm
        if co2_ppm > self.stats["max_co2_ppm"]:
            self.stats["max_co2_ppm"] = co2_ppm

        if level == "CRITICAL":
            self.stats["alerts_critical_count"] += 1
        elif level == "WARNING":
            self.stats["alerts_warning_count"] += 1

        # Ghi log dạng JSON Lines (tiện cho việc parse dữ liệu làm báo cáo CSV / Excel / BI)
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "device_id": device_id,
                "co2_ppm": co2_ppm,
                "level": level
            }
            with open(self.report_data_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_summary(self):
        """Trả về dữ liệu tổng hợp để hiển thị trên API báo cáo"""
        return {
            "status": "success",
            "uptime_since": self.stats["start_time"],
            "metrics": {
                "total_requests": self.stats["total_http_requests"],
                "telemetry_packets": self.stats["telemetry_packets_received"],
                "alerts_critical": self.stats["alerts_critical_count"],
                "alerts_warning": self.stats["alerts_warning_count"],
                "latest_co2": self.stats["last_co2_ppm"],
                "peak_co2": self.stats["max_co2_ppm"]
            },
            "log_files": {
                "access_log": str(self.access_log_path),
                "report_data": str(self.report_data_path)
            }
        }

# Khởi tạo thể hiện dùng chung
http_reporter = HTTPReportManager()
