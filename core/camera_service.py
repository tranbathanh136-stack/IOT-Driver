import time
import cv2
import threading
from core.unified_detector import UnifiedDriverDetector
from core.temporal_logic import TemporalSafetyLogic
from core.alert_manager import alert_manager
from core.arduino_node import arduino_node
from core.ring_buffer import video_ring_buffer
from core.decision_fusion import decision_fusion
from core.manifest_builder import manifest_builder
from core.state import (
    app_state,
    history_drowsiness,
    history_yawning,
    history_distraction,
    history_posture
)

def start_camera_loop(socketio):
    """
    [LUỒNG NỀN XỬ LÝ VIDEO & TÁC HỢP AI - IOT CHUẨN HÓA 5 BƯỚC]
    - Bước 1: Thu nhận video đưa vào RAM Ring Buffer (90 frames).
    - Bước 2: Temporal Logic đo thời gian thực, Leading-Edge Trigger & Best-Eyes.
    - Bước 3: Decision Fusion hợp nhất AI và Telemetry CO2 theo ma trận LV0/LV1/LV2.
    - Bước 4: Non-blocking Queue điều phối lệnh phần cứng.
    - Bước 5: Tạo Manifest bằng chứng JSON ~1KB + ảnh Base64 ~50KB.
    """
    alert_manager.set_socketio(socketio)
    temporal_logic = TemporalSafetyLogic()

    def camera_loop():
        detector = UnifiedDriverDetector(0)
        app_state.is_camera_connected = detector.is_camera_open()
        
        last_logged_event = None
        last_recovery_time = time.time()

        while True:
            try:
                state = detector.process_frame()
                if state is None or state.get("annotated_frame") is None:
                    time.sleep(0.01)
                    continue

                frame = state["annotated_frame"]
                raw_frame = state.get("frame", frame)
                ear = state.get("ear", 0.3)
                mar = state.get("mar", 0.2)
                now = time.time()

                # BƯỚC 1: Lưu khung hình vào RAM Ring Buffer (maxlen=90)
                video_ring_buffer.append(raw_frame, ear=ear, mar=mar, conf=1.0, now=now)

                # Phục hồi điểm an toàn định kỳ nếu lái xe tốt
                if now - last_recovery_time >= 30.0:
                    last_recovery_time = now
                    new_score = app_state.restore_score(1)
                    socketio.emit("score_update", {"score": new_score})

                # BƯỚC 2: Chạy qua bộ lọc thời gian liên tục (Temporal Logic)
                ai_eval = temporal_logic.update(state, now=now)
                event_type = ai_eval["event_type"]
                duration = ai_eval["duration"]
                v_start = ai_eval["violation_start_time"]

                # BƯỚC 3: Hợp nhất quyết định AI & Telemetry CO2 (Decision Fusion Engine)
                fusion_res = decision_fusion.evaluate(ai_eval, app_state.latest_co2)
                final_level = fusion_res["level"]
                severity = fusion_res["severity"]
                fusion_reason = fusion_res["reason"]
                deduct_points = fusion_res["deduct_points"]
                trigger_sound = fusion_res["trigger_sound"]
                is_leading_edge = fusion_res["is_leading_edge"]
                can_log_db = fusion_res["can_log_db"]

                app_state.latest_ai_status = severity

                # BƯỚC 4 & 5: Ghi nhận vi phạm, trừ điểm, phát cảnh báo và đóng gói Manifest
                if final_level != "LV0":
                    # Kích hoạt còi âm thanh qua Alert Manager
                    if trigger_sound or (is_leading_edge and severity == "CRITICAL"):
                        alert_manager.emit_alert(
                            level=severity,
                            source=f"FUSION_{event_type or 'CO2'}",
                            message=fusion_reason,
                            sound_trigger=trigger_sound
                        )

                    # Khi có sự kiện bắt đầu vi phạm (Leading-Edge) hoặc đến hạn ghi DB
                    if is_leading_edge or can_log_db:
                        # BƯỚC 5: Tạo Manifest JSON kèm ảnh Best-Eyes Base64 (~50KB)
                        manifest_builder.build_and_save_manifest(
                            event_type=event_type or "CO2_HAZARD",
                            severity_level=final_level,
                            reason=fusion_reason,
                            duration=duration,
                            co2_ppm=app_state.latest_co2,
                            v_start_time=v_start,
                            deduct_points=deduct_points,
                            socketio=socketio
                        )

                    if last_logged_event != event_type and event_type is not None:
                        last_logged_event = event_type
                        timestamp_str = time.strftime("%H:%M:%S")
                        log_item = {"timestamp": timestamp_str, "duration": duration, "reason": fusion_reason}

                        if event_type == "DROWSINESS":
                            history_drowsiness.appendleft(log_item)
                            socketio.emit("new_history_drowsiness", log_item)
                        elif event_type == "YAWNING":
                            history_yawning.appendleft(log_item)
                            socketio.emit("new_history_yawning", log_item)
                        elif event_type == "PHONE_DISTRACTION":
                            history_distraction.appendleft(log_item)
                            socketio.emit("new_history_distraction", log_item)
                        elif event_type == "BAD_POSTURE":
                            history_posture.appendleft(log_item)
                            socketio.emit("new_history_posture", log_item)
                else:
                    last_logged_event = None

                # VẼ HUD OVERLAY TRỰC QUAN THEO CẤP ĐỘ PHÂN CẤP [LV0 / LV1 / LV2]
                h, w, _ = frame.shape
                banner_color = (0, 0, 220) if final_level == "LV2" else ((0, 180, 240) if final_level == "LV1" else (40, 180, 40))
                cv2.rectangle(frame, (0, 0), (w, 45), banner_color, -1)
                cv2.putText(frame, f"[{final_level}] {fusion_reason}", (12, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

                cv2.putText(frame, f"EAR: {ear:.2f} | MAR: {mar:.2f} | CO2: {app_state.latest_co2:.0f}ppm", (12, h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
                cv2.putText(frame, f"Score: {app_state.safety_score}", (w - 170, h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

                # Nén ảnh JPEG (Quality 70) truyền Web Live Stream
                ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if ret:
                    app_state.global_frame = buffer.tobytes()

            except Exception:
                time.sleep(0.1)

            time.sleep(0.015)

    t = threading.Thread(target=camera_loop, daemon=True)
    t.start()

