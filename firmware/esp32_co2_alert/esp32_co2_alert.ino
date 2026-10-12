/*
 * =================================================================================
 * DỰ ÁN: HỆ THỐNG GIÁM SÁT AN TOÀN TÀI XẾ & ĐO CHẤT LƯỢNG KHÔNG KHÍ (CO2)
 * THIẾT BỊ: ESP32 Dev Module kết hợp Cảm biến MQ-135 + Loa cảnh báo PAM8403
 * GIAO TIẾP: Giao tiếp nối tiếp Serial qua cổng USB với máy tính (115200 baud)
 * =================================================================================
 *
 * HƯỚNG DẪN ARDUINO IDE:
 * - Tên thư mục chứa file phải đặt trùng tên: esp32_co2_alert
 * - Chọn Board: "ESP32 Dev Module" (hoặc DOIT ESP32 DEVKIT V1)
 * - Tốc độ truyền (Baud rate): 115200
 *
 * ============================== SƠ ĐỒ NỐI DÂY CHI TIẾT ==============================
 * 1. Cảm biến MQ-135 (Đo nồng độ CO2 / eCO2):
 *    - Chân VCC  -> Nối chân 5V (VIN) của ESP32.
 *    - Chân GND  -> Nối chân GND chung của ESP32.
 *    - Chân AO   -> Nối qua CẦU CHIA ÁP (R1 10k phía trên, R2 20k phía dưới) -> GPIO34.
 *      [LƯU Ý KỸ THUẬT QUAN TRỌNG]: 
 *      Chân AO của module MQ-135 xuất điện áp tối đa 5V. Trong khi đó chân ADC của ESP32 
 *      chỉ chịu được tối đa 3.3V (vượt quá sẽ cháy chân ADC). Do đó BẮT BUỘC dùng cầu chia áp:
 *      V_ADC = V_AO * R2 / (R1 + R2) = V_AO * 20k / (10k + 20k) = V_AO * 0.667.
 *      Hệ số chia áp DIV_RATIO = (R1 + R2) / R2 = 30k / 20k = 1.5.
 *
 * 2. Mạch khuếch đại âm thanh PAM8403 (Phát cảnh báo loa):
 *    - Chân tín hiệu: GPIO22 (D22) -> Điện trở 1k -> Tụ hóa 10uF (+ quay về PAM) -> L-IN.
 *    - Chân nguồn: Cấp 5V (VIN) và nối chung mass GND với ESP32.
 *    - Đầu ra: Nối ra Loa 4-8 Ohm (L-OUT + / -). Chỉnh âm lượng bằng biến trở xoay.
 *
 * 3. Đèn LED chỉ báo trạng thái:
 *    - GPIO2: Đèn LED xanh tích hợp sẵn trên bo mạch ESP32 (Onboard LED).
 *
 * 4. Nút bấm tắt tiếng khẩn cấp (MUTE button):
 *    - GPIO27 -> Nối qua nút nhấn vật lý -> Chân GND (Sử dụng INPUT_PULLUP nội bộ).
 *    - Nhấn nút: Tạm dừng tiếng chuông báo trong vòng 30 giây.
 *
 * ======================== BẢNG LỆNH ĐIỀU KHIỂN TỪ MÁY TÍNH ========================
 * (Nhận từ máy chủ Python gửi xuống, kết thúc bằng ký tự xuống dòng \n):
 *  - SLEEP         : Cảnh báo ngủ gật/nhắm mắt (Phát chuông bíp nhanh xen kẽ 2 tần số trong 6s).
 *  - ALERT:1[:ms]  : Cảnh báo VÀNG (Bíp từng nhịp ngắt quãng; mặc định 5000ms).
 *  - ALERT:2[:ms]  : Cảnh báo ĐỎ (Chuông kêu liên tục báo động nguy hiểm).
 *  - STOP          : Tắt chuông thủ công khi tài xế đã tỉnh táo trở lại.
 *  - CAL           : Bắt đầu hiệu chuẩn điện trở R0 trong không khí sạch (~10 giây).
 *  - PING          : Kiểm tra kết nối; ESP32 sẽ phản hồi lại chuỗi "PONG".
 *
 * ======================= ĐỊNH DẠNG DỮ LIỆU ĐẨY LÊN MÁY TÍNH =======================
 * (Gửi định kỳ mỗi 500ms để hiển thị thời gian thực trên Web Dashboard):
 *  Định dạng: CO2:<ppm>,ADC:<raw>,LV:<0|1|2>,SRC:<NONE|CO2|CMD|SLEEP|WARMUP|CAL>
 * =================================================================================
 */

