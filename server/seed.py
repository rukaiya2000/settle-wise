import json

from . import config
from .db import get_conn, init_db


def seed():
    init_db()
    with open(config.SEED_PATH) as f:
        data = json.load(f)

    with get_conn() as conn:
        for d in data.get("debts", []):
            conn.execute(
                """INSERT OR REPLACE INTO debts
                (id, name, phone, amount_due, amount_collected, amount_promised, due_date, breach_date, status,
                 salary_date, last_call_summary, next_action_at, next_action)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    d["id"], d["name"], d["phone"], d["amount_due"],
                    d.get("amount_collected", 0), d.get("amount_promised", 0),
                    d.get("due_date"), d.get("breach_date"), d.get("status", "new"),
                    d.get("salary_date", ""), d.get("last_call_summary", ""),
                    d.get("next_action_at"), d.get("next_action", "call_borrower"),
                ),
            )
        for c in data.get("calls", []):
            conn.execute(
                """INSERT OR REPLACE INTO calls
                (id, debt_id, started_at, outcome, transcript, summary, amount_promised, promise_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c["id"], c["debt_id"], c["started_at"], c.get("outcome"),
                    c.get("transcript", ""), c.get("summary", ""),
                    c.get("amount_promised"), c.get("promise_date"),
                ),
            )
        for s in data.get("sms_messages", []):
            conn.execute(
                """INSERT OR REPLACE INTO sms_messages
                (id, debt_id, payment_id, sent_at, type, amount, body, payment_link, payment_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    s["id"], s["debt_id"], s.get("payment_id"), s["sent_at"], s["type"],
                    s.get("amount"), s["body"], s.get("payment_link"), s.get("payment_status", "none"),
                ),
            )
        for m in data.get("memory", []):
            conn.execute(
                """INSERT OR REPLACE INTO memory (id, debt_id, key, value, learned_at)
                VALUES (?, ?, ?, ?, ?)""",
                (m["id"], m["debt_id"], m["key"], m["value"], m["learned_at"]),
            )
        if "demo_clock" in data:
            dc = data["demo_clock"]
            conn.execute(
                "UPDATE demo_clock SET current_time = ?, timezone = ?, speed = ? WHERE id = 1",
                (dc["current_time"], dc.get("timezone", config.DEMO_CLOCK_TIMEZONE), dc.get("speed", "paused")),
            )

    print(f"Seeded {config.DB_PATH} from {config.SEED_PATH}")


if __name__ == "__main__":
    seed()
