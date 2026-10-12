const socket = io();

const co2Number = document.getElementById("co2Number");
const co2Level = document.getElementById("co2Level");
const alertTag = document.getElementById("priorityAlertTag");
const alertMsg = document.getElementById("alertMsg");
const alertMeta = document.getElementById("alertMeta");
const driverScore = document.getElementById("driverScore");
const scoreBar = document.getElementById("scoreBar");
const aiStatusText = document.getElementById("aiStatusText");
const aiDetailText = document.getElementById("aiDetailText");

// Các thẻ chỉ báo 4 trạng thái
const indEye = document.getElementById("indEye");
const statusEye = document.getElementById("statusEye");
const indYawn = document.getElementById("indYawn");
const statusYawn = document.getElementById("statusYawn");
const indPhone = document.getElementById("indPhone");
const statusPhone = document.getElementById("statusPhone");
const indPosture = document.getElementById("indPosture");
const statusPosture = document.getElementById("statusPosture");

// 1. Nhận luồng số đo CO2 liên tục từ IoT Node
socket.on("sensor_update", (data) => {
  if (co2Number) co2Number.innerText = `${data.co2} ppm`;
  let srcTag = data.is_real_hardware ? " [MQ-135 Thật]" : "";
  if (data.co2 > 1500) {
    if (co2Number) co2Number.style.color = "#ef4444";
    if (co2Level) co2Level.innerText = `Nguy cấp (Ngạt khí cabin)${srcTag}`;
  } else if (data.co2 > 1000) {
    if (co2Number) co2Number.style.color = "#f59e0b";
    if (co2Level) co2Level.innerText = `Cảnh báo (Cần thông gió)${srcTag}`;
  } else {
    if (co2Number) co2Number.style.color = "#4ade80";
    if (co2Level) co2Level.innerText = `Không khí trong lành${srcTag}`;
  }
});

// 2. Nhận cập nhật điểm an toàn
socket.on("score_update", (data) => {
  updateScoreUI(data.score);
});

function updateScoreUI(score) {
  if (driverScore) driverScore.innerText = `${score} / 100`;
  if (scoreBar) {
    scoreBar.style.width = `${score}%`;
    if (score < 60) {
      scoreBar.style.backgroundColor = "#ef4444";
    } else if (score < 85) {
      scoreBar.style.backgroundColor = "#f59e0b";
    } else {
      scoreBar.style.backgroundColor = "#22c55e";
    }
  }
}

// 3. Nhận sự kiện cảnh báo phân cấp (Debounced & Prioritized)
socket.on("alert_event", (alert) => {
  if (alertMsg) alertMsg.innerText = `[${alert.level}] ${alert.message}`;
  if (alertMeta) alertMeta.innerText = `Nguồn: ${alert.source} | Trừ điểm: -${alert.deduct_score} | Lúc: ${alert.timestamp}`;

  if (alert.current_score !== undefined) {
    updateScoreUI(alert.current_score);
  }

  // Đổi màu Tag theo cấp độ
  if (alertTag) {
    alertTag.className = "box card-priority-tag " + 
      (alert.level === "CRITICAL" ? "pulse-critical" : "pulse-warning");
  }

  if (aiStatusText) {
    aiStatusText.innerText = alert.level === "CRITICAL" ? "NGUY HIỂM" : "CẢNH BÁO";
    aiStatusText.style.color = alert.level === "CRITICAL" ? "#ef4444" : "#f59e0b";
  }
  if (aiDetailText) {
    aiDetailText.innerText = alert.message;
  }

  // Cập nhật card chỉ báo nhanh
  if (alert.source.includes("DROWSINESS") || alert.message.includes("Ngủ gật")) {
    setIndicatorWarning(indEye, statusEye, "Ngủ gật!", "danger");
  } else if (alert.source.includes("YAWNING") || alert.message.includes("Ngáp")) {
    setIndicatorWarning(indYawn, statusYawn, "Đang ngáp", "warning");
  } else if (alert.source.includes("PHONE") || alert.message.includes("điện thoại")) {
    setIndicatorWarning(indPhone, statusPhone, "Dùng điện thoại!", "danger");
  } else if (alert.source.includes("POSTURE") || alert.message.includes("tư thế")) {
    setIndicatorWarning(indPosture, statusPosture, "Sai tư thế", "warning");
  }
});

function setIndicatorWarning(cardEl, textEl, text, type) {
  if (!cardEl || !textEl) return;
  cardEl.className = `ind-card active-${type}`;
  textEl.innerText = text;
  textEl.className = `ind-status ${type}`;
  setTimeout(() => {
    cardEl.className = "ind-card";
    textEl.className = "ind-status safe";
    textEl.innerText = "Bình Thường";
  }, 4000);
}

// 4. Nút bấm test kịch bản tức thì
function triggerTestAI(eventType) {
  fetch("/api/demo/trigger_ai", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event: eventType })
  }).then(r => r.json()).then(data => {
    if (data.current_score !== undefined) {
      updateScoreUI(data.current_score);
    }
  });
}

// 5. Khởi tạo trạng thái ban đầu từ server
fetch("/api/status").then(r => r.json()).then(data => {
  if (data.safety_score !== undefined) {
    updateScoreUI(data.safety_score);
  }
  if (data.co2_ppm !== undefined && co2Number) {
    co2Number.innerText = `${data.co2_ppm} ppm`;
  }
}).catch(() => {});