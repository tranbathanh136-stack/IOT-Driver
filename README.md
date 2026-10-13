# YOLO26 - Hệ Thống Giám Sát An Toàn Tài Xế & IoT (Phiên Bản Hợp Nhất & Thử Nghiệm Mẫu)

> **Mục Đích Tạo Ra Thư Mục Này:**  
> Đây là môi trường kiểm thử mẫu (**Staging/Sandbox**) độc lập tại `e:\AI\YOLO26`. Thư mục này tổng hợp toàn bộ các tinh hoa, thuật toán AI và tính năng từ 3 thư mục nguồn (`TEST_1`, `TEST_2`, `YOLO`) kết hợp với nền tảng của hệ thống chính (`IOT`).  
> **Cam kết:** Không can thiệp hay làm ảnh hưởng trực tiếp đến `e:\AI\IOT` cho đến khi bạn kiểm thử và xác nhận mọi chức năng hoàn hảo.

---

## 1. Tổng Hợp Tinh Hoa Được Tối Ưu Từ Các Thư Mục

| Nguồn Tài Nguyên | Thành Phần Khai Thác & Tối Ưu | Cách Tích Hợp Vào `YOLO26` |
| :--- | :--- | :--- |
| **`IOT` (Gốc)** | • Kiến trúc Flask + SocketIO thời gian thực.<br>• Quản lý bộ nhớ vòng `collections.deque(maxlen=200)` chống tràn RAM.<br>• Hàng đợi tác vụ chạy nền có ngắt mạch **Circuit Breaker**.<br>• Cảm biến MQ-135 $CO_2$ cabin xe. | Là khung xương cốt lõi (Core Framework) điều phối toàn bộ luồng truyền thông mạng và giao diện. |
| **`TEST_1`** | • Phát hiện mất tập trung / sử dụng điện thoại (`cell phone` từ YOLOv8).<br>• File âm thanh còi báo thật chất lượng cao: `alarm.wav`. | Tích hợp model `yolov8n.pt` chạy xen kẽ tối ưu FPS và bộ phát âm thanh native không giật lag. |
| **`TEST_2`** | • Cơ chế **Temporal Logic** (tính thời gian liên tục theo giây thay vì chỉ đếm frame nhiễu).<br>• Tránh báo động giả do chớp mắt sinh lý bình thường (< 0.4s).<br>• Dịch vụ âm thanh non-blocking có **Cooldown Lock** (3s).<br>• Giao diện HUD Banner trạng thái trực quan. | Đưa vào [temporal_logic.py](file:///e:/AI/YOLO26/core/temporal_logic.py) và [alarm_service.py](file:///e:/AI/YOLO26/core/alarm_service.py). |
| **`YOLO`** | • Model `yolo26n-pose.pt` (Pose Estimation keypoints).<br>• Khả năng nhận diện tư thế người. | Phân tích góc nghiêng đầu và khoảng cách mũi - vai để phát hiện **tài xế gục đầu ngủ** hoặc **lệch tư thế lái**. |

---

## 2. Cấu Trúc Thư Mục `YOLO26` (Đã Tích Hợp Chuẩn Hóa 5 Bước)

```
e:\AI\YOLO26/
├── app.py                      # Điểm khởi chạy chính (Khởi động Flask, Camera, IoT Node)
├── config.json                 # File cấu hình hợp nhất toàn diện (Model, Ngưỡng, Âm thanh, IoT)
├── requirements.txt            # Danh sách thư viện đồng bộ
├── README.md                   # Tài liệu hướng dẫn & Báo cáo kỹ thuật
├── assets/
│   └── alarm.wav               # File âm thanh cảnh báo còi thật (từ TEST_1)
├── firmware/
│   └── esp32_firmware.ino      # [BƯỚC 1 & 4 IoT] Firmware ESP32 FreeRTOS Fail-Safe, EMA & còi PWM
├── models/
│   ├── best.pt                 # Model YOLO phát hiện nhắm mắt & ngáp (từ IOT)
│   ├── face_landmarker.task    # Model MediaPipe điểm mốc khuôn mặt (đã gộp đồng nhất từ model/)
│   ├── yolov8n.pt              # Model YOLO phát hiện điện thoại (từ TEST_1)
│   └── yolo26n-pose.pt         # Model YOLO nhận diện tư thế Pose (từ YOLO)
├── core/
│   ├── ring_buffer.py          # [BƯỚC 1-2] RAM Ring Buffer deque(90) & Thuật toán Best-Eyes O(log n)
│   ├── temporal_logic.py       # [BƯỚC 2] Lọc thời gian liên tục + Leading-Edge + Dual Debounce (10s/30s)
│   ├── decision_fusion.py      # [BƯỚC 3] Máy trạng thái hợp nhất AI & Telemetry CO2 (LV0/LV1/LV2)
│   ├── arduino_node.py         # [BƯỚC 4] Dual-Thread Serial Worker: put_nowait(), Heartbeat PING/PONG
│   ├── manifest_builder.py     # [BƯỚC 5] Đóng gói Manifest JSON (~1KB) + Base64 Snapshot (~50KB)
│   ├── unified_detector.py     # Bộ AI đa nhiệm hợp nhất (Drowsy + Phone + Pose)
│   ├── alarm_service.py        # Dịch vụ phát âm thanh non-blocking có Cooldown Lock
│   ├── camera_service.py       # Điều phối Camera kết nối Ring Buffer & Decision Fusion
│   ├── alert_manager.py        # Bộ điều phối cảnh báo phân cấp & trừ điểm tài xế
│   ├── http_reporter.py        # Xử lý HTTP độc lập & lưu trữ báo cáo (Ẩn spam Terminal)
│   ├── state.py                # Quản lý Deque(200) và trạng thái hệ thống
│   ├── routes.py               # API REST, Webhook IoT và Demo triggers
│   ├── error_handlers.py       # Middleware bắt lỗi 404, 500 an toàn
│   └── logger_config.py        # Cấu hình log chuẩn hóa
├── logs/
│   ├── http_access.log         # Nhật ký toàn bộ HTTP request (xoay vòng 5MB)
│   ├── telemetry_reports.jsonl # Dữ liệu báo cáo telemetry và sự kiện an toàn
│   └── incidents_manifest.jsonl# [BƯỚC 5] Dữ liệu Manifest bằng chứng chi tiết
├── virtual_devices/
│   └── virtual_pi_node.py      # Raspberry Pi IoT Node ảo (Tự động chạy định kỳ 1s)
├── templates/
│   └── index.html              # Dashboard Web HUD hiện đại, theo dõi đa chỉ số
├── static/
│   ├── css/dashboard.css       # Giao diện Dark Mode chuyên nghiệp
│   └── js/app.js               # Logic WebSocket thời gian thực
├── history/
│   ├── history.html            # Nhật ký lịch sử 5 hạng mục vi phạm
│   ├── history.js              # Script lọc theo thời gian
│   └── history.css             # Style bảng dữ liệu
└── tests/
    └── test_components.py      # Bộ 10 Unit Tests kiểm tra toàn diện 5 bước tác hợp
```

---

## 3. Hướng Dẫn Kiểm Thử Độc Lập

### Bước 1: Chạy Bộ Unit Test Tự Động
Để kiểm tra tính toàn vẹn của code và các file weights:
```powershell
e:\AI\IOT\.venv\Scripts\python.exe -m unittest e:\AI\YOLO26\tests\test_components.py
```
*(Kết quả mong đợi: `Ran 5 tests ... OK`)*

### Bước 2: Khởi Chạy Ứng Dụng Mẫu YOLO26
```powershell
cd e:\AI\YOLO26
e:\AI\IOT\.venv\Scripts\python.exe app.py
```

### Bước 3: Trải Nghiệm Trên Trình Duyệt Web
1. **Web Dashboard Thời Gian Thực:** Mở trình duyệt tại [http://127.0.0.1:5000](http://127.0.0.1:5000)
   - Xem video stream trực tiếp từ webcam với HUD Banner đổi màu theo cấp độ cảnh báo.
   - Theo dõi 4 thẻ chỉ số: Mắt (Drowsiness), Miệng (Yawning), Điện thoại (Phone), Tư thế (Pose).
   - Theo dõi nồng độ khí $CO_2$ gửi về tự động từ node IoT Raspberry Pi ảo.
   - Thử nghiệm các nút **Demo Triggers** (Ngủ gật, Điện thoại, Ngáp, Gục đầu, CO2 cao, Reset điểm) để xem phản hồi tức thì của còi báo và WebSocket.
2. **Trang Lịch Sử Toàn Diện:** Mở [http://127.0.0.1:5000/history](http://127.0.0.1:5000/history)
   - Xem bảng thống kê 5 loại sự kiện có phân loại theo giây và mức độ.
   - Hỗ trợ lọc theo mốc thời gian bắt đầu - kết thúc.

---

## 4. Checklist Sẵn Sàng Chuyển Giao Sang Thư Mục Chính `IOT`

Khi bạn đã test xong trong `YOLO26` và muốn áp dụng vào `IOT`:
- [ ] Xác nhận giao diện và âm thanh hoạt động đúng mong muốn.
- [ ] Sao chép các module mới từ `YOLO26/core/` sang `IOT/core/`.
- [ ] Bổ sung các file weights (`yolov8n.pt`, `yolo26n-pose.pt`, `alarm.wav`) vào `IOT`.
- [ ] Cập nhật giao diện Dashboard và Bảng lịch sử của `IOT`.
- [ ] Đồng bộ hóa file cấu hình `config.json`.
