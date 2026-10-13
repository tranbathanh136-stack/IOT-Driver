import os
from pathlib import Path
import cv2
import numpy as np

class VisionDetector:
    def __init__(self, models_dir="models"):
        models_path = Path(models_dir)
        if not models_path.is_absolute() and not models_path.exists():
            base_dir = Path(__file__).resolve().parent.parent
            resolved = base_dir / models_dir
            if resolved.exists():
                models_path = resolved
        models_dir_str = str(models_path)
        self.task_path = os.path.join(models_dir_str, "face_landmarker.task")
        self.yolo_path = os.path.join(models_dir_str, "best.pt")
        self.yolo_model = None
        
        # Nạp YOLO nếu file tồn tại
        if os.path.exists(self.yolo_path):
            try:
                from ultralytics import YOLO
                self.yolo_model = YOLO(self.yolo_path)
                print(f"[AI Vision] Đã nạp thành công YOLO từ {self.yolo_path}")
            except Exception as e:
                print(f"[AI Vision] Chưa thể nạp YOLO: {e}")

        # Kiểm tra file task MediaPipe
        if os.path.exists(self.task_path):
            print(f"[AI Vision] Tìm thấy MediaPipe Task: {self.task_path}")
        else:
            print(f"[AI Vision] Chú ý: Chưa thấy file {self.task_path}")

    def compute_ear_mock(self, frame):
        """Mô phỏng trích xuất điểm mốc và tính EAR thời gian thực"""
        # Trả về giá trị EAR giả định (0.28: tỉnh táo; < 0.20: buồn ngủ)
        return 0.26