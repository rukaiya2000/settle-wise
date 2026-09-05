"""Per-client fixed-window rate limiting, counted in the database.

An in-memory counter would be per instance on a serverless deployment and
reset on every cold start; one upsert per write request holds across all of
them. Fails open: if the counter cannot be read the request proceeds and a
warning is logged - for a demo, availability beats a lockout caused by the
limiter itself.
"""

import time

from loguru import logger

from . import config
from .db import get_conn

# (bucket, limit, window seconds) chosen per request by classify().
LOGIN = ("login", lambda: config.RATE_LIMIT_LOGIN_PER_MIN, 60)
CLOCK = ("clock", lambda: config.RATE_LIMIT_CLOCK_PER_MIN, 60)
CREATE = ("create", lambda: config.RATE_LIMIT_CREATE_PER_HOUR, 3600)
WRITE = ("write", lambda: config.RATE_LIMIT_WRITES_PER_MIN, 60)


def client_ip(scope) -> str:
    headers = dict(scope.get("headers") or [])
    # Vercel (and any proxy) puts the real client first in X-Forwarded-For.
    fwd = headers.get(b"x-forwarded-for", b"").decode("latin-1").split(",")[0].strip()
    if fwd:
        return fwd
    client = scope.get("client")
    return client[0] if client else "unknown"


def classify(method: str, path: str):
    """Which bucket a request counts against; None for anything unlimited."""
    if method == "GET" or method == "HEAD" or method == "OPTIONS":
        return None
    if path == "/login":
        return LOGIN
    if path.startswith("/api/demo-clock/advance"):
        return CLOCK
    if path == "/api/debts":
        return CREATE
    return WRITE


def check(bucket, ip: str, now: float | None = None) -> tuple[bool, int]:
    """Count one request. Returns (allowed, seconds until the window resets)."""
    name, limit, window = bucket
    now = int(now if now is not None else time.time())
    window_start = now - (now % window)
    key = f"{name}:{ip}"
    try:
        with get_conn() as conn:
            row = conn.execute(
                "INSERT INTO rate_limits (key, window_start, count) VALUES (?, ?, 1) "
                "ON CONFLICT (key) DO UPDATE SET "
                "count = CASE WHEN rate_limits.window_start = excluded.window_start THEN rate_limits.count + 1 ELSE 1 END, "
                "window_start = excluded.window_start "
                "RETURNING count",
                (key, window_start),
            ).fetchone()
        count = row[0]
    except Exception as e:  # noqa: BLE001
        logger.warning("rate limiter unavailable, allowing request: {}", e)
        return True, 0
    return count <= limit(), window - (now - window_start)
