"""Admin endpoints: create clients (with an enrollment token), curate advisories,
trigger jobs.

Enrollment flow: create a client here and you get back a temporary enrollment
token. Put it in a probe's config; on first push the probe is issued its own
permanent token (see routers/ingest.py) and the enrollment token can expire.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Advisory, Client, EnrollmentToken, Site, User, utcnow
from ..security import generate_token, hash_token, slugify
from ..services.alerts import send_digest
from ..services.enrichment import rematch_site
from ..services.nvd import sync_once

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ClientIn(BaseModel):
    name: str
    ttl_hours: int | None = None  # enrollment token lifetime; defaults to config


class EnrollmentIn(BaseModel):
    label: str | None = None
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
            "note": "Put this in the probe config as `token`. It expires; the probe "
                    "swaps it for a permanent one on first push."}


@router.post("/clients", status_code=201)
def create_client(body: ClientIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    slug = slugify(body.name)
    if db.scalar(select(Client).where(Client.slug == slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Client already exists")
    client = Client(slug=slug, name=body.name)
    db.add(client)
    db.flush()
    enrollment = _mint_enrollment(db, client, label="initial", ttl_hours=body.ttl_hours)
    db.commit()
    return {"client": {"slug": client.slug, "name": client.name}, "enrollment": enrollment}


@router.post("/clients/{client_slug}/enrollment-tokens", status_code=201)
def create_enrollment(client_slug: str, body: EnrollmentIn,
                      _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = db.scalar(select(Client).where(Client.slug == client_slug))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown client")
    enrollment = _mint_enrollment(db, client, body.label, body.ttl_hours)
    db.commit()
    return enrollment


@router.get("/clients/{client_slug}/enrollment-tokens")
def list_enrollment(client_slug: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = db.scalar(select(Client).where(Client.slug == client_slug))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown client")
    rows = db.scalars(select(EnrollmentToken).where(EnrollmentToken.client_id == client.id))
    now = utcnow()
    return [
        {"id": r.id, "label": r.label, "expiresAt": r.expires_at, "revoked": r.revoked,
         "lastUsedAt": r.last_used_at, "valid": r.is_valid(now)}
        for r in rows
    ]


@router.post("/enrollment-tokens/{token_id}/revoke")
def revoke_enrollment(token_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(EnrollmentToken, token_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown enrollment token")
    row.revoked = True
    db.commit()
    return {"ok": True, "id": token_id, "revoked": True}


# ---- Advisory curation (the "curated" half of curated + NVD) ----
@router.get("/advisories")
def list_advisories(
    review_only: bool = False,
    _: User = Depends(get_current_user),
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
    _: User = Depends(get_current_user),
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
    db.commit()
    return {"ok": True, "id": adv.id, "rematched": changed_predicate}


# ---- Manual triggers (the daily jobs also run on a schedule) ----
@router.post("/sync-nvd")
def trigger_nvd_sync(_: User = Depends(get_current_user)):
    return sync_once()


@router.post("/send-digest")
def trigger_digest(_: User = Depends(get_current_user)):
    return send_digest()
