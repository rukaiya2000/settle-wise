from fastapi import FastAPI

from .db import init_db
from .routes import dashboard, demo_clock, payment, voice

app = FastAPI(title="SettleWise")

app.include_router(dashboard.router)
app.include_router(demo_clock.router)
app.include_router(payment.router)
app.include_router(voice.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
