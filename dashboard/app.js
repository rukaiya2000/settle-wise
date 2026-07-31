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

// Every timestamp from the API (demo clock, calls, SMS, memory) is a naive
// wall-clock string in the demo clock's timezone - see demo_clock.timezone,
// America/Los_Angeles. new Date("2026-08-01T09:00:00") would parse that in the
// *viewer's* timezone, so the same demo would read differently on different
// machines. Render the stored digits verbatim instead: treat them as UTC and
// format in UTC, which round-trips them unchanged.
function formatClock(iso, withZone = false) {
  if (!iso) return "--";
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!m) return iso;
  const [, y, mo, d, hh, mm] = m;
  const asUTC = new Date(Date.UTC(+y, +mo - 1, +d, +hh, +mm));

  const text = new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(asUTC);

  return withZone ? `${text} ${zoneLabel(asUTC)}` : text;
}

// "PST" / "PDT" for the demo clock's timezone. Derived from the date so it
// follows daylight saving rather than being hardcoded.
function zoneLabel(date) {
  const tz = (demoClock && demoClock.timezone) || "America/Los_Angeles";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    timeZoneName: "short",
  }).formatToParts(date);
  return (parts.find((p) => p.type === "timeZoneName") || {}).value || "";
}

async function loadDebts() {
  debts = await api("/api/debts");
  renderTable();
}

async function loadClock() {
  demoClock = await api("/api/demo-clock");
  document.querySelector("#clockValue").textContent = formatClock(demoClock.current_time, true);
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
          <td>
            <button class="row-run" data-call="${d.id}">Call</button>
            <button class="row-run ghost" data-sms="${d.id}">SMS</button>
            <button class="row-run ghost" data-run="${d.id}">Trigger agent</button>
          </td>
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
  // Kept as the bare number - the call/SMS confirm dialogs read this.
  document.querySelector("#progPhone").textContent = detail.debt.phone;

  // Staff-only. The agent never sees the reference (it verifies the last 4
  // digits through a tool), but whoever is testing a call needs to know what
  // to say when asked.
  const ref = detail.debt.account_ref;
  document.querySelector("#progRef").innerHTML = ref
    ? `Account ref ${ref} &middot; last 4: <strong>${ref.replace(/\D/g, "").slice(-4)}</strong>`
    : "";

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

  renderLastCall(detail);
}

// Raw tool names mean nothing to someone reading the page, so each one gets a
// plain-English line built from what it actually returned - a lookup reads
// differently from an action that changed something.
const ACTION_LABELS = {
  get_debt_profile: (a) => ["Looked up the account", a.result ? `${money(a.result.amount_due)} due, status "${(a.result.status || "").replace(/_/g, " ")}"` : ""],
  get_memory: (a) => ["Checked what we remember", `${(a.result && a.result.memory ? a.result.memory.length : 0)} fact(s) on file`],
  get_policy: () => ["Checked collections policy", "discount cap, call window, installment limits"],
  check_call_allowed: (a) => ["Checked it was allowed to call", a.result ? (a.result.allowed ? "allowed" : `blocked - ${a.result.reason}`) : ""],
  generate_offer_options: (a) => ["Worked out the repayment options", a.result && a.result.offers ? a.result.offers.map((o) => o.type.replace(/_/g, " ")).join(", ") : ""],
  apply_discount: (a) => ["Checked a discount request", a.result ? (a.result.approved ? `approved - settles at ${money(a.result.settled_amount)}` : `refused - ${a.result.reason}`) : ""],
  send_sms_payment_link: (a) => ["Sent a payment link by SMS", a.args.amount != null ? money(a.args.amount) : ""],
  send_sms: (a) => ["Texted the borrower", a.args.body || ""],
  schedule_sms_reminder: (a) => ["Scheduled an SMS reminder", a.args.send_at ? `for ${formatClock(a.args.send_at)}` : ""],
  schedule_next_action: (a) => ["Scheduled the next step", `${(a.args.next_action || "").replace(/_/g, " ")} at ${formatClock(a.args.next_action_at)}`],
  update_debt_status: (a) => ["Updated the account status", (a.args.status || "").replace(/_/g, " ")],
  write_memory: (a) => ["Remembered something new", `${(a.args.key || "").replace(/_/g, " ")}: ${a.args.value || ""}`],
  mark_needs_review: (a) => ["Escalated to human review", a.args.reason || ""],
  record_call_event: (a) => ["Logged the call outcome", `${(a.args.outcome || "").replace(/_/g, " ")}${a.args.amount_promised != null ? " - promised " + money(a.args.amount_promised) : ""}`],
};

// Lookups vs. actions that changed something - worth telling apart visually.
const READ_TOOLS = new Set(["get_debt_profile", "get_memory", "get_policy", "check_call_allowed", "generate_offer_options", "apply_discount"]);

