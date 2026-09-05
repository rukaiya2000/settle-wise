"""Vercel entrypoint.

Vercel's Python runtime looks for an ASGI app in api/, so this just exposes
the same FastAPI app the local server runs. Everything that differs on the
deployment is driven by environment variables, not by a separate app object:

    DATABASE_URL   Supabase Postgres (use the transaction pooler, port 6543)
    SESSION_SECRET stable cookie signing key across cold starts
    PUBLIC_DEMO    true, so visitors don't need the password to look around
    SKIP_DB_INIT   true, schema is created by scripts/migrate_to_postgres.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# No SQLite fallback on the deployment. Locally the app runs on a SQLite
# file when DATABASE_URL is unset (tests and the R pipeline depend on that);
# on Vercel that same fallback would mean a fresh, empty, read-only file per
# cold start that looks like a working site. Fail at import instead.
if not os.getenv("DATABASE_URL"):
    raise RuntimeError(
        "DATABASE_URL is not set. The deployment runs on Postgres only - "
        "there is no SQLite fallback here. Set it in the Vercel project's environment."
    )

from server.main import app  # noqa: E402

__all__ = ["app"]
