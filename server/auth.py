"""Gate on the dashboard/admin surface.

Nothing in server/main.py required authentication - every route was open,
including customer PII (name, phone, balance), delete-a-customer, and
POST /api/intelligence/rebuild (which spawns a subprocess and echoes its
full output back to the caller). That's a non-issue on localhost, but
PUBLIC_BASE_URL exists specifically so this service can sit behind an
ngrok tunnel for real inbound calls/SMS - at which point the admin surface
is reachable by anyone with the URL.

HTTP Basic over the whole app, fail-closed, with an explicit allowlist for
the handful of routes that must stay open because an external caller can't
do an interactive auth prompt: the a1mobile/Vapi webhooks, and the
borrower-facing mock checkout page reached from an SMS link. Basic Auth
specifically because the browser handles the challenge and credential
caching itself - no dashboard JS changes needed.
"""

import base64
import os
import secrets

from starlette.responses import Response

# Prefix-matched, not exact - each of these owns every path under it.
PUBLIC_PATH_PREFIXES = (
    "/health",
    "/voice",
    "/ws",
    "/api/vapi/tools",
    "/api/vapi/events",
    "/pay/",
    "/api/payments/",
)


def resolve_credentials() -> tuple[str, str]:
    """DASHBOARD_USER/DASHBOARD_PASSWORD from the environment, or a
    generated one-off password printed to the console - so a plain
    `make run` still works without prior setup, but auth is never
    silently disabled just because nobody configured it."""
    user = os.getenv("DASHBOARD_USER")
    password = os.getenv("DASHBOARD_PASSWORD")
    if user and password:
        return user, password

    user = user or "admin"
    password = password or secrets.token_urlsafe(18)
    print(
        "\n"
        "==================================================================\n"
        "  No DASHBOARD_USER/DASHBOARD_PASSWORD set - generated one for this\n"
        "  run only (won't survive a restart). Set both in .env to pin it.\n"
        f"  user:     {user}\n"
        f"  password: {password}\n"
        "==================================================================\n",
        flush=True,
    )
    return user, password


class BasicAuthMiddleware:
    """Raw ASGI middleware, not Starlette's BaseHTTPMiddleware - that
    class only handles the "http" scope and breaks the /ws websocket
    route by consuming its scope before the route ever sees it."""

    def __init__(self, app, username: str, password: str, public_prefixes: tuple[str, ...] = PUBLIC_PATH_PREFIXES):
        self.app = app
        self.username = username
        self.password = password
        self.public_prefixes = public_prefixes

    def _authorized(self, scope) -> bool:
        headers = dict(scope.get("headers") or [])
        raw = headers.get(b"authorization", b"").decode("latin-1")
        if not raw.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(raw[6:]).decode("utf-8")
        except Exception:
            return False
        user, _, password = decoded.partition(":")
        # Both comparisons run even when the first fails, so a wrong
        # username doesn't return faster than a wrong password would.
        return secrets.compare_digest(user, self.username) & secrets.compare_digest(password, self.password)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if any(path.startswith(p) for p in self.public_prefixes) or self._authorized(scope):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            # No HTTP status to return mid-handshake - refuse the upgrade.
            await send({"type": "websocket.close", "code": 4401})
            return

        response = Response(
            status_code=401,
            content="Authentication required.",
            headers={"WWW-Authenticate": 'Basic realm="SettleWise"'},
        )
        await response(scope, receive, send)
