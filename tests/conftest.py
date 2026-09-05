"""The unit tests always run on a throwaway SQLite file, never on whatever
DATABASE_URL happens to point at in .env - which, on a machine set up to
deploy, is the real Supabase database."""

import os

os.environ["DATABASE_URL"] = ""
