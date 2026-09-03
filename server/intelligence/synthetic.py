"""Reproducible synthetic collections history with hidden ground truth.

    python -m server.intelligence.synthetic --seed 42 --n 1000 --live 10

Why synthetic: the demo database has two borrowers and no history, so
there is nothing to analyse. Rather than pretend otherwise, this generates
a population whose structure is *known* - four behavioural segments, an
evening-contact effect that only exists for one of them, a reminder effect
that only exists for two, and one effect (weekday) that is pure noise. The
analysis in R never sees the labels; the evaluation step compares what R
recovered against data/synthetic/ground_truth.json. That is the point: it
tests whether the method finds real structure and, just as importantly,
whether it correctly finds nothing where nothing was planted.

Two outputs:

- The historical cohort (closed accounts, Feb-Jul 2026) goes straight into
  the analytics tables intel_borrowers / interaction_events.
- A small "live book" of open accounts is written to
  data/synthetic/live_book.json in seed.json's shape and loaded by
  server/seed.py, so the dashboard shows a realistic book with real call
  history rather than one empty row. Their events reach the analytics
  tables through the same extractor a real call would (extract.py).

Strategy is assigned at random per borrower. That is a simulated
randomised trial, which is what makes the strategy comparison in the
statistics clean; a real book would need confounder control instead, and
the findings say so.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from .. import config
from ..db import get_conn
from . import events as ev
from .schema import init_intel_db, insert_intel_rows

SYNTH_DIR = Path(config.BASE_DIR) / "data" / "synthetic"
GENERATOR_VERSION = "synth-v1"

# ---- Ground truth ---------------------------------------------------------
#
# p_answer: chance a call is picked up, by time of day. The evening lift for
# delayed_responsive is the planted contact-time effect; the other segments
# are flat-ish on purpose so a naive "evening is better" pooled result is
# partly a Simpson's-paradox trap the stratified analysis should resolve.
#
# reminder_lift: added to promise completion when a reminder went out the
# day before. Zero-ish for prompt_payer and avoidant, large for the two
# middle segments - the planted reminder effect.

SEGMENTS = {
    "prompt_payer": {
        "share": 0.30,
        "p_answer": {"day": 0.68, "evening": 0.72},
        "on_answer": {"paid": 0.46, "promised": 0.36, "objection": 0.09, "refused": 0.06, "human": 0.02, "dispute": 0.01},
        "promise_completion": 0.78,
        "reminder_lift": 0.03,
        "response_time_mean": 1800,
        "amount_log_mean": 8.3,
    },
    "delayed_responsive": {
        "share": 0.30,
        "p_answer": {"day": 0.32, "evening": 0.72},
        "on_answer": {"paid": 0.16, "promised": 0.58, "objection": 0.14, "refused": 0.08, "human": 0.025, "dispute": 0.015},
        "promise_completion": 0.42,
        "reminder_lift": 0.32,
        "response_time_mean": 7200,
        "amount_log_mean": 8.6,
    },
    "hardship": {
        "share": 0.20,
        "p_answer": {"day": 0.46, "evening": 0.50},
        "on_answer": {"paid": 0.08, "promised": 0.36, "objection": 0.40, "refused": 0.09, "human": 0.04, "dispute": 0.03},
        "promise_completion": 0.33,
        "reminder_lift": 0.22,
        "response_time_mean": 14400,
        "amount_log_mean": 8.9,
    },
    "avoidant": {
        "share": 0.20,
        "p_answer": {"day": 0.12, "evening": 0.17},
        "on_answer": {"paid": 0.10, "promised": 0.32, "objection": 0.12, "refused": 0.38, "human": 0.04, "dispute": 0.04},
        "promise_completion": 0.24,
        "reminder_lift": 0.04,
        "response_time_mean": 28800,
        "amount_log_mean": 8.5,
    },
}

# Randomised per borrower. reminder_p is the chance a reminder is sent the
# day before a promise date; bucket weights are morning/afternoon/evening.
STRATEGIES = {
    "standard": {"buckets": (0.35, 0.45, 0.20), "reminder_p": 0.30},
    "reminder_first": {"buckets": (0.35, 0.45, 0.20), "reminder_p": 1.00},
    "evening_contact": {"buckets": (0.10, 0.10, 0.80), "reminder_p": 0.30},
}

# Planted null: nothing in the simulation depends on weekday. If the
# analysis reports a weekday effect, the analysis is wrong.
NULL_EFFECTS = ["weekday"]

HORIZON_DAYS = 84
# An account runs through repeated repayment cycles (DUE_NOW_PCT of the
# balance every CYCLE_DAYS, mirroring the policy), so a borrower who pays
# promptly is still contacted ten-odd times before the balance clears.
# That is what gives each borrower enough history to have a behavioural
# signature at all - two calls is a coin flip, twelve is a pattern.
MAX_ATTEMPTS = 24
HIST_OPEN_START = datetime(2026, 2, 1)
HIST_OPEN_END = datetime(2026, 5, 15)
HIST_CENSOR = datetime(2026, 7, 31, 23, 59)
LIVE_OPEN_START = datetime(2026, 7, 6)
LIVE_OPEN_END = datetime(2026, 7, 22)
LIVE_CENSOR = datetime(2026, 7, 31, 23, 59)

FIRST_NAMES = [
    "Aisha", "Ben", "Carla", "Dev", "Elena", "Farid", "Grace", "Hiro", "Ines", "Jonas",
    "Kemi", "Luis", "Maya", "Noor", "Omar", "Priya", "Quinn", "Rosa", "Sami", "Tara",
    "Uma", "Vik", "Wren", "Xiu", "Yara", "Zane", "Amir", "Bea", "Cyrus", "Dana",
]
LAST_NAMES = [
    "Adeyemi", "Brooks", "Castillo", "Dubois", "Ekwueme", "Fischer", "Garcia", "Haddad",
    "Iyer", "Jensen", "Kowalski", "Lindqvist", "Moreau", "Nakamura", "Okafor", "Petrov",
    "Quintero", "Rahman", "Silva", "Tanaka", "Umar", "Vasquez", "Walsh", "Xu", "Yilmaz", "Zhang",
]


def _weighted_choice(rng: random.Random, table: dict[str, float]) -> str:
    keys = list(table)
    return rng.choices(keys, weights=[table[k] for k in keys], k=1)[0]


def _pick_hour(rng: random.Random, strategy: str) -> int:
    weights = STRATEGIES[strategy]["buckets"]
    bucket = rng.choices(["morning", "afternoon", "evening"], weights=weights, k=1)[0]
    lo, hi = ev.BUCKETS[bucket]
    return rng.randrange(lo, hi)


def _at(day: datetime, hour: int, rng: random.Random) -> datetime:
    return day.replace(hour=hour, minute=rng.randrange(0, 60), second=0, microsecond=0)


class Borrower:
    def __init__(self, debt_id: str, name: str, segment: str, strategy: str, amount: float, opened_at: datetime, censor_at: datetime):
        self.debt_id = debt_id
        self.name = name
        self.segment = segment
        self.strategy = strategy
        self.amount_due = amount
        self.opened_at = opened_at
        self.censor_at = censor_at
        self.events: list[dict] = []
        self.calls: list[dict] = []  # operational shape, live book only
        self.sms: list[dict] = []
        self.paid_amount = 0.0
        self.first_payment_at: datetime | None = None
        self.final_outcome = "open"
        self.closed_at: datetime | None = None
        self.last_call_outcome: str | None = None
        self.last_summary = ""
        self.promise_date: datetime | None = None

    # -- event helpers ---------------------------------------------------

    def _event(self, when: datetime, event_type: str, channel: str, outcome: str, **extra) -> dict:
        event_id = f"evt_{self.debt_id}_{len(self.events) + 1:03d}"
        row = ev.build_event_fields(
            self.debt_id, event_id, when, event_type, channel, outcome, self.strategy,
            self.amount_due - self.paid_amount, **extra,
        )
        self.events.append(row)
        return row

    def _record_call(self, when: datetime, op_outcome: str, summary: str, amount_promised=None, promise_date=None):
        self.calls.append({
            "id": f"call_{self.debt_id}_{len(self.calls) + 1:02d}",
            "debt_id": self.debt_id,
            "started_at": when.isoformat(timespec="seconds"),
            "outcome": op_outcome,
            "transcript": "",
            "summary": summary,
            "amount_promised": amount_promised,
            "promise_date": promise_date.date().isoformat() if promise_date else None,
        })
        self.last_call_outcome = op_outcome
        self.last_summary = summary

    def _record_sms(self, when: datetime, sms_type: str, amount: float | None, body: str, payment_id=None, payment_status="sent"):
        self.sms.append({
            "id": f"sms_{self.debt_id}_{len(self.sms) + 1:02d}",
            "debt_id": self.debt_id,
            "payment_id": payment_id,
            "sent_at": when.isoformat(timespec="seconds"),
            "type": sms_type,
            "amount": amount,
            "body": body,
            "payment_link": f"/pay/{payment_id}" if payment_id else None,
            "payment_status": payment_status,
        })

    # -- the simulation --------------------------------------------------

    def _pay(self, when: datetime, amount: float, rng: random.Random, response_time: float):
        outstanding = self.amount_due - self.paid_amount
        amount = min(amount, outstanding)
        self.paid_amount += amount
        outcome = ev.PAID_FULL if self.paid_amount >= self.amount_due - 0.01 else ev.PAID_PARTIAL
        pay_id = f"pay_{self.debt_id}_{len(self.sms) + 1:02d}"
        self._record_sms(when - timedelta(seconds=response_time), "payment_link", amount, f"Pay ${amount:.0f} here: /pay/{pay_id}", pay_id, "paid")
        self._event(when - timedelta(seconds=response_time), "sms", "sms", ev.LINK_SENT, amount_offered=amount)
        self._event(when, "payment", "link", outcome, amount_paid=amount, response_time_seconds=response_time)
        self._record_sms(when, "confirmation", amount, f"Payment received: ${amount:.0f}. Thank you.", None, "paid")
        if self.first_payment_at is None:
            self.first_payment_at = when

    def _cleared(self, when: datetime) -> bool:
        if self.paid_amount >= self.amount_due - 0.01:
            self.final_outcome = "paid"
            self.closed_at = when
            return True
        return False

    def simulate(self, rng: random.Random):
        seg = SEGMENTS[self.segment]
        strat = STRATEGIES[self.strategy]
        due_now = round(self.amount_due * config.DUE_NOW_PCT / 100, 2)
        day = self.opened_at
        attempts = 0

        while attempts < MAX_ATTEMPTS and day <= self.censor_at and self.final_outcome == "open":
            hour = _pick_hour(rng, self.strategy)
            when = _at(day, hour, rng)
            bucket = ev.bucket_for_hour(hour)
            p_answer = seg["p_answer"]["evening" if bucket == "evening" else "day"]
            attempts += 1

            if rng.random() >= p_answer:
                self._event(when, "call_attempt", "voice", ev.NO_ANSWER)
                self._record_call(when, "no_answer", "No answer.")
                day = day + timedelta(days=rng.randint(2, 4))
                continue

            what = _weighted_choice(rng, seg["on_answer"])
            response_time = max(120.0, rng.expovariate(1 / seg["response_time_mean"]))

            if what == "paid":
                self._event(when, "call_attempt", "voice", ev.ANSWERED_PAID, amount_offered=due_now)
                self._record_call(when, "paid", f"Agreed to pay ${due_now:.0f} today; link sent.")
                paid_at = when + timedelta(seconds=response_time)
                self._pay(paid_at, due_now, rng, response_time)
                if self._cleared(paid_at):
                    break
                # Next instalment falls due one cycle after this payment.
                day = paid_at.replace(hour=0, minute=0, second=0) + timedelta(days=config.CYCLE_DAYS)
                continue

            if what == "promised":
                promise_day = day + timedelta(days=rng.randint(2, 7))
                promise_at = _at(promise_day, 10, rng)
                self._event(when, "call_attempt", "voice", ev.ANSWERED_PROMISED, amount_offered=due_now, meta={"promise_days": (promise_day - day).days})
                self._record_call(when, "promised", f"Promised ${due_now:.0f} on {promise_day.date().isoformat()}.", due_now, promise_day)
                self.promise_date = promise_at
                reminded = rng.random() < strat["reminder_p"]
                if reminded and promise_day - timedelta(days=1) > when:
                    rem_at = _at(promise_day - timedelta(days=1), 9, rng)
                    if rem_at <= self.censor_at:
                        self._event(rem_at, "sms", "sms", ev.REMINDER_SENT, amount_offered=due_now)
                        self._record_sms(rem_at, "reminder", due_now, f"Reminder: ${due_now:.0f} is due tomorrow on your account.")
                if promise_at > self.censor_at:
                    break
                p_complete = seg["promise_completion"] + (seg["reminder_lift"] if reminded else 0.0)
                if rng.random() < p_complete:
                    paid_at = promise_at + timedelta(seconds=response_time)
                    self._pay(paid_at, due_now, rng, response_time)
                    self.last_call_outcome = "paid"
                    if self._cleared(paid_at):
                        break
                    day = paid_at.replace(hour=0, minute=0, second=0) + timedelta(days=config.CYCLE_DAYS)
                    continue
                # Missed the promise. The scheduler would notice at the
                # promise time; the next attempt follows a few days later.
                self._event(promise_at, "sms", "sms", ev.LINK_SENT, amount_offered=due_now, meta={"missed_promise": True})
                self._record_sms(promise_at, "payment_link", due_now, f"Pay ${due_now:.0f} here: /pay/pay_{self.debt_id}_{len(self.sms) + 1:02d}", f"pay_{self.debt_id}_{len(self.sms) + 1:02d}", "sent")
                self.last_call_outcome = "missed"
                day = promise_day + timedelta(days=rng.randint(1, 3))
                continue

            if what == "objection":
                self._event(when, "call_attempt", "voice", ev.ANSWERED_OBJECTION)
                self._record_call(when, "answered", "Said they cannot afford the amount right now; no agreement reached.")
                day = day + timedelta(days=rng.randint(3, 6))
                continue

            if what == "refused":
                self._event(when, "call_attempt", "voice", ev.ANSWERED_REFUSED)
                self._record_call(when, "answered", "Refused to discuss payment; call ended politely.")
                day = day + timedelta(days=rng.randint(5, 8))
                continue

            if what == "human":
                self._event(when, "call_attempt", "voice", ev.REQUESTED_HUMAN)
                self._event(when + timedelta(minutes=1), "escalation", "system", ev.NEEDS_REVIEW, meta={"reason": "requested human agent"})
                self._record_call(when, "needs_review", "requested human agent")
                self.final_outcome = "needs_review"
                self.closed_at = when
                break

            # dispute
            self._event(when, "call_attempt", "voice", ev.DISPUTE)
            self._event(when + timedelta(minutes=1), "escalation", "system", ev.NEEDS_REVIEW, meta={"reason": "disputes the debt"})
            self._record_call(when, "needs_review", "Disputes the debt - says the balance is wrong.")
            self.final_outcome = "needs_review"
            self.closed_at = when
            break

    # -- summaries -------------------------------------------------------

    def survival(self) -> tuple[float, int]:
        """(follow-up days, observed) for time-to-first-payment. Censored at
        the horizon or escalation if no payment landed."""
        start = self.opened_at
        if self.first_payment_at is not None:
            return round((self.first_payment_at - start).total_seconds() / 86400, 2), 1
        end = min(self.closed_at or self.censor_at, self.censor_at)
        return round(max(0.0, (end - start).total_seconds() / 86400), 2), 0

    def intel_row(self, cohort: str) -> dict:
        days, observed = self.survival()
        final = self.final_outcome
        if final == "open" and self.paid_amount > 0:
            final = "partial"
        return {
            "debt_id": self.debt_id,
            "cohort": cohort,
            "amount_due": self.amount_due,
            "strategy": self.strategy,
            "opened_at": self.opened_at.isoformat(timespec="seconds"),
            "closed_at": self.closed_at.isoformat(timespec="seconds") if self.closed_at else None,
            "final_outcome": final,
            "paid": 1 if self.first_payment_at else 0,
            "days_to_payment": days,
            "observed": observed,
        }

    def operational_status(self) -> tuple[str, str | None, str | None]:
        """(status, next_action, next_action_at) as the app would leave it."""
        next_at = f"{config.DEMO_CLOCK_START[:10]}T09:00:00"
        if self.final_outcome == "needs_review":
            return "needs_review", "human_review", None
        if self.paid_amount >= self.amount_due - 0.01:
            return "paid", None, None
        if self.last_call_outcome == "missed":
            return "missed", "call_borrower", next_at
        if self.last_call_outcome == "promised" and self.promise_date and self.promise_date > self.censor_at:
            return "promised", "check_payment_status", self.promise_date.isoformat(timespec="seconds")
        if self.last_call_outcome == "paid":
            # Paid this cycle; the next instalment is due a cycle later.
            return "scheduled", "call_borrower", next_at
        if self.last_call_outcome == "no_answer":
            return "no_answer", "call_borrower", next_at
        if self.last_call_outcome is None:
            return "new", "call_borrower", next_at
        return "scheduled", "call_borrower", next_at


def _make_population(rng: random.Random, n: int, prefix: str, open_start: datetime, open_end: datetime, censor: datetime) -> list[Borrower]:
    seg_names = list(SEGMENTS)
    seg_weights = [SEGMENTS[s]["share"] for s in seg_names]
    strat_names = list(STRATEGIES)
    span = (open_end - open_start).days
    out = []
    for i in range(1, n + 1):
        segment = rng.choices(seg_names, weights=seg_weights, k=1)[0]
        strategy = rng.choice(strat_names)
        amount = round(math.exp(rng.gauss(SEGMENTS[segment]["amount_log_mean"], 0.5)) / 10) * 10
        amount = max(200.0, float(amount))
        opened = open_start + timedelta(days=rng.randrange(0, span + 1))
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        # Follow-up stops at the horizon or the data cut, whichever is first.
        b = Borrower(f"{prefix}_{i:04d}", name, segment, strategy, amount, opened, min(censor, opened + timedelta(days=HORIZON_DAYS)))
        b.simulate(rng)
        out.append(b)
    return out


def _write_historical(borrowers: list[Borrower]):
    with get_conn() as conn:
        conn.execute("DELETE FROM interaction_events WHERE cohort = 'historical'")
        conn.execute("DELETE FROM intel_borrowers WHERE cohort = 'historical'")
        for b in borrowers:
            r = b.intel_row("historical")
            events = [{**e, "cohort": "historical"} for e in b.events]
            insert_intel_rows(conn, r, events)


def _live_book(borrowers: list[Borrower], rng: random.Random) -> dict:
    debts, calls, sms = [], [], []
    for b in borrowers:
        status, next_action, next_at = b.operational_status()
        promised = 0.0
        if status == "promised" and b.calls:
            promised = b.calls[-1].get("amount_promised") or 0.0
        debts.append({
            "id": b.debt_id,
            "name": b.name,
            "account_ref": f"SW-{rng.randrange(1000, 9999)}-{rng.randrange(1000, 9999)}",
            "phone": f"+1555{rng.randrange(1000000, 9999999)}",
            "amount_due": b.amount_due,
            "amount_collected": round(b.paid_amount, 2),
            "amount_promised": promised,
            "due_date": b.opened_at.date().isoformat(),
            "status": status,
            "last_call_summary": b.last_summary,
            "next_action_at": next_at,
            "next_action": next_action,
            # Kept so the extractor can attribute the randomised strategy
            # to live events without a hidden lookup table.
            "strategy": b.strategy,
        })
        calls.extend(b.calls)
        sms.extend(b.sms)
    return {"debts": debts, "calls": calls, "sms_messages": sms, "memory": [], "agent_actions": []}


def generate(seed: int = 42, n: int = 1000, n_live: int = 10) -> dict:
    init_intel_db()
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    historical = _make_population(rng, n, "hist", HIST_OPEN_START, HIST_OPEN_END, HIST_CENSOR)
    _write_historical(historical)

    # Live accounts: opened recently, still mostly open at the demo clock
    # start, so the dashboard book has history to reason from. Drawn
    # oversize then trimmed so the demo isn't dominated by closed accounts.
    live_rng = random.Random(seed + 1)
    candidates = _make_population(live_rng, n_live * 3, "live", LIVE_OPEN_START, LIVE_OPEN_END, LIVE_CENSOR)
    # Mostly open accounts, plus a couple already escalated so the review
    # queue has something in it before anyone has said "I want a human".
    escalated = [b for b in candidates if b.final_outcome == "needs_review"][:2]
    still_open = [b for b in candidates if b.final_outcome == "open"]
    live = (still_open[: n_live - len(escalated)] + escalated)[:n_live]
    book = _live_book(live, live_rng)
    (SYNTH_DIR / "live_book.json").write_text(json.dumps(book, indent=2))

    truth = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "n_historical": n,
        "n_live": len(live),
        "segments": {b.debt_id: b.segment for b in historical + live},
        "planted_effects": {
            "evening_contact": {"applies_to": ["delayed_responsive"], "description": "P(answer) 0.32 -> 0.72 in 17:00-20:00 for delayed_responsive only; other segments +0.04-0.05"},
            "reminder_after_promise": {"applies_to": ["delayed_responsive", "hardship"], "lift": {"delayed_responsive": 0.32, "hardship": 0.22}},
            "segments_separable": True,
        },
        "null_effects": NULL_EFFECTS,
        "segment_parameters": SEGMENTS,
        "strategies": STRATEGIES,
    }
    (SYNTH_DIR / "ground_truth.json").write_text(json.dumps(truth, indent=2))

    summary = {
        "seed": seed,
        "historical": n,
        "live": len(live),
        "events": sum(len(b.events) for b in historical),
        "paid_rate": round(sum(1 for b in historical if b.first_payment_at) / n, 3),
        "review_rate": round(sum(1 for b in historical if b.final_outcome == "needs_review") / n, 3),
    }
    (SYNTH_DIR / "manifest.json").write_text(json.dumps({**summary, "generator_version": GENERATOR_VERSION}, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--live", type=int, default=10)
    args = ap.parse_args()
    print(json.dumps(generate(args.seed, args.n, args.live), indent=2))


if __name__ == "__main__":
    main()
