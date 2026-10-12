import time
from dataclasses import dataclass
from typing import Optional, Dict, Any
from core.state import system_config

@dataclass
class SafetyState:
    closed_eye_started_at: Optional[float] = None
    yawn_started_at: Optional[float] = None
    phone_started_at: Optional[float] = None
    bad_posture_started_at: Optional[float] = None
    status: str = "SAFE"
    reason: str = "Tài xế tỉnh táo & an toàn"
    current_event: Optional[str] = None
    violation_start_time: Optional[float] = None

class TemporalSafetyLogic:
    """
    [BƯỚC 2: SÀNG LỌC THỜI GIAN, LEADING-EDGE TRIGGER & DUAL-TIMER DEBOUNCE]
    - Khử hoàn toàn báo động giả do phản xạ chớp mắt sinh lý (0.2s - 0.4s).
    - Ngưỡng thời gian: Mắt nhắm >= 1.5s, Ngáp >= 2.0s, Điện thoại >= 1.0s, Tư thế xấu >= 2.0s.
    - Leading-Edge Trigger: Chỉ kích hoạt sự kiện vi phạm ở frame đầu tiên chạm ngưỡng.
    - Dual-Timer Cooldown: 10s cho còi hú phần cứng, 30s cho ghi CSDL/trừ điểm để chống spam.
    """
    def __init__(self):
        cfg = system_config.get("temporal_logic", {})
        self.closed_eye_seconds = cfg.get("closed_eye_seconds", 1.5)
        self.yawn_seconds = cfg.get("yawn_seconds", 2.0)
        self.phone_seconds = cfg.get("phone_seconds", 1.0)
        self.bad_posture_seconds = cfg.get("bad_posture_seconds", 2.0)

        self.state = SafetyState()
        self.last_active_event: Optional[str] = None

        # Cooldown Timers
        self.cooldown_buzzer_sec = 10.0
        self.cooldown_db_sec = 30.0
        self.last_buzzer_time: Dict[str, float] = {}
        self.last_db_time: Dict[str, float] = {}

    def update(self, raw_signals: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
        """
        raw_signals:
            is_drowsy: bool
            is_yawning: bool
            is_phone: bool
            is_bad_posture: bool
            posture_detail: str
        """
        now = now or time.time()
        is_drowsy = raw_signals.get("is_drowsy", False)
        is_yawning = raw_signals.get("is_yawning", False)
        is_phone = raw_signals.get("is_phone", False)
        is_bad_posture = raw_signals.get("is_bad_posture", False)
        posture_detail = raw_signals.get("posture_detail", "Tư thế lệch")

        # 1. Quản lý mốc thời gian Mắt nhắm
        if is_drowsy:
            if self.state.closed_eye_started_at is None:
                self.state.closed_eye_started_at = now
        else:
            self.state.closed_eye_started_at = None

        # 2. Quản lý mốc thời gian Ngáp
        if is_yawning:
            if self.state.yawn_started_at is None:
                self.state.yawn_started_at = now
        else:
            self.state.yawn_started_at = None

        # 3. Quản lý mốc thời gian Dùng điện thoại
        if is_phone:
            if self.state.phone_started_at is None:
                self.state.phone_started_at = now
        else:
            self.state.phone_started_at = None

        # 4. Quản lý mốc thời gian Tư thế xấu (Gục đầu / Lệch người)
        if is_bad_posture:
            if self.state.bad_posture_started_at is None:
                self.state.bad_posture_started_at = now
        else:
            self.state.bad_posture_started_at = None

        # Tính thời lượng tích lũy
        eye_dur = 0.0 if self.state.closed_eye_started_at is None else now - self.state.closed_eye_started_at
        yawn_dur = 0.0 if self.state.yawn_started_at is None else now - self.state.yawn_started_at
        phone_dur = 0.0 if self.state.phone_started_at is None else now - self.state.phone_started_at
        posture_dur = 0.0 if self.state.bad_posture_started_at is None else now - self.state.bad_posture_started_at

        # Phân cấp mức độ ưu tiên
        status = "SAFE"
        reason = "Tỉnh táo & Tập trung"
        event_type = None
        duration = 0.0
        v_start = None

        if eye_dur >= self.closed_eye_seconds:
            status = "CRITICAL"
            reason = f"Ngủ gật! Nhắm mắt {eye_dur:.1f}s"
            event_type = "DROWSINESS"
            duration = eye_dur
            v_start = self.state.closed_eye_started_at
        elif phone_dur >= self.phone_seconds:
            status = "CRITICAL"
            reason = f"Phân tâm! Sử dụng điện thoại {phone_dur:.1f}s"
            event_type = "PHONE_DISTRACTION"
            duration = phone_dur
            v_start = self.state.phone_started_at
        elif yawn_dur >= self.yawn_seconds:
            status = "WARNING"
            reason = f"Ngáp mệt mỏi {yawn_dur:.1f}s"
            event_type = "YAWNING"
            duration = yawn_dur
            v_start = self.state.yawn_started_at
        elif posture_dur >= self.bad_posture_seconds:
            status = "WARNING"
            reason = f"{posture_detail} ({posture_dur:.1f}s)"
            event_type = "BAD_POSTURE"
            duration = posture_dur
            v_start = self.state.bad_posture_started_at

        # Cơ chế LEADING-EDGE TRIGGER:
        # Chỉ là leading edge khi sự kiện chuyển từ None/khác sang event_type vi phạm
        is_leading_edge = False
        if event_type is not None:
            if self.last_active_event != event_type:
                is_leading_edge = True
                self.last_active_event = event_type
        else:
            self.last_active_event = None

        # Cơ chế DUAL-TIMER DEBOUNCE:
        can_play_buzzer = False
        can_log_db = False
        if event_type is not None:
            last_buzz = self.last_buzzer_time.get(event_type, 0.0)
            if (now - last_buzz) >= self.cooldown_buzzer_sec:
                can_play_buzzer = True
                if is_leading_edge or (duration >= 2.5):
                    self.last_buzzer_time[event_type] = now

            last_db = self.last_db_time.get(event_type, 0.0)
            if (now - last_db) >= self.cooldown_db_sec:
                can_log_db = True
                if is_leading_edge:
                    self.last_db_time[event_type] = now

        self.state.status = status
        self.state.reason = reason
        self.state.current_event = event_type
        self.state.violation_start_time = v_start

        return {
            "status": status,
            "reason": reason,
            "event_type": event_type,
            "duration": round(duration, 1),
            "should_alarm": (status == "CRITICAL" and can_play_buzzer),
            "is_leading_edge": is_leading_edge,
            "can_play_buzzer": can_play_buzzer,
            "can_log_db": can_log_db,
            "violation_start_time": v_start or now,
            "eye_duration": round(eye_dur, 1),
            "yawn_duration": round(yawn_dur, 1),
            "phone_duration": round(phone_dur, 1),
            "posture_duration": round(posture_dur, 1)
        }
