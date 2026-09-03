import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (register models on Base)
from .config import settings
from .db import Base, SessionLocal, engine
from .routers import admin, auth, clients, ingest, overview
from .seed import run as run_seed
from .services.alerts import send_digest
from .services.nvd import sync_once

logging.basicConfig(level=logging.INFO)
scheduler = BackgroundScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # v1 scaffold: create tables directly. Swap for Alembic migrations before prod.
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        run_seed(db)

    # Daily jobs: NVD sync (review candidates) and the email digest.
    if settings.nvd_sync_enabled:
        scheduler.add_job(sync_once, CronTrigger(hour=settings.nvd_sync_hour), id="nvd_sync")
    scheduler.add_job(send_digest, CronTrigger(hour=settings.alert_hour), id="digest")
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="FleetScope", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(auth.router)
app.include_router(overview.router)
app.include_router(clients.router)
app.include_router(admin.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
