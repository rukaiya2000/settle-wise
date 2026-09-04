import json
import sys

from . import config
from .db import CURRENT_TIME, get_conn, init_db, on_conflict_replace


def reset_db():
    """Restore the demo to its starting state.

    Rewinding only the clock isn't enough to re-run a demo: advancing time
    fires the scheduler, which permanently changes borrower status, so a
    second run would start from 'paid'/'needs_review' instead of 'new'.
    Debts are dropped too rather than upserted, so a borrower removed from
    seed.json actually disappears instead of lingering.
    """
    init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM calls")
        conn.execute("DELETE FROM sms_messages")
        conn.execute("DELETE FROM memory")
        # Without this the previous run's tool trace survives the reset and
        # shows up under "what the agent did" on the next call.
        conn.execute("DELETE FROM agent_actions")
        conn.execute("DELETE FROM debts")
    seed()


def seed():
    init_db()
    with open(config.SEED_PATH) as f:
        data = json.load(f)
    _load(data)
    print(f"Seeded {config.DB_PATH} from {config.SEED_PATH}")

    # The synthetic live book (server/intelligence/synthetic.py) is loaded
    # on top of seed.json so "Reset DB" restores a realistic book with call
    # history, not just the two hand-written demo borrowers.
    live_book = config.BASE_DIR / "data" / "synthetic" / "live_book.json"
    if live_book.exists():
        with open(live_book) as f:
            _load(json.load(f))
        print(f"Loaded synthetic live book from {live_book}")


DEBT_COLUMNS = [
    "id", "name", "account_ref", "phone", "amount_due", "amount_collected", "amount_promised",
    "due_date", "status", "last_call_summary", "next_action_at", "next_action",
]
CALL_COLUMNS = ["id", "debt_id", "started_at", "outcome", "transcript", "summary", "amount_promised", "promise_date"]
SMS_COLUMNS = ["id", "debt_id", "payment_id", "sent_at", "type", "amount", "body", "payment_link", "payment_status"]
MEMORY_COLUMNS = ["id", "debt_id", "key", "value", "learned_at"]
ACTION_COLUMNS = ["id", "debt_id", "tool", "arguments", "result", "source", "at"]


def _load(data: dict):
    with get_conn() as conn:
        for d in data.get("debts", []):
            conn.execute(
                """INSERT INTO debts
                (id, name, account_ref, phone, amount_due, amount_collected, amount_promised, due_date, status,
                 last_call_summary, next_action_at, next_action)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
                + on_conflict_replace("id", DEBT_COLUMNS),
                (
                    d["id"], d["name"], d.get("account_ref"), d["phone"], d["amount_due"],
                    d.get("amount_collected", 0), d.get("amount_promised", 0),
                    d.get("due_date"), d.get("status", "new"),
                    d.get("last_call_summary", ""),
                    d.get("next_action_at"), d.get("next_action", "call_borrower"),
                ),
            )
        for c in data.get("calls", []):
            conn.execute(
                """INSERT INTO calls
                (id, debt_id, started_at, outcome, transcript, summary, amount_promised, promise_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
                + on_conflict_replace("id", CALL_COLUMNS),
                (
                    c["id"], c["debt_id"], c["started_at"], c.get("outcome"),
                    c.get("transcript", ""), c.get("summary", ""),
                    c.get("amount_promised"), c.get("promise_date"),
                ),
            )
        for s in data.get("sms_messages", []):
            conn.execute(
                """INSERT INTO sms_messages
                (id, debt_id, payment_id, sent_at, type, amount, body, payment_link, payment_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
                + on_conflict_replace("id", SMS_COLUMNS),
                (
                    s["id"], s["debt_id"], s.get("payment_id"), s["sent_at"], s["type"],
                    s.get("amount"), s["body"], s.get("payment_link"), s.get("payment_status", "none"),
                ),
            )
        for m in data.get("memory", []):
            conn.execute(
                """INSERT INTO memory (id, debt_id, key, value, learned_at)
                VALUES (?, ?, ?, ?, ?)"""
                + on_conflict_replace("id", MEMORY_COLUMNS),
                (m["id"], m["debt_id"], m["key"], m["value"], m["learned_at"]),
            )
        for a in data.get("agent_actions", []):
            conn.execute(
                """INSERT INTO agent_actions
                (id, debt_id, tool, arguments, result, source, at)
                VALUES (?, ?, ?, ?, ?, ?, ?)"""
                + on_conflict_replace("id", ACTION_COLUMNS),
                (a["id"], a["debt_id"], a["tool"], a.get("arguments"), a.get("result"),
                 a.get("source", "voice"), a["at"]),
            )
        if "demo_clock" in data:
            dc = data["demo_clock"]
            conn.execute(
                f"UPDATE demo_clock SET {CURRENT_TIME} = ?, timezone = ?, speed = ? WHERE id = 1",
                (dc["current_time"], dc.get("timezone", config.DEMO_CLOCK_TIMEZONE), dc.get("speed", "paused")),
            )


if __name__ == "__main__":
    reset_db() if len(sys.argv) > 1 and sys.argv[1] == "reset" else seed()
