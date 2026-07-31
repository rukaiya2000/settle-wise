const debts = [
  {
    id: "debt_001",
    name: "Riya Sharma",
    phone: "+1 415 555 0123",
    amountDue: 850,
    breachInDays: 3,
    due: "Aug 5",
    status: "promised",
    salaryDate: "5th",
    nextAction: "SMS reminder on salary morning",
    expected: 650,
    collected: 300,
    promised: 350,
    risk: 200,
    memory: [
      ["salary_date", "Gets salary on the 5th"],
      ["best_call_time", "After 6 PM"],
    ],
  },
  {
    id: "debt_002",
    name: "Marcus Lee",
    phone: "+1 628 555 0188",
    amountDue: 1240,
    breachInDays: 1,
    due: "Aug 2",
    status: "calling",
    salaryDate: "Friday",
    nextAction: "Voice call now, ask for partial today",
    expected: 930,
    collected: 0,
    promised: 930,
    risk: 310,
    memory: [["best_call_time", "Picks up during lunch"]],
  },
  {
    id: "debt_003",
    name: "Anika Patel",
    phone: "+1 510 555 0199",
    amountDue: 420,
    breachInDays: 6,
    due: "Aug 8",
    status: "paid",
    salaryDate: "1st",
    nextAction: "Send SMS confirmation",
    expected: 420,
    collected: 420,
    promised: 0,
    risk: 0,
    memory: [["sms_reminder_time", "Morning reminders work"]],
  },
  {
    id: "debt_004",
    name: "Diego Ramos",
    phone: "+1 650 555 0142",
    amountDue: 980,
    breachInDays: 4,
    due: "Aug 6",
    status: "needs_review",
    salaryDate: "15th",
    nextAction: "Review discount request",
    expected: 500,
    collected: 0,
    promised: 500,
    risk: 480,
    memory: [["discount_signal", "Asked for 20% discount"]],
  },
  {
    id: "debt_005",
    name: "Noor Khan",
    phone: "+1 408 555 0160",
    amountDue: 680,
    breachInDays: 9,
    due: "Aug 11",
    status: "new",
    salaryDate: "10th",
    nextAction: "Schedule voice call tomorrow",
    expected: 430,
    collected: 0,
    promised: 0,
    risk: 680,
    memory: [["salary_date", "Likely paid on 10th"]],
  },
  {
    id: "debt_006",
    name: "Priya Nair",
    phone: "+1 415 555 0177",
    amountDue: 1560,
    breachInDays: 13,
    due: "Aug 15",
    status: "promised",
    salaryDate: "15th",
    nextAction: "SMS link for first installment",
    expected: 1100,
    collected: 250,
    promised: 850,
    risk: 460,
    memory: [
      ["installment_fit", "Prefers two installments"],
      ["best_call_time", "Evenings"],
    ],
  },
];

const smsMessages = [
  {
    name: "Riya Sharma",
    type: "payment_link",
    time: "Today 12:10",
    body: "Pay $300 here: /pay/pay_001",
    status: "clicked",
  },
  {
    name: "Anika Patel",
    type: "confirmation",
    time: "Today 10:44",
    body: "Payment received. Balance is now clear.",
    status: "paid",
  },
  {
    name: "Priya Nair",
    type: "payment_link",
    time: "Today 09:30",
    body: "First installment link sent for $250.",
    status: "paid",
  },
  {
    name: "Noor Khan",
    type: "reminder",
    time: "Tomorrow 09:00",
    body: "Reminder queued before scheduled voice call.",
    status: "scheduled",
  },
];

const runItemsBase = [
  ["Score queue", "Marcus has 1 day to breach and $1,240 due.", "done"],
  ["Start voice call", "Agent opens with full payment, then partial today.", "waiting"],
  ["Send SMS link", "Prepared for agreed amount after call.", "new"],
  ["Update memory", "Save salary date, best call time, promise.", "new"],
];

let selectedHorizon = 7;
let runAdvanced = false;

const money = (value) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

function filteredDebts() {
  return debts.filter((debt) => debt.breachInDays <= selectedHorizon);
}

function renderMetrics() {
  const active = filteredDebts();
  const totalDue = active.reduce((sum, debt) => sum + debt.amountDue, 0);
  const expected = active.reduce((sum, debt) => sum + debt.expected, 0);
  const links = smsMessages.filter((sms) => sms.type === "payment_link").length;
  const riskCount = active.filter(
    (debt) => debt.status === "new" || debt.status === "calling",
  ).length;

  document.querySelector("#expectedRecovered").textContent = money(expected);
  document.querySelector("#expectedRecoveredSubline").textContent =
    `${Math.round((expected / totalDue) * 100)}% of ${money(totalDue)} in horizon`;
  document.querySelector("#callsQueued").textContent = active.filter(
    (debt) => debt.status === "new" || debt.status === "calling",
  ).length;
  document.querySelector("#linksSent").textContent = links;
  document.querySelector("#riskCount").textContent = riskCount;
  document.querySelector("#recoveryMeter").style.width =
    `${Math.min(100, Math.round((expected / totalDue) * 100))}%`;
}

