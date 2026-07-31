import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS debts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    amount_due REAL NOT NULL,
    due_date TEXT,
    breach_date TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    salary_date TEXT,
    last_call_summary TEXT DEFAULT '',
    next_action_at TEXT,
    next_action TEXT DEFAULT 'Call borrower'
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
    sent_at TEXT NOT NULL,
    type TEXT NOT NULL,
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
"""


def init_db():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(SCHEMA)
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
