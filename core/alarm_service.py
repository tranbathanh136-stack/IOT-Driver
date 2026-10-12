import os
import sys
import time
import threading
from pathlib import Path
from core.state import system_config

class AlarmService:
    """
    [THIẾT KẾ ĐỘC QUYỀN TỪ TEST_1 & TEST_2]
    Phát âm thanh cảnh báo non-blocking (không làm đứng luồng chính).
    Có Cooldown Lock để tránh spam âm thanh gây khó chịu hoặc treo CPU.
    Hỗ trợ phát file WAV thật (alarm.wav) và Beep fallback.
    """
    def __init__(self):
        alarm_cfg = system_config.get("alarm", {})
        self.enabled = alarm_cfg.get("enabled", True)
        self.sound_file = Path(__file__).resolve().parent.parent / alarm_cfg.get("sound_file", "assets/alarm.wav")
        self.cooldown_seconds = alarm_cfg.get("cooldown_seconds", 3.0)
        self.last_alarm_time = 0.0
        self._lock = threading.Lock()

    def can_play(self) -> bool:
        if not self.enabled:
            return False
        return (time.time() - self.last_alarm_time) >= self.cooldown_seconds

    def trigger(self, reason: str = "Cảnh báo nguy hiểm"):
        with self._lock:
            if not self.can_play():
                return
            self.last_alarm_time = time.time()

        threading.Thread(target=self._play_sound, args=(reason,), daemon=True).start()

    def _play_sound(self, reason: str):
        played = False
        # 1. Thử dùng winsound trên Windows (chuẩn native, không cần cài đặt thêm)
        if sys.platform == "win32":
            try:
                import winsound
                if self.sound_file.exists():
                    winsound.PlaySound(str(self.sound_file), winsound.SND_FILENAME | winsound.SND_ASYNC)
                    played = True
                else:
                    winsound.Beep(1200, 400)
                    played = True
            except Exception as e:
                pass

        # 2. Thử dùng pygame (nếu môi trường có cài đặt - dùng import động để tránh lỗi linter)
        if not played and self.sound_file.exists():
            try:
                import importlib
                pygame_mixer = importlib.import_module("pygame.mixer")
                pygame_mixer.init()
                sound = pygame_mixer.Sound(str(self.sound_file))
                sound.play()
                played = True
            except Exception:
                pass

        if not played:
            # Fallback cuối cùng: Terminal Bell
            print(f"\a[ALARM AUDIO] 🚨 {reason}", flush=True)

alarm_service = AlarmService()