#include <Arduino.h>
#include <Preferences.h> // Thư viện lưu giá trị R0 vào bộ nhớ Flash không bay hơi (NVS)
#include <math.h>

// ----------------------------- CẤU HÌNH CHÂN GPIO -----------------------------
#define MQ_PIN     34    // Chân đọc tín hiệu Analog từ MQ-135 qua cầu chia áp
#define SPK_PIN    22    // Chân băm xung PWM tạo âm thanh ra loa PAM8403 (GPIO22)
#define LED_PIN    2     // Đèn LED chỉ báo trạng thái trên board
#define MUTE_PIN   27    // Chân nút nhấn tạm thời tắt chuông cảnh báo (Active LOW)

// ----------------------------- THÔNG SỐ CẢM BIẾN MQ-135 -----------------------
const float VCC_SENSOR   = 5.0;    // Điện áp nguồn cấp cho cảm biến MQ-135 (5V)
const float DIV_RATIO    = 1.5;    // Tỉ số bù cầu chia áp: (10k + 20k) / 20k = 1.5
const float RL_KOHM      = 10.0;   // Điện trở tải RL trên mạch cảm biến (thông thường là 10kOhm)

// Phương trình đặc tuyến đường cong thực nghiệm của MQ-135: ppm = PARA * (Rs / R0)^(-PARB)
const float PARA         = 116.6020682;
const float PARB         = 2.769034857;
const float CLEAN_PPM    = 400.0;  // Nồng độ CO2 tiêu chuẩn trong môi trường không khí sạch ngoài trời
float R0_KOHM            = 76.63;  // Giá trị R0 mặc định (sẽ được ghi đè sau khi hiệu chuẩn CAL)

const unsigned long WARMUP_MS = 60000UL; // Thời gian sấy nóng cảm biến sau khi bật nguồn (60 giây)
const int   N_SAMPLES    = 32;     // Số mẫu lấy trung bình mỗi lần đọc để triệt tiêu nhiễu ADC
const float EMA_ALPHA    = 0.35;   // Hệ số lọc làm mịn tín hiệu số EMA (0.0 < alpha <= 1.0)

// ----------------------------- NGƯỠNG CẢNH BÁO CO2 (PPM) ----------------------
const float PPM_SAFE_MAX = 1000.0; // Dưới 1000 ppm: Trạng thái AN TOÀN (Không khí trong lành)
const float PPM_WARN     = 1000.0; // Từ 1000 đến 1500 ppm: CẢNH BÁO VÀNG (Bắt đầu ngột ngạt)
const float PPM_RED      = 1500.0; // Trên 1500 ppm: NGUY HIỂM ĐỎ (Thiếu oxy nghiêm trọng, gây ngủ gật)
const float HYST         = 50.0;   // Vùng trễ (Hysteresis) 50 ppm để chống rung giật ngưỡng đóng/ngắt

