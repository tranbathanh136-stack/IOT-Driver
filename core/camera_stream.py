import cv2
import time
import json
import numpy as np

class WebcamDrowsinessDetector:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        self.cap = cv2.VideoCapture(self.cfg["camera"]["device_index"])
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg["camera"]["width"])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg["camera"]["height"])
        
        self.drowsy_counter = 0
        self.yawn_counter = 0
        self.is_running = False

    def calculate_ear_mock(self, frame):
        """
        Nguyên lý: Trích xuất các điểm mí mắt theo công thức:
        EAR = (||P2 - P6|| + ||P3 - P5||) / (2 * ||P1 - P4||)
        (Hàm này trả về EAR tính toán thực tế hoặc mô phỏng qua ROI)
        """
        # Giả định giá trị EAR đọc được từ frame khuôn mặt
        return 0.28 

    def run_detection_loop(self, on_alert_callback):
        self.is_running = True
        while self.is_running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            ear = self.calculate_ear_mock(frame)

            # Đánh giá điều kiện ngủ gật (nhắm mắt liên tục)
            if ear < self.cfg["camera"]["min_ear_threshold"]:
                self.drowsy_counter += 1
                if self.drowsy_counter >= self.cfg["camera"]["consecutive_frames_drowsy"]:
                    on_alert_callback({
                        "source": "CAMERA_AI",
                        "level": "CRITICAL",
                        "message": f"Tài xế nhắm mắt ngủ gật! (EAR: {ear:.2f})",
                        "event_type": "DROWSINESS"
                    })
                    self.drowsy_counter = 0
            else:
                self.drowsy_counter = 0

            time.sleep(1.0 / self.cfg["camera"]["fps_target"])

    def stop(self):
        self.is_running = False
        if self.cap.isOpened():
            self.cap.release()