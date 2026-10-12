const socket = io();

let allData = { drowsiness: [], yawning: [], distraction: [], posture: [], co2: [] };

function loadHistory() {
  fetch("/api/history/all")
    .then(r => r.json())
    .then(data => {
      allData = data;
      renderAll(allData);
    });
}

function renderTable(tbodyId, items, rowGenerator) {
  const tb = document.getElementById(tbodyId);
  if (!tb) return;
  tb.innerHTML = items.map(rowGenerator).join("");
}

function renderAll(data) {
  renderTable("tbDrowsiness", data.drowsiness || [], item => 
    `<tr><td>${item.timestamp}</td><td><span class="badge danger">${item.duration}s</span></td></tr>`
  );

  renderTable("tbDistraction", data.distraction || [], item => 
    `<tr><td>${item.timestamp}</td><td><span class="badge danger">${item.duration}s</span></td></tr>`
  );

  renderTable("tbYawning", data.yawning || [], item => 
    `<tr><td>${item.timestamp}</td><td><span class="badge warning">${item.duration}s</span></td></tr>`
  );

  renderTable("tbPosture", data.posture || [], item => 
    `<tr><td>${item.timestamp}</td><td>${item.duration}s</td><td><small>${item.reason || 'Sai tư thế'}</small></td></tr>`
  );

  renderTable("tbCo2", data.co2 || [], item => {
    const badgeClass = item.level === "CRITICAL" ? "badge danger" : "badge warning";
    return `<tr><td>${item.timestamp}</td><td>${item.duration}s</td><td>${item.max_co2} ppm</td><td><span class="${badgeClass}">${item.level}</span></td></tr>`;
  });
}

// Lắng nghe sự kiện thêm mới từ WebSocket
socket.on("new_history_drowsiness", item => {
  allData.drowsiness.unshift(item);
  renderAll(allData);
});

socket.on("new_history_distraction", item => {
  allData.distraction.unshift(item);
  renderAll(allData);
});

socket.on("new_history_yawning", item => {
  allData.yawning.unshift(item);
  renderAll(allData);
});

socket.on("new_history_posture", item => {
  allData.posture.unshift(item);
  renderAll(allData);
});

socket.on("new_history_co2", item => {
  allData.co2.unshift(item);
  renderAll(allData);
});

// Bộ lọc thời gian
function applyFilter() {
  const start = document.getElementById("timeStart").value;
  const end = document.getElementById("timeEnd").value;
  if (!start && !end) return;

  const filterList = list => list.filter(item => {
    const t = item.timestamp;
    if (start && t < start) return false;
    if (end && t > end) return false;
    return true;
  });

  renderAll({
    drowsiness: filterList(allData.drowsiness || []),
    distraction: filterList(allData.distraction || []),
    yawning: filterList(allData.yawning || []),
    posture: filterList(allData.posture || []),
    co2: filterList(allData.co2 || [])
  });
}

function resetFilter() {
  document.getElementById("timeStart").value = "";
  document.getElementById("timeEnd").value = "";
  renderAll(allData);
}

loadHistory();