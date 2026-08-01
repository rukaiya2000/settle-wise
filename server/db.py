import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS debts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    -- Account reference the borrower knows. Its last 4 digits are the shared
    -- secret used to verify identity before any debt detail is disclosed, so
    -- it is deliberately stripped from get_debt_profile - an agent that can
    -- see the answer can leak it or be talked into confirming it.
    account_ref TEXT,
    phone TEXT NOT NULL,
    amount_due REAL NOT NULL,
    amount_collected REAL NOT NULL DEFAULT 0,
    amount_promised REAL NOT NULL DEFAULT 0,
    due_date TEXT,
    breach_date TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    salary_date TEXT,
    last_call_summary TEXT DEFAULT '',
    next_action_at TEXT,
    next_action TEXT DEFAULT 'call_borrower'
);

CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    debt_id TEXT NOT NULL REFERENCES debts(id),
    started_at TEXT NOT NULL,
    outcome TEXT,
    transcript TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    amount_promised REAL,
    promise_date TEXT
);

CREATE TABLE IF NOT EXISTS sms_messages (
    id TEXT PRIMARY KEY,
    debt_id TEXT NOT NULL REFERENCES debts(id),
    payment_id TEXT,
    sent_at TEXT NOT NULL,
    type TEXT NOT NULL,
    amount REAL,
    body TEXT NOT NULL,
    payment_link TEXT,
    payment_status TEXT DEFAULT 'none'
);

CREATE TABLE IF NOT EXISTS memory (
    id TEXT PRIMARY KEY,
    debt_id TEXT NOT NULL REFERENCES debts(id),
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    learned_at TEXT NOT NULL
);

-- Every tool the agent invoked, in order. This is the audit trail behind
-- "what the agent actually did" on the borrower's page: without it a real
-- call leaves only a transcript, with no record of which facts it looked up
-- or which actions it took.
CREATE TABLE IF NOT EXISTS agent_actions (
    id TEXT PRIMARY KEY,
    debt_id TEXT,
    tool TEXT NOT NULL,
    arguments TEXT,
    result TEXT,
    source TEXT NOT NULL DEFAULT 'voice',
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS demo_clock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_time TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
    speed TEXT NOT NULL DEFAULT 'paused'
);

CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY,
    max_discount_percent REAL NOT NULL,
    -- Share of the total balance being collected on this call. The agent asks
    -- for this, not the whole balance.
    due_now_percent REAL NOT NULL DEFAULT 10,
    -- Days between instalments; the same due_now amount repeats on this
    -- cadence until the balance is cleared.
    cycle_days INTEGER NOT NULL DEFAULT 5,
    -- Hard floor: nothing below this is acceptable today. Enforced in
    -- offer_engine, not just the prompt, so the agent can't be talked under it.
    min_payment_today_percent REAL NOT NULL,
    max_installments INTEGER NOT NULL,
    call_attempts_per_day INTEGER NOT NULL,
    allowed_call_hours_start TEXT NOT NULL,
    allowed_call_hours_end TEXT NOT NULL,
    human_review_triggers TEXT NOT NULL
);
"""

DEFAULT_POLICY_ID = "policy_default"


def _migrate(conn):
    """CREATE TABLE IF NOT EXISTS silently does nothing to a table that
    already exists, so columns added later need backfilling explicitly."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(debts)")}
    if "account_ref" not in existing:
        conn.execute("ALTER TABLE debts ADD COLUMN account_ref TEXT")

    pol = {r[1] for r in conn.execute("PRAGMA table_info(policies)")}
    if "due_now_percent" not in pol:
        conn.execute("ALTER TABLE policies ADD COLUMN due_now_percent REAL NOT NULL DEFAULT 10")
    if "cycle_days" not in pol:
        conn.execute("ALTER TABLE policies ADD COLUMN cycle_days INTEGER NOT NULL DEFAULT 5")
    # The floor used to be 20% of the balance; it is now the 5% hard minimum.
    conn.execute(
        "UPDATE policies SET due_now_percent = ?, min_payment_today_percent = ?, cycle_days = ? WHERE id = ?",
        (config.DUE_NOW_PCT, config.MIN_PAYMENT_PCT, config.CYCLE_DAYS, DEFAULT_POLICY_ID),
    )


def init_db():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.execute(
        "INSERT OR IGNORE INTO demo_clock (id, current_time, timezone, speed) VALUES (1, ?, ?, 'paused')",
        (config.DEMO_CLOCK_START, config.DEMO_CLOCK_TIMEZONE),
    )
    conn.execute(
        """INSERT OR IGNORE INTO policies
        (id, max_discount_percent, due_now_percent, cycle_days, min_payment_today_percent, max_installments,
         call_attempts_per_day, allowed_call_hours_start, allowed_call_hours_end, human_review_triggers)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            DEFAULT_POLICY_ID,
            config.MAX_DISCOUNT_PCT,
            config.DUE_NOW_PCT,
            config.CYCLE_DAYS,
            config.MIN_PAYMENT_PCT,
            3,
            2,
            "09:00",
            "20:00",
            "wrong_person,dispute,discount_above_limit,angry_borrower,cannot_pay_anything",
        ),
    )
    conn.commit()
    conn.close()


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None):
    return dict(row) if row is not None else None