// ----------------------------- CẤU HÌNH TẦN SỐ ÂM THANH (HZ) ------------------
const int FREQ_WARN      = 2000;   // 2000 Hz: Tần số chuông cảnh báo Vàng (bíp ngắt quãng)
const int FREQ_RED       = 3000;   // 3000 Hz: Tần số còi báo động Đỏ (hú liên tục)
const int FREQ_SLEEP1    = 2200;   // 2200 Hz: Tần số bíp 1 khi phát hiện tài xế nhắm mắt ngủ gật
const int FREQ_SLEEP2    = 3200;   // 3200 Hz: Tần số bíp 2 đảo liên tục để kích thích thính giác
const unsigned long WARN_ON_MS        = 300;   // Thời gian bật còi cảnh báo vàng (ms)
const unsigned long WARN_OFF_MS       = 700;   // Thời gian nghỉ giữa các nhịp còi vàng (ms)
const unsigned long SLEEP_BEEP_MS     = 120;   // Chu kỳ đảo nhịp bíp dồn dập khi ngủ gật (ms)
const unsigned long SLEEP_DURATION_MS = 6000;  // Thời gian phát chuông ngủ gật tự động (6 giây)
const unsigned long MUTE_DURATION_MS  = 30000; // Thời gian tạm ngắt chuông khi bấm nút Mute (30 giây)

// ----------------------------- BIẾN TOÀN CỤC VÀ TRẠNG THÁI --------------------
Preferences prefs;                 // Đối tượng truy xuất Flash NVS của ESP32
float  ppmFiltered   = CLEAN_PPM;  // Giá trị nồng độ CO2 sau khi lọc làm mịn
int    adcRaw        = 0;          // Giá trị đọc thô từ ADC (0 - 4095)
int    coLevel       = 0;          // Cấp độ cảnh báo do nồng độ khí CO2 (0: Safe, 1: Warn, 2: Red)
int    cmdLevel      = 0;          // Cấp độ cảnh báo nhận từ máy tính Python
unsigned long cmdUntil   = 0;      // Thời điểm hết hạn lệnh cảnh báo từ máy tính
bool   cmdForever    = false;      // Cờ phát chuông vô hạn đến khi có lệnh STOP
unsigned long sleepUntil = 0;      // Mốc thời gian kết thúc chuông cảnh báo ngủ gật
unsigned long muteUntil  = 0;      // Mốc thời gian kết thúc trạng thái tạm tắt loa
unsigned long lastTelemetry = 0;   // Thời điểm gửi gói tin Telemetry gần nhất
unsigned long lastSample    = 0;   // Thời điểm lấy mẫu cảm biến gần nhất

// Biến phục vụ quá trình tự động hiệu chuẩn R0
bool   calibrating   = false;      // Cờ báo đang trong tiến trình hiệu chuẩn
unsigned long calStart = 0;        // Mốc thời gian bắt đầu hiệu chuẩn
double calSum        = 0;          // Tổng tích lũy điện trở Rs để tính trung bình
int    calCount      = 0;          // Số lượng mẫu Rs thu thập được trong 10 giây

String rxBuf;                      // Bộ đệm nhận chuỗi lệnh qua Serial
int    lastReportedLevel = -1;     // Lưu mức cảnh báo trước đó để tránh bắn trùng sự kiện EVT

// =================================================================================
// [KHỐI ĐIỀU KHIỂN ÂM THANH - PWM LOA]
// Tự động tương thích với cả ESP32 Core phiên bản 2.x và Core phiên bản 3.x mới nhất
// =================================================================================
#if ESP_ARDUINO_VERSION_MAJOR >= 3
void speakerInit()          { ledcAttach(SPK_PIN, 2000, 8); ledcWriteTone(SPK_PIN, 0); }
void speakerTone(int hz)    { ledcWriteTone(SPK_PIN, hz); }
void speakerOff()           { ledcWriteTone(SPK_PIN, 0); }
#else
void speakerInit()          { ledcSetup(0, 2000, 8); ledcAttachPin(SPK_PIN, 0); ledcWriteTone(0, 0); }
void speakerTone(int hz)    { ledcWriteTone(0, hz); }
void speakerOff()           { ledcWriteTone(0, 0); }
#endif

