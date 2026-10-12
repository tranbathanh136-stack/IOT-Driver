import time
import base64
import bisect
import cv2
import numpy as np
from collections import deque
from dataclasses import dataclass
from typing import Optional, List, Tuple

@dataclass
class BufferedFrame:
    timestamp: float
    frame: np.ndarray
    ear: float
    mar: float
    conf: float
    head_pitch: float = 0.0
    head_yaw: float = 0.0

class VideoRingBuffer:
    """
    [BƯỚC 1 & 2: RAM RING BUFFER & BEST-EYES SELECTION]
    - Quản lý bộ đệm vòng 90 khung hình trên RAM (~3 giây tại 30 FPS).
    - Bộ nhớ tiêu thụ tối đa < 30MB nhờ resize frame 640x360.
    - Quét nhị phân O(log n) trên mảng timestamp để trích xuất khung hình Best-Eyes.
    """
    def __init__(self, maxlen: int = 90):
        self.maxlen = maxlen
        self.buffer = deque(maxlen=maxlen)

    def append(self, frame: np.ndarray, ear: float, mar: float, conf: float = 1.0,
               head_pitch: float = 0.0, head_yaw: float = 0.0, now: Optional[float] = None):
        """Đưa khung hình vào Ring Buffer với chi phí O(1)"""
        ts = now if now is not None else time.time()
        # Resize nhẹ 640x360 để tiết kiệm RAM tối đa
        if frame is not None:
            h, w = frame.shape[:2]
            if w > 640:
                scale = 640.0 / w
                stored_frame = cv2.resize(frame, (640, int(h * scale)), interpolation=cv2.INTER_AREA)
            else:
                stored_frame = frame.copy()
        else:
            stored_frame = None

        item = BufferedFrame(
            timestamp=ts,
            frame=stored_frame,
            ear=ear,
            mar=mar,
            conf=conf,
            head_pitch=head_pitch,
            head_yaw=head_yaw
        )
        self.buffer.append(item)

    def get_time_window(self, start_time: float, end_time: float) -> List[BufferedFrame]:
        """Trích xuất danh sách frame trong khoảng thời gian [start_time, end_time]"""
        if not self.buffer:
            return []
        
        timestamps = [item.timestamp for item in self.buffer]
        idx_start = bisect.bisect_left(timestamps, start_time)
        idx_end = bisect.bisect_right(timestamps, end_time)
        return list(self.buffer)[idx_start:idx_end]

    def extract_best_eyes(self, start_time: float, end_time: float) -> Tuple[Optional[np.ndarray], float, float]:
        """
        [BƯỚC 2: SÀNG LỌC BEST EYES]
        Tìm khung hình có EAR cực tiểu (mắt nhắm sâu nhất) và độ tin cậy khuôn mặt cao nhất.
        Trả về: (best_frame, min_ear, best_timestamp)
        """
        frames = self.get_time_window(start_time, end_time)
        if not frames:
            # Fallback lấy frame mới nhất nếu cửa sổ rỗng
            if self.buffer and self.buffer[-1].frame is not None:
                last = self.buffer[-1]
                return last.frame, last.ear, last.timestamp
            return None, 1.0, time.time()

        # Tiêu chí: EAR càng nhỏ càng tốt, kết hợp conf cao
        # Score = ear - (conf * 0.05)
        best_item = min(frames, key=lambda x: (x.ear if x.ear > 0 else 999.0))
        return best_item.frame, best_item.ear, best_item.timestamp

    @staticmethod
    def frame_to_base64_jpeg(frame: np.ndarray, quality: int = 70) -> str:
        """Nén ảnh sang JPEG ~50KB và mã hóa Base64"""
        if frame is None:
            return ""
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        ret, buf = cv2.imencode(".jpg", frame, encode_param)
        if not ret:
            return ""
        return base64.b64encode(buf.tobytes()).decode("utf-8")

# Thể hiện dùng chung cho hệ thống
video_ring_buffer = VideoRingBuffer(maxlen=90)
