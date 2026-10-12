import math
import time
import cv2
import threading
import numpy as np
from pathlib import Path
from ultralytics import YOLO
from core.state import system_config

class UnifiedDriverDetector:
    """
    [KIẾN TRÚC ZERO-LAG: TRIỆT TIÊU HOÀN TOÀN ĐỘ TRỄ CAMERA]
    1. Tách biệt Thread Grabber: Luồng chuyên đọc camera ghi đè frame mới nhất,
       loại bỏ hoàn toàn bộ đệm hàng đợi (Buffer Queue) của OpenCV gây delay vài giây.
    2. Tối ưu suy luận AI CPU: Giảm imgsz xuống 320x320 cho tốc độ xử lý siêu tốc (< 20ms).
    3. Hợp nhất 3 mô hình: Buồn ngủ (best.pt), Điện thoại (yolov8n.pt), Tư thế (yolo26n-pose.pt).
    """
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        
        # Cấu hình camera
        cam_cfg = system_config.get("camera", {})
        models_cfg = system_config.get("models", {})
        base_dir = Path(__file__).resolve().parent.parent

        # 1. Khởi tạo VideoCapture với cấu hình chống đệm (Zero Buffer)
        self.cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW) if cv2.CAP_DSHOW else cv2.VideoCapture(camera_index)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(camera_index)

        if self.cap.isOpened():
            # Yêu cầu webcam mở ở độ phân giải cao (Mặc định 1280x720 HD)
            req_w = cam_cfg.get("width", 1280)
            req_h = cam_cfg.get("height", 720)
            try:
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
            except Exception:
                pass
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, req_w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, req_h)
            self.cap.set(cv2.CAP_PROP_FPS, cam_cfg.get("target_fps", 30))
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Giữ buffer = 1 frame duy nhất chống trễ

            actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"[Camera AI] ✅ Đã kích hoạt độ phân giải Camera: {actual_w}x{actual_h}")

        # Biến chia sẻ khung hình tức thì
        self.latest_raw_frame = None
        self._is_running = True
        self._frame_lock = threading.Lock()

        # 2. Nạp Model Drowsiness (best.pt)
        drowsy_path = base_dir / models_cfg.get("yolo_drowsiness", "models/best.pt")
        try:
            self.model_drowsy = YOLO(str(drowsy_path)) if drowsy_path.exists() else None
            print(f"[YOLO26] Đã nạp Model Buồn ngủ: {drowsy_path.name}")
        except Exception as e:
            print(f"[YOLO26 Error] Không thể nạp model buồn ngủ: {e}")
            self.model_drowsy = None

        # 3. Nạp Model Distraction (yolov8n.pt)
        distract_path = base_dir / models_cfg.get("yolo_distraction", "models/yolov8n.pt")
        self.enable_distraction = models_cfg.get("enable_distraction_detection", True)
        try:
            self.model_distract = YOLO(str(distract_path)) if (self.enable_distraction and distract_path.exists()) else None
            if self.model_distract:
                print(f"[YOLO26] Đã nạp Model Phân tâm (Điện thoại): {distract_path.name}")
        except Exception as e:
            self.model_distract = None

        # 4. Nạp Model Pose (yolo26n-pose.pt)
        pose_path = base_dir / models_cfg.get("yolo_pose", "models/yolo26n-pose.pt")
        self.enable_pose = models_cfg.get("enable_pose_detection", False)  # Tắt mặc định hoặc bật theo chu kỳ để giữ FPS cao
        try:
            self.model_pose = YOLO(str(pose_path)) if (self.enable_pose and pose_path.exists()) else None
            if self.model_pose:
                print(f"[YOLO26] Đã nạp Model Tư thế (Pose): {pose_path.name}")
        except Exception as e:
            self.model_pose = None

        self.conf_threshold = models_cfg.get("confidence_threshold", 0.40)
        self.inference_size = cam_cfg.get("inference_size", 320)  # 320x320 chạy siêu nhẹ trên CPU
        self.frame_count = 0

        # Khởi chạy luồng Frame Grabber chuyên biệt để xả sạch buffer camera
        self._grabber_thread = threading.Thread(target=self._grab_frames_routine, daemon=True)
        self._grabber_thread.start()

    def _grab_frames_routine(self):
        """Luồng đọc camera tốc độ cao liên tục xả buffer, đảm bảo 0ms độ trễ"""
        while self._is_running:
            if not self.cap or not self.cap.isOpened():
                time.sleep(0.1)
                continue
            ret, frame = self.cap.read()
            if ret and frame is not None:
                with self._frame_lock:
                    self.latest_raw_frame = frame
            else:
                time.sleep(0.01)

    def is_camera_open(self) -> bool:
        return self.cap is not None and self.cap.isOpened()

    def process_frame(self):
        # Lấy khung hình mới nhất tại microsecond hiện tại (Không bao giờ lấy frame cũ từ buffer)
        with self._frame_lock:
            if self.latest_raw_frame is None:
                return None
            frame = self.latest_raw_frame.copy()

        self.frame_count += 1
        h, w, _ = frame.shape
        annotated_frame = frame.copy()

        is_drowsy = False
        is_yawning = False
        is_phone = False
        is_bad_posture = False
        posture_detail = "Tư thế chuẩn"

        # 1. PHÁT HIỆN BUỒN NGỦ & NGÁP (best.pt - Kích thước tối ưu 320 siêu tốc)
        if self.model_drowsy:
            try:
                results_drowsy = self.model_drowsy.predict(
                    frame,
                    conf=self.conf_threshold,
                    imgsz=self.inference_size,
                    verbose=False
                )
                if results_drowsy and len(results_drowsy) > 0:
                    r0 = results_drowsy[0]
                    for box in r0.boxes:
                        cls_id = int(box.cls[0].item())
                        conf = float(box.conf[0].item())
                        label = self.model_drowsy.names.get(cls_id, "").lower().replace("-", "").replace("_", "").replace(" ", "")
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

                        if any(k in label for k in ["drowsy", "eyeclose", "close", "asleep"]):
                            is_drowsy = True
                            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                            cv2.putText(annotated_frame, f"Closed {conf:.2f}", (x1, max(20, y1 - 6)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                        elif any(k in label for k in ["yawn", "openmouth"]):
                            is_yawning = True
                            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 200, 255), 2)
                            cv2.putText(annotated_frame, f"Yawn {conf:.2f}", (x1, max(20, y1 - 6)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
                        elif "open" in label or "attentive" in label:
                            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(annotated_frame, f"Active {conf:.2f}", (x1, max(20, y1 - 6)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            except Exception as e:
                pass

        # 2. PHÁT HIỆN ĐIỆN THOẠI (yolov8n.pt - chạy xen kẽ mỗi 3 frames)
        if self.model_distract and (self.frame_count % 3 == 0 or is_phone):
            try:
                results_distract = self.model_distract.predict(
                    frame,
                    conf=0.35,
                    imgsz=self.inference_size,
                    verbose=False,
                    classes=[67]
                )
                if results_distract and len(results_distract) > 0:
                    for box in results_distract[0].boxes:
                        is_phone = True
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                        cv2.putText(annotated_frame, "PHONE DETECTED!", (x1, max(25, y1 - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            except Exception as e:
                pass

        # 3. PHÁT HIỆN TƯ THẾ (yolo26n-pose.pt - chạy xen kẽ mỗi 5 frames)
        if self.model_pose and (self.frame_count % 5 == 0):
            try:
                results_pose = self.model_pose.predict(
                    frame,
                    conf=0.40,
                    imgsz=self.inference_size,
                    verbose=False
                )
                if results_pose and len(results_pose) > 0 and results_pose[0].keypoints is not None:
                    kpts = results_pose[0].keypoints.xy
                    if len(kpts) > 0:
                        pts = kpts[0].cpu().numpy()
                        if len(pts) >= 7:
                            nose = pts[0]
                            eye_l, eye_r = pts[1], pts[2]
                            shoulder_l, shoulder_r = pts[5], pts[6]

                            if eye_l[0] != 0 and eye_r[0] != 0:
                                dx = eye_r[0] - eye_l[0]
                                dy = eye_r[1] - eye_l[1]
                                angle = abs(math.degrees(math.atan2(dy, dx)))
                                if angle > 35 and angle < 145:
                                    is_bad_posture = True
                                    posture_detail = f"Đầu nghiêng ({int(angle)}°)"

                            if nose[1] != 0 and shoulder_l[1] != 0 and shoulder_r[1] != 0:
                                shoulder_y = (shoulder_l[1] + shoulder_r[1]) / 2.0
                                if (shoulder_y - nose[1]) < 35 and nose[1] > 0:
                                    is_bad_posture = True
                                    posture_detail = "Gục đầu về trước"
            except Exception as e:
                pass

        ear_sim = 0.12 if is_drowsy else 0.32
        mar_sim = 0.75 if is_yawning else 0.18

        return {
            "frame": frame,
            "annotated_frame": annotated_frame,
            "is_drowsy": is_drowsy,
            "is_yawning": is_yawning,
            "is_phone": is_phone,
            "is_bad_posture": is_bad_posture,
            "posture_detail": posture_detail,
            "ear": ear_sim,
            "mar": mar_sim
        }

    def release(self):
        self._is_running = False
        if self.cap and self.cap.isOpened():
            self.cap.release()
