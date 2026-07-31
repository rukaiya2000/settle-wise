const money = (value) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(
    Number(value) || 0,
  );

let debts = [];
let demoClock = null;

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

async function loadDebts() {
  debts = await api("/api/debts");
  renderTable();
}

async function loadClock() {
  demoClock = await api("/api/demo-clock");
  document.querySelector("#clockValue").textContent = formatClock(demoClock.current_time);
}

function renderTable() {
  const rows = [...debts].sort((a, b) => {
    if (a.due_date !== b.due_date) return a.due_date < b.due_date ? -1 : 1;
    return b.amount_due - a.amount_due;
  });

  document.querySelector("#debtTable").innerHTML = rows
    .map(
      (d) => `
        <tr class="clickable" data-id="${d.id}">
          <td><div class="borrower-name">${d.name}</div></td>
          <td>${d.phone}</td>
          <td>${money(d.amount_due)}</td>
          <td>${d.due_date || "-"}</td>
          <td><span class="status ${d.status}">${d.status.replace(/_/g, " ")}</span></td>
          <td><button class="row-run" data-run="${d.id}">Trigger agent</button></td>
        </tr>
      `,
    )
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
}

async function runAgent(debtId) {
  const res = await api(`/api/debts/${debtId}/run-agent`, { method: "POST" });
  return res.result;
}

function showRunResult(result) {
  window.alert(`Agent result: ${JSON.stringify(result)}`);
}

// a1mobile has no outbound-calling capability (confirmed via its MCP tool
// catalog - no dial/call tool exists), so this is the substitute: a live
// mic/speaker session straight to the same realtime agent via WebRTC.
let activeCall = null; // { pc, audioEl, stream }

function setCallStatus(state, text) {
  const el = document.querySelector("#callStatus");
  el.classList.remove("hidden", "connecting", "connected", "error");
  if (state) el.classList.add(state);
  el.textContent = text || "";
}

async function startBrowserCall(debtId) {
  const button = document.querySelector("#callAgentButton");
  button.disabled = true;
  setCallStatus("connecting", "Requesting microphone access...");

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const pc = new RTCPeerConnection();
    stream.getTracks().forEach((track) => pc.addTrack(track, stream));

    const audioEl = document.createElement("audio");
    audioEl.autoplay = true;
    pc.ontrack = (event) => {
      audioEl.srcObject = event.streams[0];
    };
    document.body.appendChild(audioEl);

    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "connected") {
        setCallStatus("connected", "Connected - talking to agent");
      } else if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
        endBrowserCall();
      }
    };

    setCallStatus("connecting", "Connecting to agent...");
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    await new Promise((resolve) => {
      if (pc.iceGatheringState === "complete") return resolve();
      const check = () => {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", check);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", check);
    });

    const res = await fetch("/api/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: pc.localDescription.sdp,
        type: pc.localDescription.type,
        request_data: { debt_id: debtId },
      }),
    });
    if (!res.ok) throw new Error(`offer failed: ${res.status}`);
    const answer = await res.json();
    await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });

    activeCall = { pc, audioEl, stream };
    button.textContent = "Hang up";
    button.disabled = false;
  } catch (err) {
    setCallStatus("error", `Call failed: ${err.message}`);
    button.disabled = false;
    endBrowserCall();
  }
}

function endBrowserCall() {
  if (activeCall) {
    activeCall.pc.close();
    activeCall.stream.getTracks().forEach((t) => t.stop());
    activeCall.audioEl.remove();
    activeCall = null;
  }
  const button = document.querySelector("#callAgentButton");
  if (button) {
    button.textContent = "Call agent (browser)";
    button.disabled = false;
  }
  setCallStatus(null, "");
  document.querySelector("#callStatus").classList.add("hidden");
}

document.querySelector("#callAgentButton").addEventListener("click", () => {
  if (activeCall) {
    endBrowserCall();
  } else {
    const debtId = window.location.hash.replace(/^#\/?/, "");
    startBrowserCall(debtId);
  }
});

function setView(view) {
  document.querySelector("#profilesView").classList.toggle("hidden", view !== "profiles");
  document.querySelector("#progressView").classList.toggle("hidden", view !== "progress");
}

let lastRoutedHash = null;

async function route() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  // Only hang up on an actual navigation (hash changed) - route() also runs
  // on window focus (to refresh data after paying in another tab), which
  // must not drop an active call just from switching tabs.
  if (hash !== lastRoutedHash) endBrowserCall();
  lastRoutedHash = hash;
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
      const result = await runAgent(runBtn.dataset.run);
      showRunResult(result);
    } finally {
      await loadDebts();
    }
    return;
  }

  const row = e.target.closest("tr[data-id]");
  if (row) window.location.hash = `/${row.dataset.id}`;
});

document.querySelector("#backButton").addEventListener("click", () => {
  window.location.hash = "";
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
