import time
from flask import render_template, request, jsonify, send_from_directory, send_file, Response
from core.state import (
    app_state,
    system_config,
    history_drowsiness,
    history_yawning,
    history_distraction,
    history_posture,
    history_co2
)
from core.alert_manager import alert_manager
from core.http_reporter import http_reporter

def register_routes(app, socketio):
    alert_manager.set_socketio(socketio)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/history")
    def view_history():
        return send_from_directory("history", "history.html")

    @app.route("/history/<path:filename>")
    def history_static(filename):
        return send_from_directory("history", filename)

    @app.route("/video_feed")
    def video_feed():
        """
        [HTTP MULTIPART STREAMING CHO LIVE STREAM TRỰC QUAN]
        """
        def generate():
            while True:
                if app_state.global_frame is not None:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + app_state.global_frame + b'\r\n')
                time.sleep(0.04)
        return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

    @app.route("/api/status", methods=["GET"])
    def get_status():
        return jsonify({
            "camera_connected": app_state.is_camera_connected,
            "safety_score": app_state.safety_score,
            "ai_status": app_state.latest_ai_status,
            "co2_ppm": app_state.latest_co2,
            "co2_level": app_state.latest_co2_level,
            "active_alert": app_state.active_alert
        })

    @app.route("/api/history/all", methods=["GET"])
    def get_all_history():
        return jsonify({
            "drowsiness": list(history_drowsiness),
            "yawning": list(history_yawning),
            "distraction": list(history_distraction),
            "posture": list(history_posture),
            "co2": list(history_co2)
        })

    @app.route("/api/iot/telemetry", methods=["POST"])
    def receive_telemetry():
        """
        [WEBHOOK NHẬN DỮ LIỆU CẢM BIẾN TỪ THIẾT BỊ IOT RASPBERRY PI]
        Toàn bộ nhật ký được chuyển vào http_reporter để giữ sạch Terminal.
        """
        data = request.json or {}
        co2 = float(data.get("co2_ppm", data.get("co2", data.get("CO2", 400.0))))
        adc = int(data.get("adc", data.get("ADC", 0)))
        device_id = data.get("device_id", data.get("src", data.get("SRC", "ESP32_MQ135")))

        # Nếu ESP32 gửi trực tiếp cấp độ LV
        if any(k in data for k in ["level", "lv", "LV"]):
            raw_lv = data.get("level", data.get("lv", data.get("LV", "SAFE")))
            if str(raw_lv) in ["2", "CRITICAL"]:
                level = "CRITICAL"
            elif str(raw_lv) in ["1", "WARNING"]:
                level = "WARNING"
            else:
                level = "SAFE"
        else:
            sensor_cfg = system_config.get("sensor_co2", {})
            crit_thresh = sensor_cfg.get("critical_threshold", 1500.0)
            warn_thresh = sensor_cfg.get("warning_threshold", 1000.0)
            level = "SAFE"
            if co2 >= crit_thresh:
                level = "CRITICAL"
            elif co2 >= warn_thresh:
                level = "WARNING"

        app_state.latest_co2 = co2
        app_state.latest_co2_level = level
        app_state.latest_adc = adc
        app_state.latest_src = device_id

        # Ghi nhận vào hệ thống Báo cáo chuyên biệt ngầm
        http_reporter.record_telemetry(device_id, co2, level)

        # Bắn SocketIO cập nhật cảm biến tức thì lên Web Dashboard
        socketio.emit("sensor_update", {
            "co2": round(co2, 1),
            "adc": adc,
            "level": level,
            "device_id": device_id,
            "is_real_hardware": True
        })

        # Cảnh báo nồng độ khí CO2 nguy hiểm
        if level != "SAFE":
            log_item = {
                "timestamp": time.strftime("%H:%M:%S"),
                "duration": 1.0,
                "max_co2": round(co2, 1),
                "level": level
            }
            history_co2.appendleft(log_item)
            socketio.emit("new_history_co2", log_item)

            alert_manager.emit_alert(
                level=level,
                source=f"MQ135_{device_id}",
                message=f"Nồng độ CO2 vượt mức ({co2:.1f} ppm) - Cabin thiếu khí!",
                sound_trigger=(level == "CRITICAL")
            )

        return jsonify({"status": "ok", "ack_level": level})

    @app.route("/api/cmd", methods=["POST"])
    def handle_command():
        """Nhận lệnh điều khiển trực tiếp gửi xuống Arduino/ESP32"""
        from core.arduino_node import arduino_node
        cmd = (request.json or {}).get("cmd", "")
        ok = arduino_node.send_command(cmd)
        return jsonify({"ok": ok, "cmd": cmd})

    @app.route("/api/camera_event", methods=["POST"])
    def handle_camera_event():
        """Nhận sự kiện camera và gửi lệnh SLEEP xuống Arduino/ESP32"""
        from core.arduino_node import arduino_node
        data = request.json or {}
        event_type = data.get("type", "DROWSINESS")
        ok = arduino_node.send_command("SLEEP")
        return jsonify({"ok": ok, "event": event_type})

    # =========================================================================
    # [HỆ THỐNG API BÁO CÁO CHUYÊN BIỆT (REPORTING SYSTEM)]
    # =========================================================================
    @app.route("/api/report/summary", methods=["GET"])
    def get_report_summary():
        """Trả về dữ liệu thống kê tổng hợp số lượt truy cập và sự kiện an toàn"""
        return jsonify(http_reporter.get_summary())

    @app.route("/api/report/download", methods=["GET"])
    def download_report():
        """Tải file báo cáo dữ liệu sự kiện ngầm"""
        if http_reporter.report_data_path.exists():
            return send_file(
                str(http_reporter.report_data_path),
                as_attachment=True,
                download_name="telemetry_reports.jsonl"
            )
        return jsonify({"error": "Chưa có dữ liệu báo cáo nào"}), 404

    @app.route("/api/demo/trigger_ai", methods=["POST"])
    def trigger_ai():
        """
        [API THỬ NGHIỆM TỨC THÌ (DEMO TRIGGERS) DÀNH CHO TEST NHANH]
        """
        data = request.json or {}
        event = data.get("event", "SAFE")
        timestamp_str = time.strftime("%H:%M:%S")

        if event == "DROWSINESS":
            item = {"timestamp": timestamp_str, "duration": 2.5, "reason": "Test ngủ gật"}
            history_drowsiness.appendleft(item)
            socketio.emit("new_history_drowsiness", item)
            alert_manager.emit_alert("CRITICAL", "AI_DEMO_DROWSY", "Mô phỏng phát hiện tài xế nhắm mắt ngủ gật!", True)

        elif event == "YAWNING":
            item = {"timestamp": timestamp_str, "duration": 2.0, "reason": "Test ngáp"}
            history_yawning.appendleft(item)
            socketio.emit("new_history_yawning", item)
            alert_manager.emit_alert("WARNING", "AI_DEMO_YAWN", "Mô phỏng phát hiện tài xế ngáp liên tục", False)

        elif event == "PHONE":
            item = {"timestamp": timestamp_str, "duration": 3.0, "reason": "Test điện thoại"}
            history_distraction.appendleft(item)
            socketio.emit("new_history_distraction", item)
            alert_manager.emit_alert("CRITICAL", "AI_DEMO_PHONE", "Mô phỏng phát hiện tài xế cầm điện thoại khi lái xe!", True)

        elif event == "POSTURE":
            item = {"timestamp": timestamp_str, "duration": 2.5, "reason": "Test tư thế gục"}
            history_posture.appendleft(item)
            socketio.emit("new_history_posture", item)
            alert_manager.emit_alert("WARNING", "AI_DEMO_POSTURE", "Mô phỏng phát hiện tài xế gục đầu sai tư thế", False)

        elif event == "CO2_CRITICAL":
            item = {"timestamp": timestamp_str, "duration": 5.0, "max_co2": 1680.0, "level": "CRITICAL"}
            history_co2.appendleft(item)
            socketio.emit("new_history_co2", item)
            alert_manager.emit_alert("CRITICAL", "MQ135_TEST", "Mô phỏng CO2 đạt 1680 ppm - Báo động khẩn!", True)

        elif event == "RESET_SCORE":
            app_state.safety_score = 100
            socketio.emit("score_update", {"score": 100})

        return jsonify({"status": "success", "event": event, "current_score": app_state.safety_score})
