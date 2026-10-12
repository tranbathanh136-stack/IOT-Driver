import time
from core.state import app_state, system_config
from core.alarm_service import alarm_service

class AlertManager:
    """
    [ĐỊNH TUYẾN & TẬP TRUNG HÓA CẢNH BÁO AN TOÀN]
    Tích hợp dữ liệu từ cả AI Vision (Ngủ gật, ngáp, điện thoại, tư thế)
    và IoT Node (Khí CO2 trong khoang xe).
    """
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.last_alert_time = 0.0
        self.last_alert_level = None
        self.debounce_sec = 2.0
        score_cfg = system_config.get("safety_score", {})
        self.deduct_warning = score_cfg.get("deduct_warning", 2)
        self.deduct_critical = score_cfg.get("deduct_critical", 5)

    def set_socketio(self, socketio):
        self.socketio = socketio

    def emit_alert(self, level: str, source: str, message: str, sound_trigger: bool = True):
        now = time.time()
        # Chống spam cảnh báo trùng lặp trong debounce window (2 giây) cùng mức độ
        if (now - self.last_alert_time < self.debounce_sec) and (self.last_alert_level == level):
            return

        self.last_alert_time = now
        self.last_alert_level = level
        deduct = self.deduct_critical if level == "CRITICAL" else self.deduct_warning
        new_score = app_state.deduct_score(deduct)

        timestamp_str = time.strftime("%H:%M:%S")
        alert_payload = {
            "level": level,
            "source": source,
            "message": message,
            "timestamp": timestamp_str,
            "deduct_score": deduct,
            "current_score": new_score
        }

        app_state.active_alert = alert_payload

        # Kích hoạt chuông còi nếu cần
        if sound_trigger and (level == "CRITICAL"):
            alarm_service.trigger(reason=message)

        # Phát qua WebSocket
        if self.socketio:
            self.socketio.emit("alert_event", alert_payload)
            self.socketio.emit("score_update", {"score": new_score})

alert_manager = AlertManager()
