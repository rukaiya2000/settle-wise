"""Vercel entrypoint.

Vercel's Python runtime looks for an ASGI app in api/, so this just exposes
the same FastAPI app the local server runs. Everything that differs on the
deployment is driven by environment variables, not by a separate app object:

    DATABASE_URL   Supabase Postgres (use the transaction pooler, port 6543)
    SESSION_SECRET stable cookie signing key across cold starts
    PUBLIC_DEMO    true, so visitors don't need the password to look around
    SKIP_DB_INIT   true, schema is created by scripts/migrate_to_postgres.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.main import app  # noqa: E402

__all__ = ["app"]
