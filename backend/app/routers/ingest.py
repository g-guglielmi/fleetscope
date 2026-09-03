from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..deps import bearer_token
from ..db import get_db
from ..models import (
    Certificate,
    Client,
    Collector,
    Component,
    EnrollmentToken,
    License,
    Site,
    Snapshot,
    naive_utc,
    utcnow,
)
from ..schemas import IngestPayload, IngestResult
from ..security import generate_token, hash_token, slugify
from ..services.enrichment import rematch_site

router = APIRouter(prefix="/api", tags=["ingest"])


def _get_or_create_site(db: Session, client: Client, name: str) -> Site:
    slug = slugify(name)
    site = db.scalar(select(Site).where(Site.client_id == client.id, Site.slug == slug))
    if site is None:
        site = Site(client_id=client.id, slug=slug, name=name)
        db.add(site)
        db.flush()
    return site


def _authenticate(db: Session, token: str, payload: IngestPayload) -> tuple[Collector, str | None]:
    """Resolve the pushing probe.

    - A known per-probe token -> that collector (scoped to its site).
    - Otherwise a valid enrollment token -> create the site+collector under the
      token's client, mint a permanent probe token, and return it once.
    """
    token_hash = hash_token(token)

    collector = db.scalar(select(Collector).where(Collector.token_hash == token_hash))
    if collector is not None:
        return collector, None

    enrollment = db.scalar(select(EnrollmentToken).where(EnrollmentToken.token_hash == token_hash))
    if enrollment is None or not enrollment.is_valid(utcnow()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    client = db.get(Client, enrollment.client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enrollment token's client no longer exists")

    site = _get_or_create_site(db, client, payload.site)
    probe_name = payload.probe or f"{site.slug}-collector"

    collector = db.scalar(select(Collector).where(Collector.site_id == site.id, Collector.name == probe_name))
    if collector is None:
        collector = Collector(site_id=site.id, name=probe_name)
        db.add(collector)

    new_token = generate_token()
    collector.token_hash = hash_token(new_token)
    enrollment.last_used_at = utcnow()
    db.flush()
    return collector, new_token


@router.post("/ingest", response_model=IngestResult)
def ingest(
    payload: IngestPayload,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> IngestResult:
    collector, new_token = _authenticate(db, bearer_token(authorization), payload)
    site_id = collector.site_id

    snapshot = Snapshot(
        site_id=site_id,
        collector_id=collector.id,
        collected_at=naive_utc(payload.collectedAt),
        raw=payload.model_dump(mode="json"),
    )
    db.add(snapshot)

    # Replace derived state for this site (latest-wins).
    db.execute(delete(Component).where(Component.site_id == site_id))
    db.execute(delete(Certificate).where(Certificate.site_id == site_id))
    db.execute(delete(License).where(License.site_id == site_id))

    for c in payload.components:
        db.add(Component(
            site_id=site_id, type=c.type, hostname=c.hostname, product=c.product,
            version=c.version, build=c.build, os_version=c.osVersion, extra=c.extra,
        ))
    for cert in payload.certificates:
        db.add(Certificate(
            site_id=site_id, source=cert.source, hostname=cert.hostname,
            subject=cert.subject, issuer=cert.issuer, not_after=naive_utc(cert.notAfter),
            thumbprint=cert.thumbprint,
        ))
    for lic in payload.licenses:
        db.add(License(
            site_id=site_id, product=lic.product, edition=lic.edition, model=lic.model,
            count=lic.count, subscription_advantage_date=naive_utc(lic.subscriptionAdvantageDate),
            expires=naive_utc(lic.expires),
        ))

    db.flush()  # assign component ids before matching
    findings = rematch_site(db, site_id)

    collector.last_seen = utcnow()
    collector.last_collector_version = payload.collectorVersion

    db.commit()
    return IngestResult(
        snapshotId=snapshot.id,
        components=len(payload.components),
        certificates=len(payload.certificates),
        licenses=len(payload.licenses),
        findings=findings,
        collectorToken=new_token,
        enrolled=new_token is not None,
    )
