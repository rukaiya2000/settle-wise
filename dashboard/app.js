const money = (value) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(
    Number(value) || 0,
  );

let debts = [];
let demoClock = null;

// Mirrors server/routes/dashboard.py:_validate_repayment_terms so bad input
// never round-trips to the server just to bounce back.
function validateRepaymentFields(dueNowPct, floorPct, cycleDays) {
  if (dueNowPct != null && !(dueNowPct > 0 && dueNowPct <= 100)) return "Repayment % must be between 0 and 100.";
  if (floorPct != null && !(floorPct > 0 && floorPct <= 100)) return "Floor % must be between 0 and 100.";
  if (dueNowPct != null && floorPct != null && floorPct > dueNowPct) return "Floor % cannot exceed repayment %.";
  if (cycleDays != null && !(cycleDays > 0)) return "Cycle days must be a positive number.";
  return null;
}

function emptyToNull(value) {
  return value === "" || value === undefined ? null : value;
}

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

// due_date / breach_date are plain "YYYY-MM-DD" with no time component, so
// they can't go through formatClock (which expects a timestamp). Parsed as
// UTC and rendered as UTC so the date never shifts by a day for viewers
// west or east of the demo timezone.
function formatDate(iso) {
  if (!iso) return "-";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const [, y, mo, d] = m;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(Date.UTC(+y, +mo - 1, +d)));
}

// Days from the DEMO clock, not real today - the whole point of the demo
// clock is that "now" is whatever it says.
function daysUntil(iso) {
  if (!iso || !demoClock) return null;
  const target = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  const now = /^(\d{4})-(\d{2})-(\d{2})/.exec(demoClock.current_time);
  if (!target || !now) return null;
  const t = Date.UTC(+target[1], +target[2] - 1, +target[3]);
  const n = Date.UTC(+now[1], +now[2] - 1, +now[3]);
  return Math.round((t - n) / 86400000);
}

function dueLabel(iso) {
  const days = daysUntil(iso);
  if (days === null) return "";
  if (days < 0) return `${-days}d overdue`;
  if (days === 0) return "due today";
  if (days === 1) return "tomorrow";
  return `in ${days}d`;
}

function dueClass(iso) {
  const days = daysUntil(iso);
  if (days === null) return "";
  if (days < 0) return "overdue";
  if (days <= 3) return "urgent";
  return "";
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
    .map((d) => {
      const outstanding = (d.amount_due || 0) - (d.amount_collected || 0);
      // Only worth showing the original total when part of it is already paid.
      const collectedNote =
        d.amount_collected > 0 ? `<div class="subtle">${money(d.amount_collected)} of ${money(d.amount_due)} paid</div>` : "";
      const nextAt = d.next_action_at ? `<div class="subtle">${formatClock(d.next_action_at)}</div>` : "";
      const nextAction = d.next_action
        ? `${d.next_action.replace(/_/g, " ")}${nextAt}`
        : '<span class="subtle">-</span>';
      return `
        <tr class="clickable" data-id="${d.id}">
          <td>
            <div class="borrower-name">${d.name}</div>
            <div class="subtle">${d.phone}</div>
          </td>
          <td>
            <strong>${money(outstanding)}</strong>
            ${collectedNote}
          </td>
          <td>
            ${formatDate(d.due_date)}
            <div class="due-note ${dueClass(d.due_date)}">${dueLabel(d.due_date)}</div>
          </td>
          <td>
            <span class="status ${d.status}">${d.status.replace(/_/g, " ")}</span>
            ${["needs_review", "missed", "no_answer", "scheduled", "callback_requested"].includes(d.status) && d.last_call_summary ? `<div class="status-reason">${d.last_call_summary}</div>` : ""}
          </td>
          <td class="next-action">${nextAction}</td>
          <td>
            <button class="row-run" data-call="${d.id}">Call</button>
            <button class="row-run ghost" data-sms="${d.id}">SMS</button>
          </td>
        </tr>
      `;
    })
    .join("");
}

