import json
import os
from collections import deque
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[State Config Error] {e}")
    # Default fallback
    return {
        "camera": {"device_index": 0, "width": 640, "height": 480, "target_fps": 30},
        "models": {
            "yolo_drowsiness": "models/best.pt",
            "yolo_pose": "models/yolo26n-pose.pt",
            "yolo_distraction": "models/yolov8n.pt",
            "enable_pose_detection": True,
            "enable_distraction_detection": True,
            "confidence_threshold": 0.40
        },
        "temporal_logic": {
            "closed_eye_seconds": 1.5,
            "yawn_seconds": 1.5,
            "phone_seconds": 1.0,
            "bad_posture_seconds": 2.0
        },
        "alarm": {
            "enabled": True,
            "sound_file": "assets/alarm.wav",
            "cooldown_seconds": 3.0
        },
        "sensor_co2": {
            "safe_threshold": 800.0,
            "warning_threshold": 1000.0,
            "critical_threshold": 1500.0,
            "auto_start_virtual_node": True
        },
        "safety_score": {
            "initial_score": 100,
            "deduct_warning": 2,
            "deduct_critical": 5
        }
    }

system_config = load_config()

# [THIẾT KẾ: BỘ NHỚ LỊCH SỬ DEQUE CHỐNG TRÀN RAM CHO HỆ THỐNG IOT]
history_drowsiness = deque(maxlen=200)
history_yawning = deque(maxlen=200)
history_distraction = deque(maxlen=200)
history_posture = deque(maxlen=200)
history_co2 = deque(maxlen=200)

class AppState:
    def __init__(self):
        self.last_alert_time = 0.0
        self.global_frame = None
        self.safety_score = system_config.get("safety_score", {}).get("initial_score", 100)
        self.latest_co2 = 450.0
        self.latest_co2_level = "SAFE"
        self.latest_adc = 0
        self.latest_src = "NONE"
        self.latest_ai_status = "SAFE"
        self.active_alert = None
        self.is_camera_connected = False
        self.is_hardware_muted = False
        self.mute_expire_time = 0.0
        self.is_warming_up = False
        self.esp32_r0 = 76.63

    def deduct_score(self, points):
        self.safety_score = max(0, self.safety_score - points)
        return self.safety_score

    def restore_score(self, points=1):
        max_score = system_config.get("safety_score", {}).get("initial_score", 100)
        self.safety_score = min(max_score, self.safety_score + points)
        return self.safety_score

app_state = AppState()
