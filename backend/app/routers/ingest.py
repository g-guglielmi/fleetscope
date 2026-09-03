from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import verify_ingest_key
from ..models import (
    Certificate,
    Client,
    Collector,
    Component,
    License,
    Site,
    Snapshot,
    naive_utc,
    utcnow,
)
from ..schemas import IngestPayload, IngestResult
from ..security import slugify
from ..services.enrichment import rematch_site

router = APIRouter(prefix="/api", tags=["ingest"])


def _get_or_create_client(db: Session, name: str) -> Client:
    slug = slugify(name)
    client = db.scalar(select(Client).where(Client.slug == slug))
    if client is None:
        client = Client(slug=slug, name=name)
        db.add(client)
        db.flush()
    return client


def _get_or_create_site(db: Session, client: Client, name: str) -> Site:
    slug = slugify(name)
    site = db.scalar(select(Site).where(Site.client_id == client.id, Site.slug == slug))
    if site is None:
        site = Site(client_id=client.id, slug=slug, name=name)
        db.add(site)
        db.flush()
    return site


def _get_or_create_collector(db: Session, site: Site, name: str) -> Collector:
    collector = db.scalar(select(Collector).where(Collector.site_id == site.id, Collector.name == name))
    if collector is None:
        collector = Collector(site_id=site.id, name=name)
        db.add(collector)
        db.flush()
    return collector


@router.post("/ingest", response_model=IngestResult, dependencies=[Depends(verify_ingest_key)])
def ingest(payload: IngestPayload, db: Session = Depends(get_db)) -> IngestResult:
    # Self-registration: the probe declares its client/site; we auto-provision so
    # the Overview grows a new section automatically. No pre-enrollment needed.
    client = _get_or_create_client(db, payload.client)
    site = _get_or_create_site(db, client, payload.site)
    collector = _get_or_create_collector(db, site, payload.probe or f"{site.slug}-collector")

    snapshot = Snapshot(
        site_id=site.id,
        collector_id=collector.id,
        collected_at=naive_utc(payload.collectedAt),
        raw=payload.model_dump(mode="json"),
    )
    db.add(snapshot)

    # Replace derived state for this site (latest-wins).
    db.execute(delete(Component).where(Component.site_id == site.id))
    db.execute(delete(Certificate).where(Certificate.site_id == site.id))
    db.execute(delete(License).where(License.site_id == site.id))

    for c in payload.components:
        db.add(Component(
            site_id=site.id, type=c.type, hostname=c.hostname, product=c.product,
            version=c.version, build=c.build, os_version=c.osVersion, extra=c.extra,
        ))
    for cert in payload.certificates:
        db.add(Certificate(
            site_id=site.id, source=cert.source, hostname=cert.hostname,
            subject=cert.subject, issuer=cert.issuer, not_after=naive_utc(cert.notAfter),
            thumbprint=cert.thumbprint,
        ))
    for lic in payload.licenses:
        db.add(License(
            site_id=site.id, product=lic.product, edition=lic.edition, model=lic.model,
            count=lic.count, subscription_advantage_date=naive_utc(lic.subscriptionAdvantageDate),
            expires=naive_utc(lic.expires),
        ))

    db.flush()  # assign component ids before matching
    findings = rematch_site(db, site.id)

    collector.last_seen = utcnow()
    collector.last_collector_version = payload.collectorVersion

    db.commit()
    return IngestResult(
        snapshotId=snapshot.id,
        components=len(payload.components),
        certificates=len(payload.certificates),
        licenses=len(payload.licenses),
        findings=findings,
    )
