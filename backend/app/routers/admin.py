"""Admin endpoints: clients + enrollment tokens, the agent install command,
advisory curation, manual job triggers. All require the admin role.

Enrollment flow: create a client here and you get back a temporary enrollment
token. The generated install command embeds one; on `install` the agent enrolls
(routers/agent.py) and is issued its own permanent token.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import client_ip, require_admin
from ..models import Advisory, Client, EnrollmentToken, Site, User, utcnow
from ..security import generate_token, hash_token, slugify
from ..services.alerts import send_digest
from ..services.audit import audit
from ..services.enrichment import rematch_site
from ..services.nvd import sync_once

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ClientIn(BaseModel):
    name: str
    ttl_hours: int | None = None  # enrollment token lifetime; defaults to config


class EnrollmentIn(BaseModel):
    label: str | None = None
    ttl_hours: int | None = None


class InstallCommandIn(BaseModel):
    site: str | None = None       # site display name to embed; placeholder if omitted
    ttl_hours: int | None = None


class AdvisoryPatch(BaseModel):
    affected_below_build: str | None = None
    fixed_build: str | None = None
    severity: str | None = None
    product_type: str | None = None
    needs_review: bool | None = None
    notes: str | None = None


def _mint_enrollment(db: Session, client: Client, label: str | None, ttl_hours: int | None) -> dict:
    ttl = ttl_hours or settings.enrollment_ttl_hours
    token = generate_token()
    row = EnrollmentToken(
        client_id=client.id,
        token_hash=hash_token(token),
        label=label,
        expires_at=utcnow() + timedelta(hours=ttl),
    )
    db.add(row)
    db.flush()
    # The plaintext token is returned exactly once.
    return {"id": row.id, "token": token, "expiresAt": row.expires_at, "label": label,
            "note": "Use this in the agent install command. It expires; the agent "
                    "swaps it for a permanent token on enrollment."}


def _client(db: Session, slug: str) -> Client:
    client = db.scalar(select(Client).where(Client.slug == slug))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown client")
    return client


# ---- Clients ----
@router.post("/clients", status_code=201)
def create_client(body: ClientIn, request: Request, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    slug = slugify(body.name)
    if db.scalar(select(Client).where(Client.slug == slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Client already exists")
    client = Client(slug=slug, name=body.name)
    db.add(client)
    db.flush()
    enrollment = _mint_enrollment(db, client, label="initial", ttl_hours=body.ttl_hours)
    audit(db, me.email, "client.create", "client", client.slug, {"name": body.name}, client_ip(request))
    db.commit()
    return {"client": {"slug": client.slug, "name": client.name}, "enrollment": enrollment}


@router.delete("/clients/{client_slug}", status_code=204)
def delete_client(client_slug: str, request: Request, me: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    client = _client(db, client_slug)
    audit(db, me.email, "client.delete", "client", client.slug, {"name": client.name, "sites": len(client.sites)}, client_ip(request))
    db.delete(client)  # cascades: sites, configs, collectors, snapshots, credentials, tokens
    db.commit()


@router.post("/clients/{client_slug}/install-command")
def install_command(client_slug: str, body: InstallCommandIn, request: Request,
                    me: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Mint a fresh enrollment token and render the one-line agent install
    (docs/AGENT.md §8)."""
    client = _client(db, client_slug)
    enrollment = _mint_enrollment(db, client, label=f"install:{body.site or '-'}", ttl_hours=body.ttl_hours)
    audit(db, me.email, "enrollment.mint", "client", client.slug, {"site": body.site, "purpose": "install-command"}, client_ip(request))
    db.commit()

    warnings: list[str] = []
    url = settings.public_url.rstrip("/") or "https://<dashboard-url>"
    if not settings.public_url:
        warnings.append("FS_PUBLIC_URL is not set; replace <dashboard-url> in the command.")
    key = settings.signing_pubkey or "<signing-public-key>"
    if not settings.signing_pubkey:
        warnings.append("FS_SIGNING_PUBKEY is not set; the agent cannot verify check modules until it is.")
    site = body.site or "<site name>"
    command = (
        f'iwr {url}/api/agent/release/download -OutFile FleetScopeAgent.exe\n'
        f'.\\FleetScopeAgent.exe install --url {url} --token {enrollment["token"]} '
        f'--site "{site}" --signing-key {key}'
    )
    return {"command": command, "enrollment": enrollment, "warnings": warnings}


