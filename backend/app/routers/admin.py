"""Admin/enrollment endpoints: create clients, sites, and collectors.

Creating a collector returns its token **once** — it is stored only as a hash,
so it cannot be retrieved again. Copy it into the collector's config immediately.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Advisory, Client, Collector, Site, User
from ..security import generate_collector_token, hash_token
from ..services.alerts import send_digest
from ..services.enrichment import rematch_site
from ..services.nvd import sync_once

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ClientIn(BaseModel):
    slug: str
    name: str


class SiteIn(BaseModel):
    slug: str
    name: str


class CollectorIn(BaseModel):
    name: str


class AdvisoryPatch(BaseModel):
    affected_below_build: str | None = None
    fixed_build: str | None = None
    severity: str | None = None
    product_type: str | None = None
    needs_review: bool | None = None
    notes: str | None = None


@router.post("/clients", status_code=201)
def create_client(body: ClientIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(Client).where(Client.slug == body.slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Client slug already exists")
    client = Client(slug=body.slug, name=body.name)
    db.add(client)
    db.commit()
    return {"slug": client.slug, "name": client.name}


@router.post("/clients/{client_slug}/sites", status_code=201)
def create_site(client_slug: str, body: SiteIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = db.scalar(select(Client).where(Client.slug == client_slug))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown client")
    site = Site(client_id=client.id, slug=body.slug, name=body.name)
    db.add(site)
    db.commit()
    return {"client": client_slug, "slug": site.slug, "name": site.name}


@router.post("/clients/{client_slug}/sites/{site_slug}/collectors", status_code=201)
def create_collector(
    client_slug: str,
    site_slug: str,
    body: CollectorIn,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    site = db.scalar(
        select(Site).join(Client).where(Client.slug == client_slug, Site.slug == site_slug)
    )
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown client/site")

    token = generate_collector_token()
    collector = Collector(site_id=site.id, name=body.name, token_hash=hash_token(token))
    db.add(collector)
    db.commit()
    # The plaintext token is returned exactly once.
    return {
        "collector": body.name,
        "client": client_slug,
        "site": site_slug,
        "token": token,
        "note": "Store this token now; it is not recoverable.",
    }


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
