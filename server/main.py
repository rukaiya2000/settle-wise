from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .db import init_db
from .routes import browser_call, dashboard, demo_clock, payment, vapi, voice

app = FastAPI(title="SettleWise")

app.include_router(dashboard.router)
app.include_router(demo_clock.router)
app.include_router(payment.router)
app.include_router(voice.router)
app.include_router(browser_call.router)
app.include_router(vapi.router)
app.mount("/dashboard", StaticFiles(directory=config.BASE_DIR / "dashboard", html=True), name="dashboard")


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
