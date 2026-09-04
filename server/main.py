from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .auth import SessionAuthMiddleware, resolve_credentials
from .db import init_db
from .intelligence.schema import init_intel_db
from .routes import browser_call, dashboard, demo_clock, intelligence, login, payment, sms, vapi, voice

app = FastAPI(title="SettleWise")

_dashboard_user, _ = resolve_credentials()
app.add_middleware(SessionAuthMiddleware, username=_dashboard_user)

app.include_router(login.router)
app.include_router(dashboard.router)
app.include_router(intelligence.router)
app.include_router(demo_clock.router)
app.include_router(payment.router)
app.include_router(voice.router)
app.include_router(browser_call.router)
app.include_router(vapi.router)
app.include_router(sms.router)
app.mount("/dashboard", StaticFiles(directory=config.BASE_DIR / "dashboard", html=True), name="dashboard")


@app.on_event("startup")
def on_startup():
    init_db()
    init_intel_db()


@app.get("/health")
def health():
    return {"status": "ok"}
