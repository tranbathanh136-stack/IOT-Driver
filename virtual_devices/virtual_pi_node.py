import time
import random
import threading
import requests
from core.state import system_config

class VirtualRaspberryPiNode:
    """
    [THIẾT BỊ IOT ẢO - RASPBERRY PI NODE ĐƯỢC NÂNG CẤP]
    Mô phỏng cảm biến chất lượng không khí cabin xe (CO2 ppm - MQ135)
    và bộ chấp hành ảo (Actuator: Còi buzzer, đèn LED báo trạng thái).
    Tự động kết nối với API Webhook của YOLO26.
    """
    def __init__(self, target_api="http://127.0.0.1:5000/api/iot/telemetry"):
        self.target_api = target_api
        self.device_id = "VIRTUAL_PI_YOLO26"
        self.current_co2 = 550.0  # Mức CO2 cơ sở trong cabin
        self.is_running = False
        self.virtual_buzzer = False
        self.virtual_led = "GREEN"

    def handle_actuator_feedback(self, ack_level):
        """Phản hồi còi, LED ảo trên phần cứng Raspberry Pi"""
        if ack_level == "CRITICAL":
            self.virtual_led = "RED"
            self.virtual_buzzer = True
            print(f"[{self.device_id}] 🚨 BUZZER KÊU TO! LED ĐỎ! Kích hoạt quạt thông gió & mô-tơ rung ghế.")
        elif ack_level == "WARNING":
            self.virtual_led = "YELLOW"
            self.virtual_buzzer = False
            print(f"[{self.device_id}] ⚠️ PHÁT LOA NHẮC NHỞ! LED VÀNG (Cảnh báo vi khí hậu).")
        else:
            self.virtual_led = "GREEN"
            self.virtual_buzzer = False

    def loop_telemetry(self):
        self.is_running = True
        print(f"[{self.device_id}] Bắt đầu gửi dữ liệu cảm biến CO2 lên hệ thống định kỳ 1s...")
        while self.is_running:
            # Mô phỏng biến thiên nồng độ khí CO2 thực tế
            self.current_co2 += random.uniform(-8.0, 12.0)
            self.current_co2 = max(400.0, min(2200.0, self.current_co2))

            payload = {
                "device_id": self.device_id,
                "co2_ppm": round(self.current_co2, 2),
                "timestamp": time.time()
            }
            try:
                resp = requests.post(self.target_api, json=payload, timeout=0.8)
                if resp.status_code == 200:
                    ack = resp.json().get("ack_level", "SAFE")
                    self.handle_actuator_feedback(ack)
            except Exception:
                pass  # Chống sập nếu server backend chưa sẵn sàng

            time.sleep(1.0)

    def start(self):
        t = threading.Thread(target=self.loop_telemetry, daemon=True)
        t.start()

def auto_start_if_enabled():
    sensor_cfg = system_config.get("sensor_co2", {})
    if sensor_cfg.get("auto_start_virtual_node", True):
        # Đợi một chút để server Flask khởi động trước khi bắn telemetry
        def delayed_start():
            time.sleep(2.0)
            node = VirtualRaspberryPiNode()
            node.start()
        threading.Thread(target=delayed_start, daemon=True).start()
