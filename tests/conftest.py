"""The unit tests always run on a throwaway SQLite file, never on whatever
DATABASE_URL happens to point at in .env - which, on a machine set up to
deploy, is the real Supabase database - and never on the local demo file."""

import os
import tempfile

os.environ["DATABASE_URL"] = ""
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="settlewise-tests-"), "test.db")
os.environ.setdefault("ENABLE_VOICE", "false")
os.environ.setdefault("PUBLIC_DEMO", "true")
os.environ.setdefault("DASHBOARD_USER", "admin")
os.environ.setdefault("DASHBOARD_PASSWORD", "test-password")
os.environ.setdefault("SESSION_SECRET", "test-secret")
