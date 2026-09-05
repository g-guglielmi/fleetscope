import logging
import os
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config as AlembicConfig
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from . import models  # noqa: F401  (register models on Base)
from .config import settings
from .db import SessionLocal
from .routers import admin, agent, auth, clients, credentials, ingest, overview, siteconfig, users
from .seed import run as run_seed
from .services import crypto
from .services.alerts import send_digest
from .services.manifest import CHECKS_DIR, is_signed, load_manifest
from .services.nvd import sync_once

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fleetscope")

# Honor the standard Docker TZ variable (e.g. Europe/Rome) so the daily NVD sync
# and email digest fire at the configured local hour. APScheduler resolves the
# name via pytz. Falls back to UTC.
scheduler = BackgroundScheduler(timezone=os.environ.get("TZ", "UTC"))

# backend/ dir (holds alembic.ini + migrations/); /app in the container.
_BASE_DIR = os.path.dirname(os.path.dirname(__file__))


def _run_migrations() -> None:
    """Bring the database schema up to head. Idempotent — a no-op when current."""
    cfg = AlembicConfig(os.path.join(_BASE_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BASE_DIR, "migrations"))
    command.upgrade(cfg, "head")


def _production_checks() -> None:
    """Refuse to run with default or missing secrets (docs/AGENT.md §6.5).
    FS_DEV_MODE=true relaxes everything except a malformed FS_SECRETS_KEY."""
    problems: list[str] = []

    key_error = crypto.validate_key()
    if key_error:
        problems.append(key_error)

    with SessionLocal() as db:
        users = db.scalar(select(func.count(models.User.id))) or 0
        creds = db.scalar(select(func.count(models.Credential.id))) or 0

    if not settings.dev_mode:
        if settings.jwt_secret == "change-me-in-production":
            problems.append("FS_JWT_SECRET is at its default value")
        elif len(settings.jwt_secret) < 32:
            problems.append("FS_JWT_SECRET must be at least 32 characters (HMAC-SHA256 key)")
        if users == 0 and settings.admin_password in ("", "changeme"):
            problems.append("FS_ADMIN_PASSWORD is unset/default and no users exist yet")
        if creds > 0 and not crypto.secrets_enabled():
            problems.append("credentials exist in the database but FS_SECRETS_KEY is not set")

    if problems:
        for p in problems:
            log.error("STARTUP REFUSED: %s", p)
        log.error("Fix deploy.env (see deploy/deploy.env.example) or set FS_DEV_MODE=true for local development only.")
        raise SystemExit(1)

    if settings.dev_mode:
        log.warning("FS_DEV_MODE is on — production safety checks are relaxed")
    if not crypto.secrets_enabled():
        log.warning("FS_SECRETS_KEY not set — credential storage is disabled")
    if not settings.signing_pubkey:
        log.warning("FS_SIGNING_PUBKEY not set — install commands will carry a placeholder")
    if not settings.public_url:
        log.warning("FS_PUBLIC_URL not set — install commands will carry a placeholder")
    manifest = load_manifest()
    log.info("check manifest: %d checks from %s (%s)", len(manifest.get("checks", [])), CHECKS_DIR,
             "signed" if is_signed(manifest) else "UNSIGNED — agents will refuse it")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_migrations()
    _production_checks()
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


app = FastAPI(title="FleetScope", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(agent.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(credentials.router)
app.include_router(siteconfig.router)
app.include_router(overview.router)
app.include_router(clients.router)
app.include_router(admin.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# ---- Serve the built React SPA from this same container (single-image deploy) ----
# In the Docker image the frontend build is copied to app/static. In local dev
# this directory is absent, so the API runs standalone and Vite serves the UI.
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # API routes are matched earlier; anything else falls back to the SPA.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = os.path.join(STATIC_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
