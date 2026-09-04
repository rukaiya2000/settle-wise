"""Database access, over SQLite locally and Postgres when deployed.

Which backend is used depends solely on whether config.DATABASE_URL is set:
unset means the SQLite file this project has always used (so local dev, the
test suite, CI, and the R pipeline in intelligence/ are all unchanged and
need no setup), set means Postgres (Supabase, on the serverless deployment
where there is no writable filesystem to keep a SQLite file on).

Every caller in the codebase goes through get_conn()/row_to_dict()/
rows_to_dicts() below and writes SQLite-flavoured SQL with `?` and `:name`
placeholders. Rather than rewrite ~120 call sites across 16 modules, the
Postgres connection is wrapped so it translates those placeholders to
psycopg's `%s`/`%(name)s` on the way through - which is why nothing outside
this module had to change.
"""

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

IS_POSTGRES = bool(config.DATABASE_URL)

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
    status TEXT NOT NULL DEFAULT 'new',
    last_call_summary TEXT DEFAULT '',
    next_action_at TEXT,
    next_action TEXT DEFAULT 'call_borrower',
    -- Per-customer repayment terms. NULL means "use the policies row"
    -- (see server/agent/tools.py:effective_policy) - these only exist to
    -- override the default for a specific borrower.
    due_now_percent_override REAL,
    min_payment_today_percent_override REAL,
    cycle_days_override INTEGER
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


_PLACEHOLDER_RE = re.compile(r"'[^']*'|:([a-zA-Z_][a-zA-Z0-9_]*)|\?")


def _to_pg_params(sql: str) -> str:
    """SQLite `?` and `:name` -> psycopg `%s` and `%(name)s`.

    Quoted string literals are matched first and passed through untouched, so
    a `?` or `:foo` inside one is never mistaken for a placeholder. A literal
    `%` in the SQL has to be doubled for psycopg, which is done here too."""

    def swap(m: re.Match) -> str:
        text = m.group(0)
        if text.startswith("'"):
            return text
        return f"%({m.group(1)})s" if m.group(1) else "%s"

    return _PLACEHOLDER_RE.sub(swap, sql.replace("%", "%%"))


class _PgConn:
    """Gives a psycopg connection the small slice of the sqlite3 API this
    codebase actually uses: conn.execute(sql, params) returning something
    with .fetchone()/.fetchall(), plus commit/close."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=None):
        cur = self._conn.cursor()
        cur.execute(_to_pg_params(sql), params if params else None)
        return cur

    def executescript(self, sql: str):
        # psycopg runs a multi-statement string fine as long as nothing is
        # bound to it - which is exactly how SCHEMA is used.
        self._conn.execute(sql.replace("%", "%%"))
        return self

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def _connect_pg():
    import psycopg
    from psycopg.rows import dict_row

    return _PgConn(psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=False))


# `current_time` is a column on demo_clock and a reserved word in Postgres,
# so it has to be quoted there. Quoting works in SQLite too, but the bare
# name is what the existing SQLite-era SQL uses.
CURRENT_TIME = '"current_time"' if IS_POSTGRES else "current_time"


# SQLite's INSERT OR IGNORE / INSERT OR REPLACE are its own syntax, but both
# engines support the standard UPSERT form (SQLite since 3.24), so these emit
# one dialect-neutral clause rather than branching on the backend.


def _on_conflict_ignore(pk: str) -> str:
    return f" ON CONFLICT ({pk}) DO NOTHING"


def on_conflict_replace(pk: str, columns: list[str]) -> str:
    """Replacement for INSERT OR REPLACE, used by server/seed.py so
    re-seeding overwrites existing rows rather than erroring."""
    assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != pk)
    return f" ON CONFLICT ({pk}) DO UPDATE SET {assignments}"


def _migrate(conn):
    """CREATE TABLE IF NOT EXISTS silently does nothing to a table that
    already exists, so columns added later need backfilling explicitly.

    SQLite only: this exists to patch .db files created by older versions of
    this code. A Postgres database is always created fresh from SCHEMA, so
    there is nothing to backfill (and PRAGMA doesn't exist there anyway)."""
    if IS_POSTGRES:
        return
    existing = {r[1] for r in conn.execute("PRAGMA table_info(debts)")}
    if "account_ref" not in existing:
        conn.execute("ALTER TABLE debts ADD COLUMN account_ref TEXT")
    if "breach_date" in existing:
        # Never enforced by any code path - just a stale field. Dropped
        # rather than left nullable-and-unused.
        conn.execute("ALTER TABLE debts DROP COLUMN breach_date")
    if "salary_date" in existing:
        # Pre-filled before ever speaking to the borrower - a privacy
        # liability with no offsetting use (has_future_income_date in
        # offer_engine.generate_offer_options is accepted but never read).
        # The agent still learns and uses this live, in-call, via memory
        # (write_memory key=salary_date) - that mechanism is unaffected.
        conn.execute("ALTER TABLE debts DROP COLUMN salary_date")
    if "due_now_percent_override" not in existing:
        conn.execute("ALTER TABLE debts ADD COLUMN due_now_percent_override REAL")
    if "min_payment_today_percent_override" not in existing:
        conn.execute("ALTER TABLE debts ADD COLUMN min_payment_today_percent_override REAL")
    if "cycle_days_override" not in existing:
        conn.execute("ALTER TABLE debts ADD COLUMN cycle_days_override INTEGER")

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
    if IS_POSTGRES:
        conn = _connect_pg()
    else:
        Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.execute(
        f"INSERT INTO demo_clock (id, {CURRENT_TIME}, timezone, speed) VALUES (1, ?, ?, 'paused')"
        f"{_on_conflict_ignore('id')}",
        (config.DEMO_CLOCK_START, config.DEMO_CLOCK_TIMEZONE),
    )
    conn.execute(
        """INSERT INTO policies
        (id, max_discount_percent, due_now_percent, cycle_days, min_payment_today_percent, max_installments,
         call_attempts_per_day, allowed_call_hours_start, allowed_call_hours_end, human_review_triggers)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        + _on_conflict_ignore("id"),
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
    if IS_POSTGRES:
        conn = _connect_pg()
    else:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row):
    # Works for both backends: a sqlite3.Row converts, and psycopg's
    # dict_row already yields a dict (which dict() copies).
    return dict(row) if row is not None else None


def rows_to_dicts(conn, sql: str, *args) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]
