from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, get_current_user, require_admin
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
from ..services.audit import audit
from ..services.enrollment import get_or_create_site
from ..services.siteconfig import config_dict, referenced_credentials
from .overview import collector_status

router = APIRouter(prefix="/api", tags=["clients"])


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


def _collector_out(c: Collector) -> dict:
    return {
        "name": c.name, "status": collector_status(c),
        "lastSeen": c.last_seen, "lastCheckin": c.last_checkin,
        "version": c.last_collector_version, "agentVersion": c.agent_version, "osVersion": c.os_version,
        "prerequisites": c.prerequisites or {}, "credentialVersions": c.credential_versions or {},
        "lastRun": c.last_run, "pendingActions": c.pending_actions or [],
    }


@router.get("/clients")
def list_clients(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"slug": c.slug, "name": c.name, "sites": len(c.sites)}
        for c in db.scalars(select(Client).order_by(Client.name))
    ]


@router.post("/clients/{slug}/sites", status_code=201)
def create_site(slug: str, body: SiteIn, request: Request, me: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Pre-create a site so it can be configured before its agent is installed."""
    client = db.scalar(select(Client).where(Client.slug == slug))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown client")
    site = get_or_create_site(db, client, body.name.strip())
    audit(db, me.email, "site.create", "site", f"{client.slug}/{site.slug}", {"name": site.name}, client_ip(request))
    db.commit()
    return {"slug": site.slug, "name": site.name}


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

        config = config_dict(site.config)
        enabled = [k for k, v in (config.get("checks") or {}).items() if v.get("enabled")]
        sites_out.append({
            "slug": site.slug,
            "name": site.name,
            "configured": site.config is not None,
            "enabledChecks": enabled,
            "serviceAccount": (config.get("agent") or {}).get("serviceAccount"),
            "referencedCredentials": sorted(referenced_credentials(config)),
            "collectors": [_collector_out(c) for c in collectors],
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