// "SW-6693-4520" -> "SW-••••-4520". Masks every digit but the last four,
// keeping the separators so the shape of the reference is still recognisable.
function maskRef(ref) {
  if (!ref) return "";
  const total = (ref.match(/\d/g) || []).length;
  let seen = 0;
  return ref.replace(/\d/g, (ch) => {
    seen += 1;
    return seen > total - 4 ? ch : "•";
  });
}

function feedItem(title, meta, body) {
  return `<div class="feed-item"><div class="feed-title">${title}</div><div class="feed-meta">${meta}</div>${body || ""}</div>`;
}

// Per-customer repayment overrides (server/agent/tools.py:effective_policy) -
// null means this borrower falls back to the global policy default.
function renderRepaymentSettings(debt, progress) {
  const rows = [
    ["Repayment % / cycle", debt.due_now_percent_override, "%"],
    ["Floor %", debt.min_payment_today_percent_override, "%"],
    ["Cycle length", debt.cycle_days_override, " days"],
  ];
  document.querySelector("#repaymentView").innerHTML = rows
    .map(([label, value, unit]) => {
      const custom = value !== null && value !== undefined;
      const shown = custom ? `${value}${unit}` : "Policy default";
      return `<div><span class="term-label">${label}:</span> <span class="term-value${custom ? " custom" : ""}">${shown}</span></div>`;
    })
    .join("");

  document.querySelector("#rpDueNowPct").value = debt.due_now_percent_override ?? "";
  document.querySelector("#rpFloorPct").value = debt.min_payment_today_percent_override ?? "";
  document.querySelector("#rpCycleDays").value = debt.cycle_days_override ?? "";

  renderPaymentSchedule(progress);
}

// Resolved dollar schedule from server/offer_engine.py:payment_schedule -
// due_now/floor already reflect this debt's overrides (or the policy
// default), computed forward from today, not a stale fixed calendar date.
function renderPaymentSchedule(progress) {
  const el = document.querySelector("#repaymentSchedule");
  if (!progress || !progress.schedule) {
    el.innerHTML = "";
    return;
  }
  if (!progress.schedule.length) {
    el.innerHTML = '<div class="feed-empty">Nothing left to collect.</div>';
    return;
  }

  const cycles = progress.cycles_to_clear;
  const summary = `
    <div class="schedule-summary">
      ${money(progress.due_now)} due each cycle, every ${progress.cycle_days} day${progress.cycle_days === 1 ? "" : "s"}
      &middot; floor ${money(progress.minimum_acceptable_today)}
      &middot; ${cycles} cycle${cycles === 1 ? "" : "s"} to clear
    </div>`;

  const rows = progress.schedule
    .map(
      (c) => `
      <div class="schedule-row">
        <span>${formatDate(c.on)} <span class="due-note ${dueClass(c.on)}">${dueLabel(c.on)}</span></span>
        <span>${money(c.amount)}</span>
      </div>`,
    )
    .join("");

  const more = progress.more_cycles > 0
    ? `<div class="subtle schedule-more">+${progress.more_cycles} more cycle${progress.more_cycles === 1 ? "" : "s"} after this</div>`
    : "";

  el.innerHTML = summary + rows + more;
}