function renderTable() {
  const rows = [...filteredDebts()].sort((a, b) => {
    if (a.breachInDays !== b.breachInDays) return a.breachInDays - b.breachInDays;
    return b.amountDue - a.amountDue;
  });

  document.querySelector("#debtTable").innerHTML = rows
    .map(
      (debt) => `
        <tr>
          <td>
            <div class="borrower-name">${debt.name}</div>
            <div class="subtle">${debt.phone} · salary ${debt.salaryDate}</div>
          </td>
          <td>
            <strong>${debt.due}</strong>
            <div class="subtle">${debt.breachInDays}d to breach</div>
          </td>
          <td>${money(debt.amountDue)}</td>
          <td><span class="status ${debt.status}">${debt.status.replace("_", " ")}</span></td>
          <td>${debt.nextAction}</td>
        </tr>
      `,
    )
    .join("");
}

function renderRunStack() {
  const items = runAdvanced
    ? [
        ["Score queue", "Marcus selected for immediate voice call.", "done"],
        ["Voice call complete", "Borrower agreed to $500 today, $430 Friday.", "done"],
        ["SMS link sent", "Payment link sent for $500.", "done"],
        ["Memory updated", "Saved lunch pickup and Friday salary timing.", "done"],
      ]
    : runItemsBase;

  document.querySelector("#agentRunCopy").textContent = runAdvanced
    ? "Last run converted a high-risk debt into a promise."
    : "Ready to call the next borrowers.";

  document.querySelector("#runStack").innerHTML = items
    .map(
      ([title, meta, state], index) => `
        <div class="run-item ${state}">
          <div class="run-step">${index + 1}</div>
          <div>
            <div class="run-title">${title}</div>
            <div class="run-meta">${meta}</div>
          </div>
          <span class="pill">${state}</span>
        </div>
      `,
    )
    .join("");
}

function renderSmsTimeline() {
  document.querySelector("#smsTimeline").innerHTML = smsMessages
    .map(
      (sms) => `
        <div class="timeline-item ${sms.type}">
          <div class="run-title">${sms.name}</div>
          <div class="timeline-meta">${sms.time} · ${sms.type.replace("_", " ")} · ${sms.status}</div>
          <div class="subtle">${sms.body}</div>
        </div>
      `,
    )
    .join("");
}

function renderMemory() {
  const facts = filteredDebts().flatMap((debt) =>
    debt.memory.map(([key, value]) => ({ name: debt.name, key, value })),
  );

  document.querySelector("#memoryList").innerHTML = facts
    .slice(0, 8)
    .map(
      (fact) => `
        <div class="memory-item">
          <div class="memory-key">${fact.key}</div>
          <div>${fact.value}</div>
          <div class="memory-meta">${fact.name}</div>
        </div>
      `,
    )
    .join("");
}

function chartSeries() {
  const points = Array.from({ length: selectedHorizon }, (_, index) => {
    const day = index + 1;
    const active = debts.filter((debt) => debt.breachInDays <= day);
    const collected = active.reduce((sum, debt) => sum + debt.collected, 0);
    const promised = active.reduce((sum, debt) => sum + debt.promised, 0);
    const risk = active.reduce((sum, debt) => sum + debt.risk, 0);
    return { day, collected, promised, risk };
  });

  if (runAdvanced) {
    return points.map((point) =>
      point.day >= 1
        ? {
            ...point,
            collected: point.collected + 500,
            promised: Math.max(0, point.promised - 70),
            risk: Math.max(0, point.risk - 500),
          }
        : point,
    );
  }

  return points;
}

function drawChart() {
  const canvas = document.querySelector("#progressChart");
  const ctx = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.floor(rect.width * ratio);
  canvas.height = Math.floor(rect.height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

  const width = rect.width;
  const height = rect.height;
  const pad = { top: 16, right: 18, bottom: 36, left: 58 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const series = chartSeries();
  const maxValue =
    Math.max(...series.flatMap((p) => [p.collected, p.promised, p.risk])) * 1.15 || 1;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "#e6edf1";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#6a747c";
  ctx.font = "12px Inter, system-ui, sans-serif";

  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + plotH * (i / 4);
    const value = maxValue * (1 - i / 4);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.fillText(money(value), 8, y + 4);
  }

  const x = (index) =>
    pad.left + (series.length === 1 ? 0 : (plotW * index) / (series.length - 1));
  const y = (value) => pad.top + plotH - (value / maxValue) * plotH;

  function drawLine(key, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    series.forEach((point, index) => {
      const px = x(index);
      const py = y(point[key]);
      if (index === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();

    ctx.fillStyle = color;
    series.forEach((point, index) => {
      ctx.beginPath();
      ctx.arc(x(index), y(point[key]), 4, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  drawLine("risk", "#c33a32");
  drawLine("promised", "#2f6fce");
  drawLine("collected", "#2c9a4b");

  ctx.fillStyle = "#6a747c";
  series.forEach((point, index) => {
    if (index === 0 || index === series.length - 1 || point.day % 3 === 0) {
      ctx.fillText(`D${point.day}`, x(index) - 8, height - 12);
    }
  });
}

function renderAll() {
  renderMetrics();
  renderTable();
  renderRunStack();
  renderSmsTimeline();
  renderMemory();
  drawChart();
}

document.querySelectorAll(".segment").forEach((button) => {
  button.addEventListener("click", () => {
    selectedHorizon = Number(button.dataset.horizon);
    document
      .querySelectorAll(".segment")
      .forEach((segment) => segment.classList.remove("active"));
    button.classList.add("active");
    renderAll();
  });
});

document.querySelector("#runAgentButton").addEventListener("click", () => {
  runAdvanced = !runAdvanced;
  document.querySelector("#runAgentButton").textContent = runAdvanced
    ? "Reset run"
    : "Run next calls";
  renderAll();
});

window.addEventListener("resize", drawChart);
renderAll();