// =================================================================================
// [CÔNG THỨC TOÁN HỌC & ĐỌC ĐIỆN TRỞ CẢM BIẾN MQ-135]
// =================================================================================
float readRsKohm() {
  // Lấy trung bình 32 mẫu liên tiếp bằng hàm analogReadMilliVolts() để loại bỏ nhiễu phi tuyến tính
  uint32_t sumMv = 0; 
  uint32_t sumRaw = 0;
  for (int i = 0; i < N_SAMPLES; i++) {
    sumMv  += analogReadMilliVolts(MQ_PIN);
    sumRaw += analogRead(MQ_PIN);
    delayMicroseconds(300);
  }
  adcRaw = sumRaw / N_SAMPLES;
  
  // Tính điện áp đo được tại chân GPIO của ESP32 (V)
  float vAdc = (sumMv / (float)N_SAMPLES) / 1000.0;    
  // Quy đổi ngược về điện áp thực tế tại chân AO của MQ-135 trước khi qua cầu chia áp
  float vOut = vAdc * DIV_RATIO;                       
  
  // Giới hạn an toàn để chống lỗi toán học chia cho 0
  if (vOut < 0.05) vOut = 0.05;                        
  if (vOut > VCC_SENSOR - 0.05) vOut = VCC_SENSOR - 0.05;
  
  // Công thức tính điện trở màng cảm biến Rs: Rs = RL * (Vcc - Vout) / Vout
  return RL_KOHM * (VCC_SENSOR - vOut) / vOut;         
}

// Chuyển đổi từ điện trở Rs sang nồng độ khí CO2 quy đổi (ppm) dựa trên tỷ số Rs/R0
float rsToPpm(float rs) {
  float ratio = rs / R0_KOHM;
  float ppm = PARA * pow(ratio, -PARB);
  // Không ghim cứng ở 400ppm để có thể quan sát được biến thiên điện áp thực tế
  if (ppm < 10.0) ppm = 10.0;   
  if (ppm > 10000.0) ppm = 10000.0;
  return ppm;
}

// Bắt đầu quá trình hiệu chuẩn R0 trong không khí sạch (kéo dài 10 giây)
void startCalibration() {
  calibrating = true; 
  calStart = millis(); 
  calSum = 0; 
  calCount = 0;
  Serial.println("EVT,CAL_START (Dat mach trong khong khi sach trong 10 giay)");
}

// Kết thúc quá trình tính toán và lưu R0 mới vào bộ nhớ Flash NVS
void finishCalibration() {
  float rsAir = calSum / calCount;
  // Tại nồng độ không khí sạch (400 ppm): R0 = Rs / ((400/PARA)^(-1/PARB))
  float ratio400 = pow(CLEAN_PPM / PARA, -1.0 / PARB);
  R0_KOHM = rsAir / ratio400;
  
  // Ghi vào bộ nhớ không bay hơi để không bị mất khi mất điện/reset
  prefs.putFloat("r0", R0_KOHM);
  ppmFiltered = CLEAN_PPM;
  calibrating = false;
  Serial.printf("EVT,CAL_DONE,R0=%.2f\n", R0_KOHM);
}

// =================================================================================
// [ĐÁNH GIÁ MỨC ĐỘ CẢNH BÁO VỚI VÙNG TRỄ CHỐNG NHẤP NHÁY (HYSTERESIS)]
// =================================================================================
int levelFromPpm(float ppm, int prev) {
  if (prev == 2) { 
    if (ppm > PPM_RED - HYST) return 2; 
  } else if (ppm > PPM_RED) {
    return 2;
  }
  
  if (prev >= 1) { 
    if (ppm >= PPM_WARN - HYST) return 1; 
  } else if (ppm >= PPM_WARN) {
    return 1;
  }
  
  return 0; // An toàn (Dưới 1000 ppm)
}