# ---- Enrollment tokens ----
@router.post("/clients/{client_slug}/enrollment-tokens", status_code=201)
def create_enrollment(client_slug: str, body: EnrollmentIn, request: Request,
                      me: User = Depends(require_admin), db: Session = Depends(get_db)):
    client = _client(db, client_slug)
    enrollment = _mint_enrollment(db, client, body.label, body.ttl_hours)
    audit(db, me.email, "enrollment.mint", "client", client.slug, {"label": body.label}, client_ip(request))
    db.commit()
    return enrollment


@router.get("/clients/{client_slug}/enrollment-tokens")
def list_enrollment(client_slug: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    client = _client(db, client_slug)
    rows = db.scalars(select(EnrollmentToken).where(EnrollmentToken.client_id == client.id))
    now = utcnow()
    return [
        {"id": r.id, "label": r.label, "expiresAt": r.expires_at, "revoked": r.revoked,
         "lastUsedAt": r.last_used_at, "valid": r.is_valid(now)}
        for r in rows
    ]


@router.post("/enrollment-tokens/{token_id}/revoke")
def revoke_enrollment(token_id: int, request: Request, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(EnrollmentToken, token_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown enrollment token")
    row.revoked = True
    audit(db, me.email, "enrollment.revoke", "enrollment_token", token_id, None, client_ip(request))
    db.commit()
    return {"ok": True, "id": token_id, "revoked": True}


# ---- Advisory curation (the "curated" half of curated + NVD) ----
@router.get("/advisories")
def list_advisories(
    review_only: bool = False,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(Advisory).order_by(Advisory.needs_review.desc(), Advisory.severity)
    if review_only:
        stmt = stmt.where(Advisory.needs_review.is_(True))
    return [
        {
            "id": a.id, "productType": a.product_type, "title": a.title, "cve": a.cve,
            "severity": a.severity, "cvss": a.cvss, "affectedBelowBuild": a.affected_below_build,
            "fixedBuild": a.fixed_build, "url": a.url, "source": a.source,
            "needsReview": a.needs_review, "published": a.published,
        }
        for a in db.scalars(stmt)
    ]


@router.patch("/advisories/{advisory_id}")
def curate_advisory(
    advisory_id: int,
    patch: AdvisoryPatch,
    request: Request,
    me: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Add a build predicate to an advisory so it starts matching components.

    Editing `affected_below_build` re-runs matching across all sites."""
    adv = db.get(Advisory, advisory_id)
    if adv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown advisory")

    fields = patch.model_dump(exclude_unset=True)
    changed_predicate = "affected_below_build" in fields
    for key, value in fields.items():
        setattr(adv, key, value)
    db.flush()

    if changed_predicate:
        for site in db.scalars(select(Site)):
            rematch_site(db, site.id)
    audit(db, me.email, "advisory.curate", "advisory", adv.id, fields, client_ip(request))
    db.commit()
    return {"ok": True, "id": adv.id, "rematched": changed_predicate}


# ---- Manual triggers (the daily jobs also run on a schedule) ----
@router.post("/sync-nvd")
def trigger_nvd_sync(_: User = Depends(require_admin)):
    return sync_once()


@router.post("/send-digest")
def trigger_digest(_: User = Depends(require_admin)):
    return send_digest()


# ---- Audit log ----
@router.get("/audit")
def list_audit(limit: int = 200, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    from ..models import AuditLog
    limit = max(1, min(limit, 1000))
    return [
        {"id": a.id, "at": a.at, "actor": a.actor, "action": a.action, "targetType": a.target_type,
         "targetId": a.target_id, "detail": a.detail, "ip": a.ip}
        for a in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    ]
