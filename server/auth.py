"""Gate on the dashboard/admin surface.

Nothing in server/main.py required authentication - every route was open,
including customer PII (name, phone, balance), delete-a-customer, and
POST /api/intelligence/rebuild (which spawns a subprocess and echoes its
full output back to the caller). That's a non-issue on localhost, but
PUBLIC_BASE_URL exists specifically so this service can sit behind an
ngrok tunnel for real inbound calls/SMS - at which point the admin surface
is reachable by anyone with the URL.

A signed session cookie, set by the login page in server/routes/login.py,
gates everything else. This used to be HTTP Basic, which is simpler to
implement but forces the browser's own unstyled native credential prompt -
jarring, and impossible to theme or improve. A normal in-app login page
that redirects here on an unauthenticated request is the same protection
with none of that.
"""

import base64
import hashlib
import hmac
import os
import secrets
import time

from starlette.responses import RedirectResponse, Response

from . import ratelimit

# Prefix-matched, not exact - each of these owns every path under it.
PUBLIC_PATH_PREFIXES = (
    "/health",
    "/voice",
    "/ws",
    "/api/vapi/tools",
    "/api/vapi/events",
    "/pay/",
    "/api/payments/",
    "/login",
)

# Routes that stay behind the login even when PUBLIC_DEMO is on, because they
# either destroy the demo or cost real money / contact real people. Matched on
# (method, path fragment) since the read and the write of a debt share a URL.
PROTECTED_ALWAYS = (
    "/api/reset-demo",
    "/delete",
    "/api/debts/bulk-delete",
    "/api/intelligence/rebuild",
    "/sms",
    "/call",  # covers /call and /call-agent - real outbound telephony
)


def _is_protected(path: str) -> bool:
    return any(frag in path for frag in PROTECTED_ALWAYS)

SESSION_COOKIE = "settlewise_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days

_credentials: tuple[str, str] | None = None
_session_secret: str | None = None


def resolve_credentials() -> tuple[str, str]:
    """DASHBOARD_USER/DASHBOARD_PASSWORD from the environment, or a
    generated one-off password printed to the console - so a plain
    `make run` still works without prior setup, but auth is never
    silently disabled just because nobody configured it.

    Cached after the first call: this is read both at startup (to print
    the generated password) and from the login route on every submit, and
    a *second* random password would never match the one already printed."""
    global _credentials
    if _credentials is not None:
        return _credentials

    user = os.getenv("DASHBOARD_USER")
    password = os.getenv("DASHBOARD_PASSWORD")
    if not (user and password):
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
    _credentials = (user, password)
    return _credentials


def session_secret() -> str:
    """Key for signing session cookies.

    SESSION_SECRET from the environment when set - required on any
    deployment that can run more than one process: a per-process random key
    means every cold start invalidates all sessions, and two instances
    reject each other's cookies outright. Falls back to a generated value
    for local runs, where a single process makes that moot."""
    global _session_secret
    if _session_secret is None:
        _session_secret = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
    return _session_secret


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session_token(username: str) -> str:
    expiry = int(time.time()) + SESSION_MAX_AGE
    payload = f"{username}|{expiry}"
    signed = f"{payload}|{_sign(payload, session_secret())}"
    return base64.urlsafe_b64encode(signed.encode()).decode()


def verify_session_token(token: str, expected_username: str) -> bool:
    try:
        username, expiry, sig = base64.urlsafe_b64decode(token.encode()).decode().split("|", 2)
    except Exception:
        return False
    if not secrets.compare_digest(sig, _sign(f"{username}|{expiry}", session_secret())):
        return False
    if not secrets.compare_digest(username, expected_username):
        return False
    try:
        return int(expiry) >= time.time()
    except ValueError:
        return False


class SessionAuthMiddleware:
    """Raw ASGI middleware, not Starlette's BaseHTTPMiddleware - that
    class only handles the "http" scope and breaks the /ws websocket
    route by consuming its scope before the route ever sees it.

    An unauthenticated page load is redirected to /login (a normal page
    navigation); an unauthenticated /api/* call gets a plain 401 so the
    dashboard's own fetch() wrapper can send the browser there itself."""

    def __init__(self, app, username: str, public_prefixes: tuple[str, ...] = PUBLIC_PATH_PREFIXES, public_demo: bool = False):
        self.app = app
        self.username = username
        self.public_prefixes = public_prefixes
        # PUBLIC_DEMO opens browsing and the harmless writes (add a customer,
        # advance the clock, run the simulated agent) to anyone with the link,
        # so a shared demo is actually usable without handing out a password.
        # PROTECTED_ALWAYS still applies - nobody anonymous can wipe the demo
        # or trigger real telephony.
        self.public_demo = public_demo

    def _authorized(self, scope) -> bool:
        headers = dict(scope.get("headers") or [])
        cookie_header = headers.get(b"cookie", b"").decode("latin-1")
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE:
                return verify_session_token(value, self.username)
        return False

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if scope["type"] == "http":
            bucket = ratelimit.classify(scope.get("method", "GET"), path)
            if bucket is not None:
                allowed, retry_after = ratelimit.check(bucket, ratelimit.client_ip(scope))
                if not allowed:
                    response = Response(
                        status_code=429,
                        content='{"error":"too many requests, slow down"}',
                        media_type="application/json",
                        headers={"Retry-After": str(retry_after)},
                    )
                    await response(scope, receive, send)
                    return
        open_to_anyone = any(path.startswith(p) for p in self.public_prefixes) or (
            self.public_demo and not _is_protected(path)
        )
        if open_to_anyone or self._authorized(scope):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            # No HTTP status to return mid-handshake - refuse the upgrade.
            await send({"type": "websocket.close", "code": 4401})
            return

        if path.startswith("/api/"):
            response = Response(status_code=401, content='{"error":"authentication required"}', media_type="application/json")
        else:
            response = RedirectResponse(url=f"/login?next={path}", status_code=302)
        await response(scope, receive, send)