// =================================================================================
// [XỬ LÝ LỆNH TRUYỀN TỪ MÁY CHỦ PYTHON QUA CỔNG SERIAL]
// =================================================================================
void handleCommand(String c) {
  c.trim(); 
  c.toUpperCase();
  if (c.length() == 0) return;
  unsigned long now = millis();

  if (c == "SLEEP") {
    // Lệnh phát hiện tài xế ngủ gật từ AI Vision -> Bật chuông dồn dập 6 giây
    sleepUntil = now + SLEEP_DURATION_MS;
    Serial.println("EVT,ACK,SLEEP");
  } else if (c.startsWith("ALERT:")) {
    // Nhận mức cảnh báo định danh từ server: ALERT:<level>[:ms]
    int lv = c.substring(6, 7).toInt();
    unsigned long dur = 5000;
    int p = c.indexOf(':', 6);
    if (p > 0) dur = c.substring(p + 1).toInt();
    if (lv >= 1 && lv <= 2) {
      cmdLevel = lv;
      cmdForever = (dur == 0);
      cmdUntil = now + dur;
      Serial.printf("EVT,ACK,ALERT,%d\n", lv);
    }
  } else if (c == "STOP") {
    // Tắt toàn bộ chuông báo động thủ công
    cmdLevel = 0; 
    cmdForever = false; 
    sleepUntil = 0;
    Serial.println("EVT,ACK,STOP");
  } else if (c == "CAL") {
    startCalibration();
  } else if (c == "PING") {
    Serial.println("PONG");
  }
}

// Đọc ký tự từ cổng nối tiếp Serial không chặn luồng (Non-blocking)
void readSerialCommands() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') { 
      handleCommand(rxBuf); 
      rxBuf = ""; 
    } else if (ch != '\r' && rxBuf.length() < 40) {
      rxBuf += ch;
    }
  }
}

// =================================================================================
// [CẬP NHẬT TRẠNG THÁI ÂM THANH VÀ ĐÈN LED (KHÔNG DÙNG HÀM DELAY)]
// =================================================================================
void updateAudio(int level, bool sleepActive) {
  unsigned long now = millis();
  bool muted = now < muteUntil;
  
  // Tắt loa và LED nếu đang trong thời gian Mute hoặc trạng thái an toàn
  if (muted || (level == 0 && !sleepActive)) {
    speakerOff(); 
    digitalWrite(LED_PIN, LOW); 
    return;
  }
  
  if (sleepActive) {                       
    // Cảnh báo ngủ gật: Nháy còi dồn dập xen kẽ giữa 2 tần số 2200Hz và 3200Hz
    unsigned long phase = (now / SLEEP_BEEP_MS) % 4;
    if (phase == 0) { 
      speakerTone(FREQ_SLEEP1); 
      digitalWrite(LED_PIN, HIGH); 
    } else if (phase == 2) { 
      speakerTone(FREQ_SLEEP2); 
      digitalWrite(LED_PIN, HIGH); 
    } else { 
      speakerOff();             
      digitalWrite(LED_PIN, LOW);  
    }
  } else if (level == 2) {                 
    // Mức ĐỎ (Nguy hiểm): Chuông hú liên tục ở tần số 3000Hz
    speakerTone(FREQ_RED); 
    digitalWrite(LED_PIN, HIGH);
  } else if (level == 1) {                 
    // Mức VÀNG (Cảnh báo): Bíp từng nhịp ngắt quãng (300ms kêu, 700ms nghỉ)
    unsigned long phase = now % (WARN_ON_MS + WARN_OFF_MS);
    if (phase < WARN_ON_MS) { 
      speakerTone(FREQ_WARN); 
      digitalWrite(LED_PIN, HIGH); 
    } else { 
      speakerOff();           
      digitalWrite(LED_PIN, LOW);  
    }
  }
}

