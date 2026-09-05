#!/usr/bin/env bash
# Push the deployment variables from .env into Vercel's production
# environment. Values are read from .env and piped straight into the CLI -
# nothing is echoed. Requires `npx vercel login` and `npx vercel link` first.
#
#   scripts/vercel_env.sh            # adds/updates the seven variables
set -euo pipefail
cd "$(dirname "$0")/.."
val() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
push() {  # name value
  [ -n "$2" ] || { echo "  $1: blank in .env - skipped"; return; }
  npx --yes vercel env rm "$1" production --yes >/dev/null 2>&1 || true
  printf '%s' "$2" | npx --yes vercel env add "$1" production >/dev/null && echo "  $1: set"
}
push DATABASE_URL       "$(val DATABASE_URL)"
push SESSION_SECRET     "$(val SESSION_SECRET)"
push DASHBOARD_USER     "$(val DASHBOARD_USER)"
push DASHBOARD_PASSWORD "$(val DASHBOARD_PASSWORD)"
push PUBLIC_DEMO        true
push SKIP_DB_INIT       true
push ENABLE_VOICE       false
push LIVE_SMS           false
