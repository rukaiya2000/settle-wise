"""Create the schema in Postgres and load the demo data.

Run once against a fresh Supabase database, before the first deploy:

    DATABASE_URL='postgresql://...pooler...:6543/postgres' \
        .venv/bin/python scripts/migrate_to_postgres.py

Both steps are idempotent - the schema uses CREATE TABLE IF NOT EXISTS and
the seed upserts - so re-running it refreshes the demo data without
dropping anything.

The intelligence tables (what the R pipeline computes) are NOT filled here;
run scripts/sync_intelligence.py for those.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config  # noqa: E402


def main():
    if not config.DATABASE_URL:
        raise SystemExit(
            "DATABASE_URL is not set - this script is for the Postgres deployment.\n"
            "Set it to the Supabase *transaction pooler* URL (port 6543)."
        )

    # Imported after the env check so the module-level IS_POSTGRES in
    # server.db is resolved with DATABASE_URL already present.
    from server.db import init_db
    from server.intelligence.schema import init_intel_db
    from server.seed import seed

    host = config.DATABASE_URL.split("@")[-1].split("/")[0]
    print(f"Target: {host}")

    print("Creating operational schema...")
    init_db()
    print("Creating intelligence schema...")
    init_intel_db()
    print("Loading seed data + synthetic live book...")
    seed()
    print("\nDone. Next: .venv/bin/python scripts/sync_intelligence.py")


if __name__ == "__main__":
    main()