async function loadProgress(debtId) {
  const [detail, progress] = await Promise.all([
    api(`/api/debts/${debtId}`),
    api(`/api/debts/${debtId}/progress`),
  ]);

  document.querySelector("#progName").textContent = detail.debt.name;
  // Kept as the bare number - the call/SMS confirm dialogs read this.
  document.querySelector("#progPhone").textContent = detail.debt.phone;

  // Masked deliberately: the last 4 is the only part anyone needs (it's what
  // the agent asks for), and showing the whole reference would leak the full
  // value into any screenshot or screen-share of this page.
  const ref = detail.debt.account_ref;
  document.querySelector("#progRef").innerHTML = ref
    ? `Account ref <span class="ref-value">${maskRef(ref)}</span>`
    : "";

  // The detail page previously jumped straight from the name to the metric
  // cards, so the two things an operator most needs - when it's due and what
  // happens next - were nowhere on the page.
  const d = detail.debt;
  // A status like "needs review" is alarming but meaningless on its own -
  // the reason was previously buried further down the page, so the obvious
  // (wrong) assumption was that it related to the dates beside it.
  const flagged = ["needs_review", "missed", "no_answer", "scheduled", "callback_requested"].includes(d.status);
  const statusReason =
    flagged && d.last_call_summary ? `<div class="status-reason">${d.last_call_summary}</div>` : "";

  const facts = [
    ["Status", `<span class="status ${d.status}">${d.status.replace(/_/g, " ")}</span>${statusReason}`],
    ["Due date", `${formatDate(d.due_date)} <span class="due-note ${dueClass(d.due_date)}">${dueLabel(d.due_date)}</span>`],
    ["Breach date", `${formatDate(d.breach_date)} <span class="due-note ${dueClass(d.breach_date)}">${dueLabel(d.breach_date)}</span>`],
    [
      "Next action",
      d.next_action
        ? `${d.next_action.replace(/_/g, " ")}${d.next_action_at ? ` <span class="subtle">${formatClock(d.next_action_at)}</span>` : ""}`
        : "<span class='subtle'>none scheduled</span>",
    ],
    ["Salary date", d.salary_date || "<span class='subtle'>unknown</span>"],
  ];
  document.querySelector("#progFacts").innerHTML = facts
    .map(([k, v]) => `<div class="fact"><dt>${k}</dt><dd>${v}</dd></div>`)
    .join("");

  renderRepaymentSettings(d, progress);

  const cards = [
    { label: "Outstanding", value: money(progress.amount_due - progress.amount_collected) },
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
          let link = "";
          if (s.payment_id && s.payment_status !== "paid") {
            link = `<div class="pay-open"><button data-pay="${s.payment_id}" data-amount="${s.amount || 0}">Open payment link</button></div>`;
          } else if (s.payment_id) {
            link = `<div class="paid-tag">&check; Paid</div>`;
          }
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
  const turns = last && last.transcript ? last.transcript.split("\n").filter((l) => l.trim()) : [];
  if (turns.length) {
    transcriptEl.innerHTML = turns
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

  // An empty "what the agent did" column left half the panel blank, which
  // read as broken rather than empty. Give the transcript the full width
  // instead and drop the column entirely.
  const hasActions = actions.length > 0;
  document.querySelector("#agentStepsWrap").classList.toggle("hidden", !hasActions);
  document.querySelector("#lastCallSplit").classList.toggle("single", !hasActions);

  // Say what's inside while it's shut, so collapsing doesn't hide whether
  // there is anything worth opening.
  const parts = [];
  if (hasActions) parts.push(`${actions.length} action${actions.length === 1 ? "" : "s"}`);
  if (turns.length) parts.push(`${turns.length} turn${turns.length === 1 ? "" : "s"}`);
  document.querySelector("#lastCallToggle").textContent = parts.length
    ? `Call details — ${parts.join(" · ")}`
    : "Call details";
}

function setCallStatus(state, text) {
  const el = document.querySelector("#callStatus");
  el.classList.remove("hidden", "connecting", "connected", "error");
  if (state) el.classList.add(state);
  el.textContent = text || "";
}

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
  if (hash !== lastRoutedHash) {
    setCallStatus(null, "");
    document.querySelector("#callStatus").classList.add("hidden");
  }
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

document.querySelector("#resetDemo").addEventListener("click", async () => {
  await api("/api/reset-demo", { method: "POST" });
  window.location.hash = "";
  await loadClock();
  await route();
});

// ---- Checkout modal --------------------------------------------------
//
// The same POST the borrower's phone hits (/pay/:id/complete), so paying from
// the dashboard and paying from the SMS link go through one code path and one
// double-tap guard. Kept in-page so the money visibly lands on the progress
// bar behind the modal instead of in a tab nobody is looking at.

const payOverlay = document.querySelector("#payOverlay");
const payBody = document.querySelector("#payBody");

function closePayModal() {
  payOverlay.classList.add("hidden");
  payBody.innerHTML = "";
}

function openPayModal(paymentId, amount) {
  const name = document.querySelector("#progName").textContent || "this account";
  payBody.innerHTML = `
    <div class="pay-brand">SettleWise</div>
    <div class="pay-sub">Secure payment</div>
    <div class="pay-amount-label">Amount due today</div>
    <div class="pay-amount">${money(amount)}</div>
    <div class="pay-rows">
      <div class="pay-row"><span>Account</span><span>${name}</span></div>
      <div class="pay-row"><span>Reference</span><span>${paymentId}</span></div>
    </div>
    <button class="pay-submit" id="paySubmit">Pay ${money(amount)}</button>
    <div class="pay-note">Demo checkout. No real payment is taken and no card
    details are collected.</div>`;
  payOverlay.classList.remove("hidden");

  document.querySelector("#paySubmit").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.textContent = "Processing...";
    const existingError = payBody.querySelector(".pay-error");
    if (existingError) existingError.remove();
    try {
      const result = await api(`/pay/${paymentId}/complete`, { method: "POST" });
      const shortfall = result.shortfall_this_cycle || 0;
      const shortfallNote = shortfall > 0
        ? `<div class="pay-shortfall">${money(shortfall)} still due this cycle - it'll carry into the upcoming schedule.</div>`
        : "";
      payBody.innerHTML = `
        <div class="pay-done">
          <div class="pay-tick">&check;</div>
          <h3>Payment received</h3>
          <div class="pay-sub">${money(amount)} paid. Thank you, ${name}.</div>
          ${shortfallNote}
          <button class="pay-submit" id="payDone">Done</button>
        </div>`;
      // Refresh underneath first, so closing reveals the new balance rather
      // than the old one flashing to the new one.
      const debtId = window.location.hash.replace(/^#\/?/, "");
      if (debtId) await loadProgress(debtId);
      document.querySelector("#payDone").addEventListener("click", closePayModal);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = `Pay ${money(amount)}`;
      btn.insertAdjacentHTML("afterend", `<div class="pay-error">Payment failed: ${err.message}</div>`);
    }
  });
}

document.querySelector("#smsHistory").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-pay]");
  if (btn) openPayModal(btn.dataset.pay, Number(btn.dataset.amount));
});

