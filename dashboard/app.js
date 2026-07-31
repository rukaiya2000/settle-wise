const money = (value) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(
    Number(value) || 0,
  );

const NEEDS_CALL_STATUSES = ["new", "scheduled", "no_answer", "callback_requested"];
const PROMISED_STATUSES = ["promised", "link_sent"];

let debts = [];
let demoClock = null;
let currentFilter = "all";

async function api(path, options) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options && options.headers) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.status === 204 ? null : res.json();
}

function daysBetween(fromIso, toIso) {
  if (!fromIso || !toIso) return null;
  const ms = new Date(toIso) - new Date(fromIso);
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

function formatClock(iso) {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

async function loadClock() {
  demoClock = await api("/api/demo-clock");
  document.querySelector("#clockValue").textContent = formatClock(demoClock.current_time);
}

async function loadDebts() {
  debts = await api("/api/debts");
  renderMetrics();
  renderTable();
}

function renderMetrics() {
  const totalDue = debts.reduce((s, d) => s + d.amount_due, 0);
  const totalCollected = debts.reduce((s, d) => s + d.amount_collected, 0);
  const totalPromised = debts.reduce((s, d) => s + d.amount_promised, 0);
  const needsReview = debts.filter((d) => d.status === "needs_review").length;
  const recoveryPct = totalDue > 0 ? Math.round((totalCollected / totalDue) * 100) : 0;

  const cards = [
    { label: "Collected", value: money(totalCollected) },
    { label: "Promised", value: money(totalPromised) },
    { label: "Recovery rate", value: `${recoveryPct}%` },
    { label: "Needs review", value: String(needsReview) },
  ];

  document.querySelector("#metricsRow").innerHTML = cards
    .map((c) => `<div class="metric"><div class="value">${c.value}</div><div class="label">${c.label}</div></div>`)
    .join("");
}

function filteredDebts() {
  if (currentFilter === "all") return debts;
  if (currentFilter === "needs_call") return debts.filter((d) => NEEDS_CALL_STATUSES.includes(d.status));
  if (currentFilter === "promised") return debts.filter((d) => PROMISED_STATUSES.includes(d.status));
  return debts.filter((d) => d.status === currentFilter);
}

function renderTable() {
  const now = demoClock ? demoClock.current_time : null;
  const rows = [...filteredDebts()].sort((a, b) => {
    if (a.breach_date !== b.breach_date) return a.breach_date < b.breach_date ? -1 : 1;
    return b.amount_due - a.amount_due;
  });

  document.querySelector("#debtTable").innerHTML = rows
    .map((d) => {
      const days = daysBetween(now, d.breach_date);
      const daysLabel = days === null ? "" : days < 0 ? `${-days}d overdue` : `${days}d to breach`;
      const canRun = d.status !== "paid" && d.status !== "needs_review";
      return `
        <tr class="clickable" data-id="${d.id}">
          <td>
            <div class="borrower-name">${d.name}</div>
            <div class="subtle">${d.phone}${d.salary_date ? " · salary " + d.salary_date : ""}</div>
          </td>
          <td>
            <strong>${d.breach_date || "-"}</strong>
            <div class="subtle">${daysLabel}</div>
          </td>
          <td>${money(d.amount_due)}</td>
          <td><span class="status ${d.status}">${d.status.replace(/_/g, " ")}</span></td>
          <td class="subtle">${d.next_action ? d.next_action.replace(/_/g, " ") : "-"}</td>
          <td>
            ${canRun ? `<button class="row-run" data-run="${d.id}">Run agent</button>` : ""}
          </td>
        </tr>
      `;
    })
    .join("");
}

function feedItem(title, meta, body) {
  return `<div class="feed-item"><div class="feed-title">${title}</div><div class="feed-meta">${meta}</div>${body || ""}</div>`;
}

async function loadProgress(debtId) {
  const [detail, progress] = await Promise.all([
    api(`/api/debts/${debtId}`),
    api(`/api/debts/${debtId}/progress`),
  ]);

  document.querySelector("#progName").textContent = detail.debt.name;
  document.querySelector("#progPhone").textContent = detail.debt.phone;

  const canRun = detail.debt.status !== "paid" && detail.debt.status !== "needs_review";
  const runBtn = document.querySelector("#runAgentButton");
  runBtn.disabled = !canRun;
  runBtn.textContent =
    detail.debt.status === "no_answer" || detail.debt.status === "scheduled" ? "Retry now" : "Run agent";

  const cards = [
    { label: "Amount due", value: money(progress.amount_due) },
    { label: "Collected", value: money(progress.amount_collected) },
    { label: "Promised", value: money(progress.amount_promised) },
    { label: "Calls made", value: String(progress.calls_made) },
    { label: "SMS links sent", value: String(progress.sms_links_sent) },
  ];
  document.querySelector("#progMetrics").innerHTML = cards
    .map((c) => `<div class="metric"><div class="value">${c.value}</div><div class="label">${c.label}</div></div>`)
    .join("");

  const covered = progress.amount_collected + progress.amount_promised;
  const pct = progress.amount_due > 0 ? Math.min(100, Math.round((progress.amount_collected / progress.amount_due) * 100)) : 0;
  document.querySelector("#progressBarFill").style.width = `${pct}%`;
  document.querySelector("#progressBarLabel").textContent =
    `${money(progress.amount_collected)} collected` +
    (progress.amount_promised > 0 ? ` + ${money(progress.amount_promised)} promised` : "") +
    ` / ${money(progress.amount_due)} total`;

  const calls = detail.calls;
  document.querySelector("#callHistory").innerHTML = calls.length
    ? calls
        .map((c) =>
          feedItem(
            c.outcome ? c.outcome.replace(/_/g, " ") : "call",
            formatClock(c.started_at),
            `<div class="subtle">${c.summary || ""}</div>`,
          ),
        )
        .reverse()
        .join("")
    : '<div class="feed-empty">No calls yet.</div>';

  const sms = detail.sms_messages;
  document.querySelector("#smsHistory").innerHTML = sms.length
    ? sms
        .map((s) => {
          const link =
            s.payment_id && s.payment_status !== "paid"
              ? `<div><a href="/pay/${s.payment_id}" target="_blank">Open payment link &rarr;</a></div>`
              : "";
          return feedItem(
            s.type.replace(/_/g, " "),
            `${formatClock(s.sent_at)} · ${s.payment_status}${s.amount ? " · " + money(s.amount) : ""}`,
            `<div class="subtle">${s.body}</div>${link}`,
          );
        })
        .reverse()
        .join("")
    : '<div class="feed-empty">No SMS yet.</div>';

  const memory = detail.memory;
  document.querySelector("#memoryList").innerHTML = memory.length
    ? memory.map((m) => feedItem(m.key.replace(/_/g, " "), formatClock(m.learned_at), `<div>${m.value}</div>`)).join("")
    : '<div class="feed-empty">Nothing learned yet.</div>';

  document.querySelector("#runResult").classList.add("hidden");
}

async function runAgent(debtId) {
  const res = await api(`/api/debts/${debtId}/run-agent`, { method: "POST" });
  return res.result;
}

function showRunResult(result) {
  const box = document.querySelector("#runResult");
  box.classList.remove("hidden");
  box.textContent = `Agent result: ${JSON.stringify(result)}`;
}

function setView(view) {
  document.querySelector("#profilesView").classList.toggle("hidden", view !== "profiles");
  document.querySelector("#progressView").classList.toggle("hidden", view !== "progress");
}

async function route() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash) {
    setView("progress");
    await loadProgress(hash);
  } else {
    setView("profiles");
    await loadDebts();
  }
}

