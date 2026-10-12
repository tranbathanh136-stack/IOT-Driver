import time
from typing import Dict, Any, Optional
from core.state import app_state, system_config
from core.arduino_node import arduino_node

class DecisionFusionEngine:
    """
    [BƯỚC 3: HỢP NHẤT QUYẾT ĐỊNH & MÁY TRẠNG THÁI (FUSION STATE MACHINE)]
    - Hợp nhất tín hiệu AI thị giác (Mắt, Ngáp, Điện thoại, Tư thế) và Dữ liệu môi trường CO2 từ ESP32.
    - Ma trận 3 cấp độ:
      * LV0 (SAFE): Mọi chỉ số an toàn. Gửi STOP tắt còi.
      * LV1 (WARNING): Ngáp > 2s HOẶC 1000 <= CO2 <= 1500 ppm. Lệnh ALERT:1:5000, trừ 2 điểm.
      * LV2 (CRITICAL): Mắt nhắm > 1.5s HOẶC CO2 > 1500 ppm HOẶC CỘNG HƯỞNG (CO2 > 1200 + Ngáp). Lệnh SLEEP, trừ 5 điểm.
    """
    def __init__(self):
        sensor_cfg = system_config.get("sensor_co2", {})
        self.co2_warning_threshold = sensor_cfg.get("warning_threshold", 1000.0)
        self.co2_critical_threshold = sensor_cfg.get("critical_threshold", 1500.0)
        self.last_sent_cmd: Optional[str] = None
        self.last_level: str = "LV0"

    def evaluate(self, ai_eval: Dict[str, Any], co2_ppm: float) -> Dict[str, Any]:
        ai_status = ai_eval.get("status", "SAFE")
        event_type = ai_eval.get("event_type")
        duration = ai_eval.get("duration", 0.0)
        yawn_dur = ai_eval.get("yawn_duration", 0.0)
        is_leading_edge = ai_eval.get("is_leading_edge", False)
        can_play_buzzer = ai_eval.get("can_play_buzzer", False)
        can_log_db = ai_eval.get("can_log_db", False)

        final_level = "LV0"
        hardware_cmd = "STOP"
        reason = "Hệ thống vận hành an toàn"
        severity = "SAFE"
        deduct_points = 0
        trigger_sound = False
        is_compound = False

        # 1. ĐÁNH GIÁ MỨC NGUY HIỂM CAO NHẤT (LV2 - CRITICAL)
        if ai_status == "CRITICAL":
            final_level = "LV2"
            severity = "CRITICAL"
            hardware_cmd = "SLEEP" if event_type == "DROWSINESS" else "ALERT:2:5000"
            reason = ai_eval.get("reason", "Cảnh báo khẩn cấp từ AI!")
            deduct_points = 5
            trigger_sound = can_play_buzzer

        elif co2_ppm >= self.co2_critical_threshold:
            final_level = "LV2"
            severity = "CRITICAL"
            hardware_cmd = "ALERT:2:5000"
            reason = f"Cabin thiếu oxy nghiêm trọng! CO2 đạt {co2_ppm:.1f} ppm"
            deduct_points = 5
            trigger_sound = True

        # ĐIỀU KIỆN CỘNG HƯỞNG NGUY HIỂM (Compound Risk):
        # CO2 vùng ngột ngạt (> 1200 ppm) kết hợp tài xế bắt đầu ngáp (> 1.5s)
        elif co2_ppm >= 1200.0 and yawn_dur >= 1.5:
            final_level = "LV2"
            severity = "CRITICAL"
            hardware_cmd = "SLEEP"
            reason = f"Cộng hưởng nguy hiểm: CO2 {co2_ppm:.0f} ppm kết hợp ngáp mệt mỏi!"
            deduct_points = 5
            trigger_sound = can_play_buzzer
            is_compound = True

        # 2. ĐÁNH GIÁ MỨC CẢNH BÁO (LV1 - WARNING)
        elif ai_status == "WARNING":
            final_level = "LV1"
            severity = "WARNING"
            hardware_cmd = "ALERT:1:5000"
            reason = ai_eval.get("reason", "Cảnh báo hành vi tài xế!")
            deduct_points = 2
            trigger_sound = False

        elif co2_ppm >= self.co2_warning_threshold:
            final_level = "LV1"
            severity = "WARNING"
            hardware_cmd = "ALERT:1:4000"
            reason = f"Không khí cabin ngột ngạt ({co2_ppm:.1f} ppm) - Hãy lấy gió ngoài"
            deduct_points = 2
            trigger_sound = False

        # 3. MỨC BÌNH THƯỜNG (LV0 - SAFE)
        else:
            final_level = "LV0"
            severity = "SAFE"
            hardware_cmd = "STOP"
            reason = "Tài xế tỉnh táo & Không khí cabin tốt"

        # GỬI LỆNH ĐIỀU KHIỂN PHẦN CỨNG BẤT ĐỒNG BỘ (BƯỚC 4)
        if final_level != "LV0":
            if is_leading_edge or trigger_sound or (self.last_level != final_level):
                arduino_node.send_command(hardware_cmd)
                self.last_sent_cmd = hardware_cmd
        else:
            if self.last_level != "LV0":
                arduino_node.send_command("STOP")
                self.last_sent_cmd = "STOP"

        self.last_level = final_level

        return {
            "level": final_level,
            "severity": severity,
            "hardware_cmd": hardware_cmd,
            "reason": reason,
            "deduct_points": deduct_points,
            "trigger_sound": trigger_sound,
            "is_compound": is_compound,
            "is_leading_edge": is_leading_edge,
            "can_log_db": can_log_db
        }

decision_fusion = DecisionFusionEngine()