document.querySelector("#payClose").addEventListener("click", closePayModal);
payOverlay.addEventListener("click", (e) => {
  if (e.target === payOverlay) closePayModal();
});

// ---- Edit repayment terms (person progress page) ---------------------

document.querySelector("#repaymentEditToggle").addEventListener("click", () => {
  document.querySelector("#repaymentForm").classList.remove("hidden");
  document.querySelector("#repaymentEditToggle").classList.add("hidden");
});

document.querySelector("#repaymentCancel").addEventListener("click", () => {
  document.querySelector("#repaymentForm").classList.add("hidden");
  document.querySelector("#repaymentEditToggle").classList.remove("hidden");
  document.querySelector("#repaymentError").classList.add("hidden");
});

document.querySelector("#repaymentForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const debtId = window.location.hash.replace(/^#\/?/, "");
  const errorEl = document.querySelector("#repaymentError");
  errorEl.classList.add("hidden");

  const dueNowPct = emptyToNull(document.querySelector("#rpDueNowPct").value);
  const floorPct = emptyToNull(document.querySelector("#rpFloorPct").value);
  const cycleDays = emptyToNull(document.querySelector("#rpCycleDays").value);
  const body = {
    due_now_percent: dueNowPct === null ? null : Number(dueNowPct),
    min_payment_today_percent: floorPct === null ? null : Number(floorPct),
    cycle_days: cycleDays === null ? null : Number(cycleDays),
  };

  const validationError = validateRepaymentFields(body.due_now_percent, body.min_payment_today_percent, body.cycle_days);
  if (validationError) {
    errorEl.textContent = validationError;
    errorEl.classList.remove("hidden");
    return;
  }

  const button = document.querySelector("#repaymentSave");
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Saving...";
  try {
    await api(`/api/debts/${debtId}/update`, { method: "POST", body: JSON.stringify(body) });
    document.querySelector("#repaymentForm").classList.add("hidden");
    document.querySelector("#repaymentEditToggle").classList.remove("hidden");
    await loadProgress(debtId);
  } catch (err) {
    errorEl.textContent = `Save failed: ${err.message}`;
    errorEl.classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
});