document.querySelector("#debtTable").addEventListener("click", async (e) => {
  const runBtn = e.target.closest("[data-run]");
  if (runBtn) {
    e.stopPropagation();
    runBtn.disabled = true;
    runBtn.textContent = "Running...";
    try {
      await runAgent(runBtn.dataset.run);
    } finally {
      await loadDebts();
    }
    return;
  }
  const row = e.target.closest("tr[data-id]");
  if (row) window.location.hash = `/${row.dataset.id}`;
});

document.querySelector("#filters").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-filter]");
  if (!btn) return;
  currentFilter = btn.dataset.filter;
  document.querySelectorAll("#filters button").forEach((b) => b.classList.toggle("active", b === btn));
  renderTable();
});

document.querySelector("#backButton").addEventListener("click", () => {
  window.location.hash = "";
});

document.querySelector("#runAgentButton").addEventListener("click", async (e) => {
  const debtId = window.location.hash.replace(/^#\/?/, "");
  e.target.disabled = true;
  const original = e.target.textContent;
  e.target.textContent = "Running...";
  try {
    const result = await runAgent(debtId);
    showRunResult(result);
  } finally {
    e.target.textContent = original;
    await loadProgress(debtId);
    await loadClock();
  }
});

document.querySelectorAll("[data-advance]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    await api("/api/demo-clock/advance", {
      method: "POST",
      body: JSON.stringify({ amount: Number(btn.dataset.advance), unit: btn.dataset.unit }),
    });
    await loadClock();
    await route();
  });
});

document.querySelector("#resetClock").addEventListener("click", async () => {
  await api("/api/demo-clock/reset", { method: "POST" });
  await loadClock();
  await route();
});

window.addEventListener("hashchange", route);
window.addEventListener("focus", route);

(async function init() {
  await loadClock();
  await route();
})();
