"""Per-site agent configuration and actions (docs/AGENT.md §6.2–6.4)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, get_current_user, require_admin
from ..models import Client, Collector, Credential, Site, User
from ..services.audit import audit
from ..services.manifest import is_signed, load_manifest
from ..services.siteconfig import config_dict, get_or_create_config, referenced_credentials, validate_config

router = APIRouter(prefix="/api/sites", tags=["site-config"])

ACTIONS = {"run-now", "restart"}


def _site(db: Session, client_slug: str, site_slug: str) -> tuple[Client, Site]:
    client = db.scalar(select(Client).where(Client.slug == client_slug))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown client")
    site = db.scalar(select(Site).where(Site.client_id == client.id, Site.slug == site_slug))
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown site")
    return client, site


def _credential_summaries(db: Session, client: Client) -> list[dict]:
    return [
        {"name": c.name, "kind": c.kind, "username": c.username, "version": c.version}
        for c in db.scalars(select(Credential).where(Credential.client_id == client.id).order_by(Credential.name))
    ]


@router.get("/{client_slug}/{site_slug}/config")
def get_config(client_slug: str, site_slug: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    client, site = _site(db, client_slug, site_slug)
    manifest = load_manifest()
    config = config_dict(site.config)
    creds = _credential_summaries(db, client)
    known = {c["name"] for c in creds}
    return {
        "client": {"slug": client.slug, "name": client.name},
        "site": {"slug": site.slug, "name": site.name},
        "config": config,
        "checks": [
            {k: v for k, v in c.items() if k in ("name", "version", "description", "requires", "settingsSchema", "timeoutSeconds")}
            for c in manifest.get("checks", [])
        ],
        "manifestSigned": is_signed(manifest),
        "credentials": creds,
        "missingCredentials": sorted(referenced_credentials(config) - known),
    }


@router.put("/{client_slug}/{site_slug}/config")
def put_config(client_slug: str, site_slug: str, body: dict, request: Request,
               me: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    client, site = _site(db, client_slug, site_slug)
    clean = validate_config(db, client, body)
    cfg = get_or_create_config(db, site)
    cfg.checks = clean["checks"]
    cfg.interval_minutes = clean["intervalMinutes"]
    cfg.auto_update = clean["autoUpdate"]
    cfg.agent = clean["agent"]
    cfg.prerequisites = clean["prerequisites"]
    cfg.updated_by = me.email
    audit(db, me.email, "siteconfig.update", "site", f"{client.slug}/{site.slug}",
          {"checks": {k: v["enabled"] for k, v in clean["checks"].items()},
           "serviceAccount": clean["agent"].get("serviceAccount")}, client_ip(request))
    db.commit()
    return {"ok": True, "config": config_dict(cfg)}


@router.post("/{client_slug}/{site_slug}/actions/{action}")
def queue_action(client_slug: str, site_slug: str, action: str, request: Request,
                 me: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    if action not in ACTIONS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown action; valid: {sorted(ACTIONS)}")
    client, site = _site(db, client_slug, site_slug)
    queued = 0
    for col in db.scalars(select(Collector).where(Collector.site_id == site.id)):
        actions = list(col.pending_actions or [])
        if action not in actions:
            actions.append(action)
            col.pending_actions = actions
            queued += 1
    audit(db, me.email, f"agent.action.{action}", "site", f"{client.slug}/{site.slug}", {"queued": queued}, client_ip(request))
    db.commit()
    return {"ok": True, "action": action, "queued": queued}