// ---- Add customer modal -----------------------------------------------

const addCustomerOverlay = document.querySelector("#addCustomerOverlay");
const addCustomerForm = document.querySelector("#addCustomerForm");
const addCustomerError = document.querySelector("#addCustomerError");

function openAddCustomerModal() {
  addCustomerForm.reset();
  addCustomerError.classList.add("hidden");
  addCustomerOverlay.classList.remove("hidden");
  document.querySelector("#acName").focus();
}

function closeAddCustomerModal() {
  addCustomerOverlay.classList.add("hidden");
}

document.querySelector("#addCustomerButton").addEventListener("click", openAddCustomerModal);
document.querySelector("#addCustomerClose").addEventListener("click", closeAddCustomerModal);
addCustomerOverlay.addEventListener("click", (e) => {
  if (e.target === addCustomerOverlay) closeAddCustomerModal();
});

addCustomerForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  addCustomerError.classList.add("hidden");

  const dueNowPct = emptyToNull(document.querySelector("#acDueNowPct").value);
  const floorPct = emptyToNull(document.querySelector("#acFloorPct").value);
  const cycleDays = emptyToNull(document.querySelector("#acCycleDays").value);
  const body = {
    name: document.querySelector("#acName").value.trim(),
    phone: document.querySelector("#acPhone").value.trim(),
    amount_due: Number(document.querySelector("#acAmount").value),
    breach_date: emptyToNull(document.querySelector("#acBreachDate").value),
    salary_date: emptyToNull(document.querySelector("#acSalaryDate").value),
    due_now_percent: dueNowPct === null ? null : Number(dueNowPct),
    min_payment_today_percent: floorPct === null ? null : Number(floorPct),
    cycle_days: cycleDays === null ? null : Number(cycleDays),
  };

  if (!body.name || !body.phone) {
    addCustomerError.textContent = "Name and phone are required.";
    addCustomerError.classList.remove("hidden");
    return;
  }
  if (!(body.amount_due > 0)) {
    addCustomerError.textContent = "Amount due must be positive.";
    addCustomerError.classList.remove("hidden");
    return;
  }
  const validationError = validateRepaymentFields(body.due_now_percent, body.min_payment_today_percent, body.cycle_days);
  if (validationError) {
    addCustomerError.textContent = validationError;
    addCustomerError.classList.remove("hidden");
    return;
  }

  const button = document.querySelector("#addCustomerSubmit");
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Adding...";
  try {
    await api("/api/debts", { method: "POST", body: JSON.stringify(body) });
    closeAddCustomerModal();
    await loadDebts();
  } catch (err) {
    addCustomerError.textContent = `Failed to add customer: ${err.message}`;
    addCustomerError.classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!payOverlay.classList.contains("hidden")) closePayModal();
  if (!addCustomerOverlay.classList.contains("hidden")) closeAddCustomerModal();
});

window.addEventListener("hashchange", route);
window.addEventListener("focus", route);

(async function init() {
  await loadClock();
  await route();
})();
