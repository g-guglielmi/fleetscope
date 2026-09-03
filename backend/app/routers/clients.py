from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Advisory,
    Certificate,
    Client,
    Collector,
    Component,
    Finding,
    License,
    Site,
    User,
)

router = APIRouter(prefix="/api", tags=["clients"])


@router.get("/clients")
def list_clients(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"slug": c.slug, "name": c.name, "sites": len(c.sites)}
        for c in db.scalars(select(Client).order_by(Client.name))
    ]


@router.get("/clients/{slug}")
def client_detail(
    slug: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    client = db.scalar(select(Client).where(Client.slug == slug))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown client")

    sites_out = []
    for site in client.sites:
        collectors = list(db.scalars(select(Collector).where(Collector.site_id == site.id)))
        components = list(db.scalars(select(Component).where(Component.site_id == site.id)))
        certs = list(db.scalars(select(Certificate).where(Certificate.site_id == site.id)))
        licenses = list(db.scalars(select(License).where(License.site_id == site.id)))

        findings = list(
            db.execute(
                select(Finding, Advisory, Component)
                .join(Advisory, Advisory.id == Finding.advisory_id)
                .join(Component, Component.id == Finding.component_id)
                .where(Finding.site_id == site.id)
            )
        )

        sites_out.append({
            "slug": site.slug,
            "name": site.name,
            "collectors": [
                {"name": c.name, "lastSeen": c.last_seen, "version": c.last_collector_version}
                for c in collectors
            ],
            "components": [
                {
                    "type": c.type, "hostname": c.hostname, "product": c.product,
                    "version": c.version, "build": c.build, "osVersion": c.os_version,
                    "extra": c.extra,
                }
                for c in components
            ],
            "certificates": [
                {
                    "source": c.source, "hostname": c.hostname, "subject": c.subject,
                    "issuer": c.issuer, "notAfter": c.not_after, "thumbprint": c.thumbprint,
                }
                for c in certs
            ],
            "licenses": [
                {
                    "product": l.product, "edition": l.edition, "model": l.model,
                    "count": l.count, "subscriptionAdvantageDate": l.subscription_advantage_date,
                    "expires": l.expires,
                }
                for l in licenses
            ],
            "findings": [
                {
                    "hostname": comp.hostname, "type": comp.type,
                    "build": comp.build or comp.version,
                    "cve": adv.cve, "severity": adv.severity, "title": adv.title,
                    "fixedBuild": adv.fixed_build, "url": adv.url,
                }
                for (_f, adv, comp) in findings
            ],
        })

    return {"slug": client.slug, "name": client.name, "sites": sites_out}