function parseJson(value, fallback) {
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function renderLastCall(detail) {
  const panel = document.querySelector("#lastCallPanel");
  const calls = detail.calls || [];
  const actions = detail.agent_actions || [];

  if (!calls.length && !actions.length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");

  const last = calls.length ? calls[calls.length - 1] : null;

  document.querySelector("#lastCallMeta").textContent = last
    ? `${formatClock(last.started_at)} · ${(last.outcome || "").replace(/_/g, " ")}`
    : "no call recorded yet";
  document.querySelector("#lastCallSummary").textContent = last && last.summary ? last.summary : "";

  const transcriptEl = document.querySelector("#lastCallTranscript");
  if (last && last.transcript) {
    transcriptEl.innerHTML = last.transcript
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => {
        const isAgent = /^(AI|Agent)\s*:/i.test(line);
        const text = line.replace(/^(AI|Agent|User|Borrower)\s*:\s*/i, "");
        return `<div class="turn ${isAgent ? "agent" : "borrower"}"><span class="who">${isAgent ? "Agent" : "Borrower"}</span>${text}</div>`;
      })
      .join("");
  } else {
    transcriptEl.innerHTML = '<div class="feed-empty">No transcript for this call.</div>';
  }

  const stepsEl = document.querySelector("#agentSteps");
  stepsEl.innerHTML = actions.length
    ? actions
        .map((a) => {
          const args = parseJson(a.arguments, {});
          const result = parseJson(a.result, null);
          const label = ACTION_LABELS[a.tool];
          const [title, detailText] = label ? label({ args, result }) : [a.tool.replace(/_/g, " "), ""];
          const kind = READ_TOOLS.has(a.tool) ? "read" : "write";
          return `
            <li class="step ${kind}">
              <div class="step-title">${title}</div>
              ${detailText ? `<div class="step-detail">${detailText}</div>` : ""}
              <div class="step-tool">${a.tool}</div>
            </li>`;
        })
        .join("")
    : '<div class="feed-empty">No recorded agent actions yet.</div>';
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

document.querySelector("#smsBorrowerButton").addEventListener("click", async (e) => {
  const debtId = window.location.hash.replace(/^#\/?/, "");
  const debt = debts.find((d) => d.id === debtId);
  const name = document.querySelector("#progName").textContent || "this borrower";
  const phone = document.querySelector("#progPhone").textContent || "their number";
  const text = promptSms(name, phone, debt ? debt.amount_due : 0);
  if (!text) return;

  const button = e.target;
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Sending...";
  setCallStatus("connecting", "Sending SMS...");
  try {
    const res = await sendSms(debtId, text);
    setCallStatus("connected", `SMS sent to ${res.name} at ${res.to}`);
  } catch (err) {
    setCallStatus("error", `SMS failed: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = original;
    await loadProgress(debtId);
  }
});

document.querySelector("#callBorrowerButton").addEventListener("click", async (e) => {
  const debtId = window.location.hash.replace(/^#\/?/, "");
  const name = document.querySelector("#progName").textContent || "this borrower";
  const phone = document.querySelector("#progPhone").textContent || "their number";
  if (!confirmCall(name, phone)) return;

  const button = e.target;
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Dialing...";
  setCallStatus("connecting", "Placing call...");
  try {
    const res = await callBorrower(debtId);
    setCallStatus("connected", `Calling ${res.name} at ${res.to} - their phone should ring shortly.`);
  } catch (err) {
    setCallStatus("error", `Call failed: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = original;
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

// Real outbound phone call to the borrower, via Vapi. Distinct from the
// browser call (WebRTC to your own mic) and from "Trigger agent" (the
// deterministic simulator, which never dials out).
async function callBorrower(debtId) {
  return api(`/api/debts/${debtId}/call`, { method: "POST" });
}

// Dialing rings a real phone and can't be taken back, so always confirm the
// name and number first. Returns false if the user cancels.
function confirmCall(name, phone) {
  return window.confirm(
    `Place a real phone call to ${name} at ${phone}?\n\n` +
      `Their phone will ring and the agent will start negotiating.`,
  );
}

async function sendSms(debtId, body) {
  return api(`/api/debts/${debtId}/sms`, {
    method: "POST",
    body: JSON.stringify({ body, type: "custom" }),
  });
}

// Texting is outward-facing and can't be recalled, so show the exact message
// and let it be edited before sending. Returns the text, or null to cancel.
function promptSms(name, phone, amountDue) {
  const suggested = `Hi ${name}, this is SettleWise about the ${money(amountDue)} outstanding on your account. Please get in touch to arrange payment.`;
  return window.prompt(`Send an SMS to ${name} at ${phone}:`, suggested);
}

document.querySelector("#debtTable").addEventListener("click", async (e) => {
  const smsBtn = e.target.closest("[data-sms]");
  if (smsBtn) {
    e.stopPropagation();
    const debt = debts.find((d) => d.id === smsBtn.dataset.sms);
    if (!debt) return;
    const text = promptSms(debt.name, debt.phone, debt.amount_due);
    if (!text) return;

    smsBtn.disabled = true;
    const original = smsBtn.textContent;
    smsBtn.textContent = "Sending...";
    try {
      const res = await sendSms(debt.id, text);
      window.alert(`SMS sent to ${res.name} at ${res.to}`);
    } catch (err) {
      window.alert(`SMS failed: ${err.message}`);
    } finally {
      smsBtn.disabled = false;
      smsBtn.textContent = original;
    }
    return;
  }

  const callBtn = e.target.closest("[data-call]");
  if (callBtn) {
    e.stopPropagation();
    const debt = debts.find((d) => d.id === callBtn.dataset.call);
    if (!confirmCall(debt ? debt.name : "this borrower", debt ? debt.phone : "their number")) return;

    callBtn.disabled = true;
    const original = callBtn.textContent;
    callBtn.textContent = "Calling...";
    try {
      const res = await callBorrower(callBtn.dataset.call);
      window.alert(`Calling ${res.name} at ${res.to}\nStatus: ${res.status}`);
    } catch (err) {
      window.alert(`Call failed: ${err.message}`);
    } finally {
      callBtn.disabled = false;
      callBtn.textContent = original;
    }
    return;
  }

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
