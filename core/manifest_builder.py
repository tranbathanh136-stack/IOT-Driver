import time
import json
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
import numpy as np

from core.ring_buffer import video_ring_buffer
from core.state import app_state

class ManifestBuilder:
    """
    [BƯỚC 5: TẠO MANIFEST BẰNG CHỨNG & ĐỒNG BỘ QUẢN LÝ (PROOF & SYNC)]
    - Đóng gói file JSON Manifest (~1KB) kèm ảnh Base64 Best-Eyes (~50KB).
    - Thay thế hoàn toàn việc upload video 40MB gây nghẽn băng thông 4G trên xe.
    - Ghi nhận lịch sử tương thích schema IOT_LOGS và cập nhật trừ điểm DRIVERS.
    """
    def __init__(self, log_dir=None):
        if log_dir is None:
            self.log_dir = Path(__file__).resolve().parent.parent / "logs"
        else:
            self.log_dir = Path(log_dir)

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_log_path = self.log_dir / "incidents_manifest.jsonl"

    def build_and_save_manifest(
        self,
        event_type: str,
        severity_level: str,
        reason: str,
        duration: float,
        co2_ppm: float,
        v_start_time: float,
        deduct_points: int,
        socketio=None
    ) -> Dict[str, Any]:
        now = time.time()
        incident_id = f"INC_{time.strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:6].upper()}"

        # 1. Trích xuất Best-Eyes Snapshot từ Ring Buffer trên RAM
        best_frame, min_ear, best_ts = video_ring_buffer.extract_best_eyes(v_start_time, now)
        snapshot_b64 = video_ring_buffer.frame_to_base64_jpeg(best_frame, quality=70) if best_frame is not None else ""

        # 2. Cấu trúc Manifest chuẩn hóa
        manifest = {
            "incident_id": incident_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": event_type,
            "severity_level": severity_level,
            "reason": reason,
            "telemetry": {
                "duration_sec": round(duration, 1),
                "min_ear": round(min_ear, 2) if min_ear != 1.0 else None,
                "co2_ppm": round(co2_ppm, 1),
                "best_frame_ts": round(best_ts, 2)
            },
            "deduct_points": deduct_points,
            "driver_score_after": app_state.safety_score,
            "snapshot_base64": snapshot_b64
        }

        # 3. Ghi vào file nhật ký Manifest JSONL
        try:
            with open(self.manifest_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(manifest, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[Manifest Error] Không thể lưu file manifest: {e}")

        # 4. Phát sự kiện qua Socket.IO để Dashboard hiển thị Popup ảnh bằng chứng
        if socketio:
            socketio.emit("incident_manifest", {
                "incident_id": incident_id,
                "timestamp": manifest["timestamp"],
                "event_type": event_type,
                "severity_level": severity_level,
                "reason": reason,
                "deduct_points": deduct_points,
                "driver_score": app_state.safety_score,
                "snapshot_base64": snapshot_b64
            })

        return manifest

manifest_builder = ManifestBuilder()
