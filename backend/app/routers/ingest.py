from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..deps import get_collector
from ..db import get_db
from ..models import Certificate, Collector, Component, License, Site, Snapshot, utcnow
from ..schemas import IngestPayload, IngestResult
from ..services.enrichment import rematch_site

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest", response_model=IngestResult)
def ingest(
    payload: IngestPayload,
    collector: Collector = Depends(get_collector),
    db: Session = Depends(get_db),
) -> IngestResult:
    site = db.get(Site, collector.site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collector's site no longer exists")

    # If the body names a scope, it must match the token's scope.
    if payload.site and payload.site != site.slug:
        raise HTTPException(status.HTTP_409_CONFLICT, "Body 'site' does not match token scope")
    if payload.client and site.client and payload.client != site.client.slug:
        raise HTTPException(status.HTTP_409_CONFLICT, "Body 'client' does not match token scope")

    # Store the raw snapshot (history).
    snapshot = Snapshot(
        site_id=site.id,
        collector_id=collector.id,
        collected_at=payload.collectedAt,
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
            subject=cert.subject, issuer=cert.issuer, not_after=cert.notAfter,
            thumbprint=cert.thumbprint,
        ))
    for lic in payload.licenses:
        db.add(License(
            site_id=site.id, product=lic.product, edition=lic.edition, model=lic.model,
            count=lic.count, subscription_advantage_date=lic.subscriptionAdvantageDate,
            expires=lic.expires,
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
