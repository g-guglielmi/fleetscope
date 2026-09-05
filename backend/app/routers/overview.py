from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Advisory,
    Certificate,
    Client,
    Collector,
    Finding,
    License,
    User,
    utcnow,
)
from ..schemas import OverviewClient

router = APIRouter(prefix="/api", tags=["overview"])


def collector_status(c: Collector) -> str:
    """ok | stale | offline | unknown.

    Agents check in every FS_AGENT_CHECKIN_SECONDS, so they are judged on that
    cadence; the legacy collector only pushes every few hours and keeps the
    minute-based thresholds."""
    if c.last_checkin is not None:
        age = utcnow() - c.last_checkin
        period = timedelta(seconds=settings.agent_checkin_seconds)
        if age <= period * 3:
            return "ok"
        if age <= period * 15:
            return "stale"
        return "offline"
    if c.last_seen is None:
        return "unknown"
    age = utcnow() - c.last_seen
    if age <= timedelta(minutes=settings.collector_stale_minutes):
        return "ok"
    if age <= timedelta(minutes=settings.collector_offline_minutes):
        return "stale"
    return "offline"


@router.get("/overview", response_model=list[OverviewClient])
def overview(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OverviewClient]:
    result: list[OverviewClient] = []

    for client in db.scalars(select(Client).order_by(Client.name)):
        site_ids = [s.id for s in client.sites]
        collectors = (
            list(db.scalars(select(Collector).where(Collector.site_id.in_(site_ids))))
            if site_ids else []
        )
        seen = [t for c in collectors for t in (c.last_seen, c.last_checkin) if t]
        last_seen = max(seen, default=None)

        # Roll each collector up to a single worst status for the client.
        statuses = [collector_status(c) for c in collectors]
        order = {"offline": 0, "unknown": 1, "stale": 2, "ok": 3}
        status = min(statuses, key=lambda s: order[s]) if statuses else "unknown"

        open_findings = crit_findings = 0
        nearest_cert = nearest_lic = None
        if site_ids:
            open_findings = db.scalar(
                select(func.count(Finding.id)).where(Finding.site_id.in_(site_ids))
            ) or 0
            crit_findings = db.scalar(
                select(func.count(Finding.id))
                .join(Advisory, Advisory.id == Finding.advisory_id)
                .where(Finding.site_id.in_(site_ids), Advisory.severity == "critical")
            ) or 0
            nearest_cert = db.scalar(
                select(func.min(Certificate.not_after)).where(Certificate.site_id.in_(site_ids))
            )
            nearest_lic = db.scalar(
                select(func.min(License.expires)).where(License.site_id.in_(site_ids))
            )

        result.append(OverviewClient(
            slug=client.slug,
            name=client.name,
            sites=len(site_ids),
            collectors=len(collectors),
            status=status,
            lastSeen=last_seen,
            openFindings=open_findings,
            criticalFindings=crit_findings,
            nearestCertExpiry=nearest_cert,
            nearestLicenseExpiry=nearest_lic,
        ))

    return result
