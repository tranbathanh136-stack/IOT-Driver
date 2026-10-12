import cv2
import math
from ultralytics import YOLO

class RealVisionDetector:
    def __init__(self, camera_source=0):
        """
        [MỤC ĐÍCH KHỞI TẠO]
        Module này chịu trách nhiệm kết nối với Camera và chạy mô hình AI (YOLO)
        để nhận diện trạng thái của tài xế (Nhắm mắt, Ngáp...).
        """
        self.camera_source = camera_source
        # Khởi tạo đối tượng VideoCapture của OpenCV để lấy hình ảnh từ webcam (số 0 là cam mặc định)
        self.cap = cv2.VideoCapture(camera_source)
        
        # [THIẾT KẾ: KHUNG THOÁT HIỂM / ISOLATION]
        # Nếu camera bị lỗi (ai đó rút dây cáp), ta in ra lỗi và bỏ qua chứ không dùng raise Exception,
        # điều này giúp tránh việc toàn bộ ứng dụng Flask bị sập theo.
        if not self.cap.isOpened():
            print(f"[Isolate Error] Lỗi: Không thể mở camera {camera_source}. Bỏ qua module này để tránh sập liên lụy.")
            
        try:
            # [THIẾT KẾ: DÙNG YOLO THAY VÌ MEDIAPIPE]
            # YOLOv8 (ultralytics) hoạt động cực kì ổn định trên Python 3.14+ (ngược với mediapipe hay bị lỗi file config).
            # Nó trực tiếp nhận diện các Object như "Drowsy eye" (mắt buồn ngủ), "Yawn" (ngáp).
            self.model = YOLO("model/best.pt")
            print("[Vision AI] Đã nạp thành công mô hình YOLO best.pt")
        except Exception as e:
            print(f"[Isolate Error] Lỗi nạp mô hình YOLO: {e}")
            self.model = None
            
    def process_frame(self):
        """
        [QUY TRÌNH XỬ LÝ TỪNG KHUNG HÌNH (FRAME)]
        Hàm này được gọi liên tục (nhiều lần mỗi giây) bởi một vòng lặp bên app.py.
        Nó trả về hình ảnh đã vẽ khung (bounding box) và 2 chỉ số ảo (EAR, MAR) để báo động.
        """
        if not self.cap.isOpened():
            return None

        # 1. Đọc một khung hình thô từ Camera
        ret, frame = self.cap.read()
        if not ret:
            return None
            
        # Trạng thái mặc định ban đầu: Tỉnh táo (EAR cao) và Không ngáp (MAR thấp)
        state = {"ear": 0.30, "mar": 0.10, "posture_warning": False, "frame": frame}
        
        if self.model is None:
            return state

        try:
            # 2. Đưa hình ảnh vào mô hình AI để dự đoán (predict)
            results = self.model(frame, verbose=False)
            
            is_drowsy = False
            is_yawning = False
            
            # 3. Vẽ luôn các khung nhận diện (ô vuông) lên bức ảnh để tí nữa Web hiển thị trực quan
            annotated_frame = results[0].plot()
            
            # 4. Quét qua tất cả các đối tượng (khuôn mặt, mắt, miệng) mà AI tìm thấy
            for box in results[0].boxes:
                cls_id = int(box.cls[0])           # ID của nhãn
                conf = float(box.conf[0])          # Độ tự tin (Confidence score: từ 0.0 đến 1.0)
                name = self.model.names[cls_id].lower() # Tên nhãn (Ví dụ: 'yawn', 'drowsy eye')
                
                # [THIẾT KẾ: ĐỘ TIN CẬY (CONFIDENCE THRESHOLD)]
                # Chỉ tin tưởng các kết quả AI chắc chắn > 40% để tránh báo động giả (False Positive)
                if conf > 0.4:
                    # Gom nhóm các nhãn liên quan đến Nhắm mắt / Buồn ngủ
                    if name in ['drowsy eye', 'eyeclosed', 'asleep', 'close', 'closed']:
                        is_drowsy = True
                    # Gom nhóm các nhãn liên quan đến Há miệng / Ngáp
                    if name in ['open-mouth', 'yawn']:
                        is_yawning = True
            
            # [THIẾT KẾ: MÔ PHỎNG EAR / MAR CHO TƯƠNG THÍCH]
            # Thay vì tính toán công thức hình học phức tạp như MediaPipe, ta dùng thẳng kết quả YOLO.
            # Nhưng để tương thích với hệ thống đếm ngược ở app.py, ta gán ngược lại thành hệ số:
            # EAR < 0.22 được quy ước là buồn ngủ -> Gán 0.10
            # MAR > 0.50 được quy ước là ngáp -> Gán 0.80
            state["ear"] = 0.10 if is_drowsy else 0.30
            state["mar"] = 0.80 if is_yawning else 0.20
            state["frame"] = annotated_frame
            
            return state
        except Exception as e:
            # Ngắt đoạn (Circuit Breaker) nếu AI bị lỗi xử lý 1 khung hình, tránh làm sập luồng
            print(f"[Isolate Error] Lỗi xử lý frame YOLO: {e}")
            return None

    def release(self):
        # Đóng tài nguyên Camera khi tắt ứng dụng để camera không bị treo (đèn webcam không sáng mãi)
        if self.cap.isOpened():
            self.cap.release()
