from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_agent
from ..models import Certificate, Collector, Component, License, Snapshot, naive_utc, utcnow
from ..schemas import IngestPayload, IngestResult
from ..services.enrichment import rematch_site

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest", response_model=IngestResult)
def ingest(
    payload: IngestPayload,
    collector: Collector = Depends(get_agent),
    db: Session = Depends(get_db),
) -> IngestResult:
    """Collection results from an enrolled agent (enrollment is /api/agent/enroll)."""
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
    if payload.diagnostics is not None:
        collector.last_run = {
            "at": utcnow().isoformat(),
            "checks": [d.model_dump() for d in payload.diagnostics],
        }

    db.commit()
    return IngestResult(
        snapshotId=snapshot.id,
        components=len(payload.components),
        certificates=len(payload.certificates),
        licenses=len(payload.licenses),
        findings=findings,
    )
