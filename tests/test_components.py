import os
import sys
import unittest
from pathlib import Path

# Thêm thư mục gốc vào PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state import load_config, app_state
from core.temporal_logic import TemporalSafetyLogic
from core.alarm_service import alarm_service
from core.unified_detector import UnifiedDriverDetector
from app import app

class TestYOLO26Components(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_01_config_loading(self):
        """Kiểm tra nạp cấu hình hệ thống"""
        cfg = load_config()
        self.assertIn("models", cfg)
        self.assertIn("temporal_logic", cfg)
        self.assertIn("alarm", cfg)
        self.assertEqual(cfg["system"]["version"], "2.6.0")

    def test_02_model_and_asset_files_exist(self):
        """Kiểm tra sự tồn tại của các file model và âm thanh đã copy"""
        base_dir = Path(__file__).resolve().parent.parent
        self.assertTrue((base_dir / "models" / "best.pt").exists(), "best.pt phải tồn tại")
        self.assertTrue((base_dir / "models" / "yolov8n.pt").exists(), "yolov8n.pt phải tồn tại")
        self.assertTrue((base_dir / "models" / "yolo26n-pose.pt").exists(), "yolo26n-pose.pt phải tồn tại")
        self.assertTrue((base_dir / "assets" / "alarm.wav").exists(), "alarm.wav phải tồn tại")

    def test_03_temporal_safety_logic(self):
        """Kiểm tra logic lọc thời gian tránh báo động giả do chớp mắt"""
        logic = TemporalSafetyLogic()

        # Frame 1: Chớp mắt tức thời (< 0.5s) -> Phải là SAFE
        res1 = logic.update({"is_drowsy": True, "is_yawning": False, "is_phone": False, "is_bad_posture": False}, now=100.0)
        self.assertEqual(res1["status"], "SAFE", "Chớp mắt tức thời không được báo động")
        self.assertFalse(res1["should_alarm"])

        # Frame 2: Nhắm mắt kéo dài 2.0s -> Phải là CRITICAL
        res2 = logic.update({"is_drowsy": True, "is_yawning": False, "is_phone": False, "is_bad_posture": False}, now=102.0)
        self.assertEqual(res2["status"], "CRITICAL", "Nhắm mắt >= 1.5s phải chuyển sang CRITICAL")
        self.assertTrue(res2["should_alarm"])

        # Frame 3: Mở mắt tỉnh lại -> Phải trả về SAFE
        res3 = logic.update({"is_drowsy": False, "is_yawning": False, "is_phone": False, "is_bad_posture": False}, now=103.0)
        self.assertEqual(res3["status"], "SAFE")

    def test_04_alarm_service_cooldown(self):
        """Kiểm tra dịch vụ âm thanh còi báo và cooldown lock"""
        self.assertTrue(alarm_service.can_play())
        alarm_service.trigger("Unit test alarm trigger")
        # Vừa kích hoạt xong thì trong 3s không được kích hoạt trùng (cooldown)
        self.assertFalse(alarm_service.can_play(), "Cooldown phải khóa không cho spam chuông liên tục")

    def test_05_api_endpoints(self):
        """Kiểm tra các endpoints REST API của Flask"""
        # Test GET /api/status
        resp_status = self.client.get("/api/status")
        self.assertEqual(resp_status.status_code, 200)
        json_status = resp_status.get_json()
        self.assertIn("safety_score", json_status)

        # Test POST /api/iot/telemetry
        resp_telemetry = self.client.post("/api/iot/telemetry", json={"co2_ppm": 650.0, "device_id": "TEST_NODE"})
        self.assertEqual(resp_telemetry.status_code, 200)
        json_tel = resp_telemetry.get_json()
        self.assertEqual(json_tel["ack_level"], "SAFE")

        # Test POST /api/demo/trigger_ai
        resp_demo = self.client.post("/api/demo/trigger_ai", json={"event": "DROWSINESS"})
        self.assertEqual(resp_demo.status_code, 200)
        self.assertEqual(resp_demo.get_json()["status"], "success")

    def test_06_http_report_system(self):
        """Kiểm tra hệ thống báo cáo HTTP độc lập"""
        resp_report = self.client.get("/api/report/summary")
        self.assertEqual(resp_report.status_code, 200)
        json_report = resp_report.get_json()
        self.assertEqual(json_report["status"], "success")
        self.assertIn("metrics", json_report)
        self.assertGreaterEqual(json_report["metrics"]["total_requests"], 1)

    def test_07_ring_buffer_and_best_eyes(self):
        """Kiểm tra Ring Buffer và thuật toán trích xuất Best-Eyes"""
        import numpy as np
        from core.ring_buffer import VideoRingBuffer
        rb = VideoRingBuffer(maxlen=10)
        dummy_frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
        dummy_frame2 = np.ones((100, 100, 3), dtype=np.uint8) * 255

        # Đẩy frame 1: EAR = 0.35
        rb.append(dummy_frame1, ear=0.35, mar=0.2, now=10.0)
        # Đẩy frame 2: EAR = 0.12 (mắt nhắm sâu nhất)
        rb.append(dummy_frame2, ear=0.12, mar=0.2, now=11.0)
        # Đẩy frame 3: EAR = 0.28
        rb.append(dummy_frame1, ear=0.28, mar=0.2, now=12.0)

        best_frame, min_ear, ts = rb.extract_best_eyes(9.5, 12.5)
        self.assertEqual(min_ear, 0.12, "Thuật toán phải tìm đúng frame có EAR cực tiểu")
        self.assertEqual(ts, 11.0)

        b64 = rb.frame_to_base64_jpeg(best_frame)
        self.assertTrue(len(b64) > 0, "Base64 string phải được tạo thành công")

    def test_08_decision_fusion_matrix(self):
        """Kiểm tra ma trận hợp nhất quyết định (Decision Fusion)"""
        from core.decision_fusion import DecisionFusionEngine
        engine = DecisionFusionEngine()

        # Trường hợp 1: Bình thường (LV0)
        res_safe = engine.evaluate({"status": "SAFE", "duration": 0.0}, co2_ppm=600.0)
        self.assertEqual(res_safe["level"], "LV0")
        self.assertEqual(res_safe["hardware_cmd"], "STOP")

        # Trường hợp 2: CO2 cao đơn lẻ (LV1)
        res_warn = engine.evaluate({"status": "SAFE", "duration": 0.0}, co2_ppm=1100.0)
        self.assertEqual(res_warn["level"], "LV1")

        # Trường hợp 3: AI Ngủ gật (LV2)
        res_crit = engine.evaluate({
            "status": "CRITICAL",
            "event_type": "DROWSINESS",
            "duration": 2.0,
            "is_leading_edge": True,
            "can_play_buzzer": True
        }, co2_ppm=600.0)
        self.assertEqual(res_crit["level"], "LV2")
        self.assertEqual(res_crit["hardware_cmd"], "SLEEP")
        self.assertEqual(res_crit["deduct_points"], 5)

        # Trường hợp 4: CỘNG HƯỞNG (CO2 > 1200 + Ngáp > 1.5s) -> Thăng hạng lên LV2
        res_compound = engine.evaluate({
            "status": "WARNING",
            "event_type": "YAWNING",
            "yawn_duration": 1.8,
            "is_leading_edge": True,
            "can_play_buzzer": True
        }, co2_ppm=1300.0)
        self.assertEqual(res_compound["level"], "LV2", "Cộng hưởng CO2 và Ngáp phải được nâng lên LV2")
        self.assertTrue(res_compound["is_compound"])

    def test_09_arduino_non_blocking_queue(self):
        """Kiểm tra hàng đợi non-blocking không bao giờ treo luồng khi mất kết nối Serial"""
        from core.arduino_node import arduino_node
        ok = arduino_node.send_command("SLEEP")
        self.assertTrue(ok, "send_command put_nowait phải trả về True ngay lập tức")
        self.assertFalse(arduino_node.cmd_queue.empty())

    def test_10_manifest_builder(self):
        """Kiểm tra đóng gói Manifest JSON và Base64"""
        from core.manifest_builder import manifest_builder
        manifest = manifest_builder.build_and_save_manifest(
            event_type="TEST_INCIDENT",
            severity_level="LV2",
            reason="Test vi phạm",
            duration=2.0,
            co2_ppm=1250.0,
            v_start_time=100.0,
            deduct_points=5
        )
        self.assertIn("incident_id", manifest)
        self.assertEqual(manifest["severity_level"], "LV2")
        self.assertEqual(manifest["deduct_points"], 5)
        self.assertTrue(manifest_builder.manifest_log_path.exists())

if __name__ == "__main__":
    unittest.main()

