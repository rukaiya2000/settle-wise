import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .auth import SessionAuthMiddleware, resolve_credentials
from .db import init_db
from .intelligence.schema import init_intel_db
from .routes import dashboard, demo_clock, intelligence, login, payment, sms, vapi

logger = logging.getLogger(__name__)

app = FastAPI(title="SettleWise")

_dashboard_user, _ = resolve_credentials()
app.add_middleware(SessionAuthMiddleware, username=_dashboard_user, public_demo=config.PUBLIC_DEMO)

app.include_router(login.router)


@app.get("/dashboard", include_in_schema=False)
def dashboard_no_slash():
    # StaticFiles serves index.html at /dashboard too, but the page's relative
    # asset paths then resolve against /, so it arrives with no CSS or JS.
    return RedirectResponse(url="/dashboard/", status_code=302)


@app.get("/", include_in_schema=False)
def root():
    # The bare domain used to fall through to a JSON 404; the product lives
    # under /dashboard/.
    return RedirectResponse(url="/dashboard/", status_code=302)

app.include_router(dashboard.router)
app.include_router(intelligence.router)
app.include_router(demo_clock.router)
app.include_router(payment.router)
app.include_router(vapi.router)
app.include_router(sms.router)

# The in-browser WebRTC call imports pipecat at module level, which the
# serverless deployment deliberately doesn't ship (see config.ENABLE_VOICE).
# Import it lazily so a missing pipecat is a skipped feature rather than a
# failed boot.
if config.ENABLE_VOICE != "false":
    try:
        from .routes import browser_call

        app.include_router(browser_call.router)
    except ImportError as e:
        if config.ENABLE_VOICE == "true":
            raise
        logger.info("Voice routes disabled (pipecat not installed): %s", e)

app.mount("/dashboard", StaticFiles(directory=config.BASE_DIR / "dashboard", html=True), name="dashboard")


@app.on_event("startup")
def on_startup():
    # On a serverless deployment the schema is created once by
    # scripts/migrate_to_postgres.py, not on every cold start.
    if config.SKIP_DB_INIT:
        return
    init_db()
    init_intel_db()


@app.get("/health")
def health():
    return {"status": "ok"}