// =================================================================================
// [HÀM KHỞI TẠO HỆ THỐNG - SETUP]
// =================================================================================
void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  pinMode(MUTE_PIN, INPUT_PULLUP);
  
  // Cấu hình chân ADC của ESP32 để đo điện áp đến ~3.1V
  analogReadResolution(12);
  analogSetPinAttenuation(MQ_PIN, ADC_11db);
  speakerInit();

  // Khôi phục giá trị R0 đã lưu trong bộ nhớ Flash NVS
  prefs.begin("mq135", false);
  R0_KOHM = prefs.getFloat("r0", R0_KOHM);

  Serial.println("EVT,BOOT");
  Serial.printf("EVT,R0=%.2f\n", R0_KOHM);
  
  // Phát 1 tiếng bíp ngắn báo hiệu ESP32 đã khởi động thành công
  speakerTone(1500); 
  delay(120); 
  speakerOff();
}

// =================================================================================
// [VÒNG LẶP CHÍNH - LOOP]
// =================================================================================
void loop() {
  unsigned long now = millis();
  readSerialCommands(); // Quét nhận lệnh từ cổng USB

  // Kiểm tra nút nhấn tắt tiếng (Mute)
  static bool lastBtn = HIGH;
  bool btn = digitalRead(MUTE_PIN);
  if (lastBtn == HIGH && btn == LOW) { 
    muteUntil = now + MUTE_DURATION_MS; 
    Serial.println("EVT,MUTE"); 
  }
  lastBtn = btn;

  // Thu thập và xử lý tín hiệu cảm biến mỗi 100ms
  if (now - lastSample >= 100) {
    lastSample = now;
    float rs = readRsKohm();
    if (calibrating) {
      calSum += rs; 
      calCount++;
      if (now - calStart >= 10000) finishCalibration();
    } else {
      float ppm = rsToPpm(rs);
      // Bộ lọc mũ số EMA: Giúp số liệu mượt mà, triệt tiêu xung nhiễu đột ngột
      ppmFiltered = EMA_ALPHA * ppm + (1.0 - EMA_ALPHA) * ppmFiltered;
    }
  }

  // Kiểm tra thời gian làm nóng (Warm-up 60 giây)
  bool warming = now < WARMUP_MS;

  // Xác định cấp độ cảnh báo nồng độ khí
  if (warming || calibrating) {
    coLevel = 0;
  } else {
    coLevel = levelFromPpm(ppmFiltered, coLevel);
  }

  // Kiểm tra thời hạn của lệnh điều khiển từ máy tính
  if (cmdLevel > 0 && !cmdForever && now > cmdUntil) {
    cmdLevel = 0;
  }
  bool sleepActive = now < sleepUntil;

  // Lựa chọn cấp độ cao nhất giữa nồng độ CO2 và lệnh máy tính
  int level = max(coLevel, cmdLevel);
  if (sleepActive) level = 2; // Buồn ngủ luôn được gán mức ưu tiên cao nhất (Mức Đỏ)

  const char* src = "NONE";
  if (sleepActive) src = "SLEEP";
  else if (cmdLevel > 0 && cmdLevel >= coLevel) src = "CMD";
  else if (coLevel > 0) src = "CO2";

  // Cập nhật trạng thái chuông loa và đèn LED theo thời gian thực
  updateAudio(level, sleepActive);

  // Báo sự kiện lên máy tính chỉ khi có sự thay đổi cấp độ
  if (level != lastReportedLevel) {
    Serial.printf("EVT,LEVEL,%d,%s,%d\n", level, src, (int)ppmFiltered);
    lastReportedLevel = level;
  }

  // Đẩy gói tin Telemetry lên máy tính chu kỳ 500ms một lần
  if (now - lastTelemetry >= 500) {
    lastTelemetry = now;
    if (warming) {
      Serial.printf("CO2:%d,ADC:%d,LV:0,SRC:WARMUP\n", (int)ppmFiltered, adcRaw);
    } else if (calibrating) {
      Serial.printf("CO2:%d,ADC:%d,LV:0,SRC:CAL\n", (int)ppmFiltered, adcRaw);
    } else {
      Serial.printf("CO2:%d,ADC:%d,LV:%d,SRC:%s\n", (int)ppmFiltered, adcRaw, level, src);
    }
  }
}
