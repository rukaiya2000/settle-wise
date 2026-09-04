"""Copy the R pipeline's output tables from local SQLite into Postgres.

The R layer (intelligence/) keeps writing to the local SQLite file - porting
it to RPostgres would mean a new renv dependency, a CI change, and
rewriting dbWriteTable(overwrite=TRUE) semantics, for no benefit while the
analysis only ever runs on a laptop. So the flow is:

    make intelligence                             # compute locally, as usual
    DATABASE_URL='postgresql://...' \
        .venv/bin/python scripts/sync_intelligence.py   # push the results

Each table is replaced wholesale, matching what write_table() does in
intelligence/R/00_setup.R, so the deployed copy is always a clean snapshot
of the latest local run rather than an accumulation.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config  # noqa: E402
from server.intelligence.schema import R_OUTPUT_TABLES  # noqa: E402

# The R-written analysis tables, plus the two input tables the Python side
# fills (the synthetic history and the extracted live events) - the deployed
# instance needs those too for /api/intelligence/portfolio.
TABLES = [*R_OUTPUT_TABLES, "intel_borrowers", "interaction_events"]


def main():
    if not config.DATABASE_URL:
        raise SystemExit("DATABASE_URL is not set - nothing to sync to.")

    sqlite_path = config.DB_PATH
    if not Path(sqlite_path).exists():
        raise SystemExit(f"No local SQLite database at {sqlite_path} - run `make intelligence` first.")

    import psycopg

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row

    with psycopg.connect(config.DATABASE_URL) as dst:
        for table in TABLES:
            try:
                rows = src.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.OperationalError:
                print(f"  {table:<30} skipped (not present locally)")
                continue
            if not rows:
                print(f"  {table:<30} empty, cleared")
                dst.execute(f"DELETE FROM {table}")
                continue

            columns = list(rows[0].keys())
            collist = ", ".join(f'"{c}"' for c in columns)
            placeholders = ", ".join(["%s"] * len(columns))

            dst.execute(f"DELETE FROM {table}")
            with dst.cursor() as cur:
                cur.executemany(
                    f'INSERT INTO {table} ({collist}) VALUES ({placeholders})',
                    [tuple(r[c] for c in columns) for r in rows],
                )
            print(f"  {table:<30} {len(rows)} rows")
        dst.commit()

    src.close()
    print("\nSync complete.")


if __name__ == "__main__":
    main()
