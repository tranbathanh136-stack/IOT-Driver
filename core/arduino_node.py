import time
import re
import queue
import threading
from typing import Optional
from core.state import app_state, system_config, history_co2
from core.alert_manager import alert_manager
from core.http_reporter import http_reporter

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

class ArduinoMQ135Node:
    """
    [KIẾN TRÚC BẤT ĐỒNG BỘ: NON-BLOCKING EVENT QUEUE & SERIAL WORKER]
    - Hoàn toàn tách rời luồng Camera/AI khỏi luồng Serial I/O (Zero-deadlock).
    - send_command(): Đẩy lệnh vào queue.Queue(maxsize=50) bằng put_nowait() (< 0.01ms).
    - Dedicated Serial Worker Thread: Đọc hàng đợi và ghi xuống ESP32.
    - Reader Thread: Đọc dòng telemetry định kỳ và xử lý PONG.
    - Heartbeat Watchdog: Định kỳ 3 giây gửi PING, kiểm tra kết nối sống còn.
    """
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.ser: Optional[serial.Serial] = None
        self.is_running = False
        self.is_connected = False
        self.last_warn_time = 0.0
        self.last_pong_time = time.time()

        # Nạp cấu hình cổng COM
        cfg = system_config.get("arduino_serial", {})
        self.port = cfg.get("port", "COM3")
        self.baudrate = cfg.get("baudrate", 115200)
        self.timeout = cfg.get("timeout", 0.1)  # 0.1s non-blocking
        self.auto_detect = cfg.get("auto_detect_port", True)

        # Hàng đợi lệnh điều khiển non-blocking
        self.cmd_queue = queue.Queue(maxsize=50)
        self._lock = threading.Lock()

    def set_socketio(self, socketio):
        self.socketio = socketio

    def auto_find_port(self) -> str:
        """Tự động tìm kiếm cổng COM của Arduino / ESP32 / CH340 / CP210x"""
        if not serial:
            return self.port
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            desc = p.description.lower()
            if any(k in desc for k in ["ch340", "cp210", "arduino", "usb-serial", "ftdi", "esp"]):
                return p.device
        if ports:
            return ports[0].device
        return self.port

    def send_command(self, cmd: str) -> bool:
        """
        [BƯỚC 4: NON-BLOCKING DISPATCHER]
        Đẩy lệnh vào hàng đợi với put_nowait(). Tuyệt đối không bao giờ làm đứng khung hình camera!
        """
        cmd_str = cmd.strip().upper()
        if not cmd_str:
            return False

        try:
            self.cmd_queue.put_nowait(cmd_str)
            return True
        except queue.Full:
            # Drop oldest policy khi hàng đợi quá tải
            try:
                self.cmd_queue.get_nowait()
                self.cmd_queue.put_nowait(cmd_str)
                return True
            except Exception:
                return False

    def _writer_worker_loop(self):
        """Worker chuyên biệt chịu trách nhiệm ghi lệnh xuống cổng Serial"""
        while self.is_running:
            try:
                cmd = self.cmd_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            with self._lock:
                if self.ser and self.ser.is_open:
                    try:
                        payload = (cmd + "\n").encode("utf-8")
                        self.ser.write(payload)
                        self.ser.flush()
                    except Exception as e:
                        self.is_connected = False
                        print(f"[Serial Worker Error] Không thể gửi {cmd}: {e}")
                else:
                    # Ghi log nội bộ khi cổng COM chưa mở, không bao giờ crash
                    pass

    def _heartbeat_loop(self):
        """Định kỳ mỗi 3s gửi PING kiểm tra tình trạng ESP32"""
        while self.is_running:
            time.sleep(3.0)
            if self.is_connected:
                self.send_command("PING")

    def _reader_loop(self):
        """Tiến trình ngầm đọc telemetry và phản hồi từ ESP32"""
        while self.is_running:
            # 1. Kết nối cổng COM nếu chưa mở
            if self.ser is None or not self.ser.is_open:
                if self.auto_detect:
                    detected_port = self.auto_find_port()
                    if detected_port:
                        self.port = detected_port

                try:
                    self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
                    time.sleep(1.5)  # Chờ ESP32 reset sau khi mở DTR
                    self.is_connected = True
                    self.last_pong_time = time.time()
                    print(f"\n[Arduino MQ-135] ✅ ĐÃ KẾT NỐI THÀNH CÔNG tại {self.port} ({self.baudrate} baud)!")
                except Exception:
                    self.is_connected = False
                    now = time.time()
                    if now - self.last_warn_time >= 5.0:
                        self.last_warn_time = now
                        print(f"[Arduino MQ-135] Đang chờ kết nối cảm biến tại {self.port}...")
                    time.sleep(2.0)
                    continue

            # 2. Đọc dòng dữ liệu từ cảm biến
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                if line == "PONG":
                    self.last_pong_time = time.time()
                    continue

                # 3. Giải mã các gói sự kiện EVT từ Firmware ESP32
                if line.startswith("EVT"):
                    evt_parts = line.split(",")
                    evt_name = evt_parts[1].strip() if len(evt_parts) > 1 else ""

                    if evt_name == "MUTE":
                        app_state.is_hardware_muted = True
                        app_state.mute_expire_time = time.time() + 30.0
                        print("\n[ESP32] 🔇 NÚT MUTE VẬT LÝ ĐÃ BẤM -> Tạm dừng còi trong 30 giây!")
                        if self.socketio:
                            self.socketio.emit("hardware_event", {
                                "type": "MUTE",
                                "duration": 30,
                                "message": "Nút Mute phần cứng được bấm: Tạm tắt loa 30s"
                            })
                    elif evt_name == "BOOT":
                        print("[ESP32] 🚀 Thiết bị khởi động lại thành công (BOOT).")
                    elif evt_name.startswith("R0="):
                        try:
                            app_state.esp32_r0 = float(evt_name.split("=")[1])
                            print(f"[ESP32] ⚙️ Điện trở chuẩn R0 nạp từ Flash: {app_state.esp32_r0:.2f} kOhm")
                        except Exception:
                            pass
                    elif evt_name == "CAL_START":
                        print("[ESP32] 🧪 Đang thực hiện hiệu chuẩn R0 trong không khí sạch (10s)...")
                        if self.socketio:
                            self.socketio.emit("hardware_event", {
                                "type": "CAL_START",
                                "message": "Đang hiệu chuẩn R0 trong không khí sạch (10s)..."
                            })
                    elif evt_name == "CAL_DONE":
                        r0_info = evt_parts[2].strip() if len(evt_parts) > 2 else ""
                        try:
                            if "R0=" in r0_info:
                                app_state.esp32_r0 = float(r0_info.split("=")[1])
                        except Exception:
                            pass
                        print(f"[ESP32] ✅ Hiệu chuẩn hoàn tất! {r0_info}")
                        if self.socketio:
                            self.socketio.emit("hardware_event", {
                                "type": "CAL_DONE",
                                "message": f"Hiệu chuẩn thành công: {r0_info}"
                            })
                    continue

                co2_val = None
                adc_val = 0
                lv_num = 0
                level_str = "SAFE"
                src_str = "ESP32_MQ135"

                if "CO2:" in line:
                    parts = {p.split(":", 1)[0].strip(): p.split(":", 1)[1].strip() for p in line.split(",") if ":" in p}
                    co2_val = float(parts.get("CO2", 0.0))
                    adc_val = int(parts.get("ADC", 0))
                    src_str = parts.get("SRC", "ESP32_MQ135")

                    if "LV" in parts:
                        lv_num = int(parts.get("LV", 0))
                        level_str = "CRITICAL" if lv_num == 2 else ("WARNING" if lv_num == 1 else "SAFE")
                    else:
                        if co2_val > 1500.0:
                            level_str = "CRITICAL"
                        elif co2_val >= 1000.0:
                            level_str = "WARNING"
                else:
                    try:
                        co2_val = float(line.strip())
                        if co2_val > 1500.0:
                            level_str = "CRITICAL"
                        elif co2_val >= 1000.0:
                            level_str = "WARNING"
                    except ValueError:
                        continue

                if co2_val is not None:
                    # Kiểm tra trạng thái sấy nóng và Mute
                    app_state.is_warming_up = (src_str == "WARMUP")
                    if time.time() > app_state.mute_expire_time:
                        app_state.is_hardware_muted = False

                    app_state.latest_co2 = co2_val
                    app_state.latest_co2_level = level_str
                    app_state.latest_adc = adc_val
                    app_state.latest_src = src_str

                    http_reporter.record_telemetry(src_str, co2_val, level_str)

                    if self.socketio:
                        self.socketio.emit("sensor_update", {
                            "co2": round(co2_val, 1),
                            "adc": adc_val,
                            "level": level_str,
                            "source": src_str,
                            "is_real_hardware": True,
                            "is_warming_up": app_state.is_warming_up,
                            "is_muted": app_state.is_hardware_muted,
                            "r0": app_state.esp32_r0
                        })

                    # Fallback cảnh báo: Chỉ phát từ luồng đọc Serial khi Camera AI không kết nối
                    # (Khi Camera hoạt động, Decision Fusion Engine sẽ chịu trách nhiệm điều phối cảnh báo)
                    if level_str != "SAFE" and not app_state.is_camera_connected:
                        log_item = {
                            "timestamp": time.strftime("%H:%M:%S"),
                            "duration": 1.0,
                            "max_co2": round(co2_val, 1),
                            "level": level_str
                        }
                        history_co2.appendleft(log_item)
                        if self.socketio:
                            self.socketio.emit("new_history_co2", log_item)

                        alert_manager.emit_alert(
                            level=level_str,
                            source="CẢM BIẾN MQ-135 THẬT",
                            message=f"Nồng độ CO2 vượt mức ({co2_val:.1f} ppm) - Cabin thiếu khí!",
                            sound_trigger=(level_str == "CRITICAL" and not app_state.is_hardware_muted)
                        )

            except Exception as e:
                self.is_connected = False
                with self._lock:
                    if self.ser:
                        try:
                            self.ser.close()
                        except Exception:
                            pass
                        self.ser = None
                time.sleep(2.0)

    def start(self):
        self.is_running = True
        t_reader = threading.Thread(target=self._reader_loop, daemon=True)
        t_reader.start()

        t_writer = threading.Thread(target=self._writer_worker_loop, daemon=True)
        t_writer.start()

        t_heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        t_heartbeat.start()

arduino_node = ArduinoMQ135Node()
