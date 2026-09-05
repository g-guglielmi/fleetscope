"""Agent identity: resolve a permanent agent token, or enroll with a temporary
enrollment token (docs/AGENT.md §6.2). Shared by /api/agent/enroll and, until
the PowerShell collector is retired, by /api/ingest."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client, Collector, EnrollmentToken, Site, utcnow
from ..security import generate_token, hash_token, slugify


def resolve_agent(db: Session, token: str) -> Collector | None:
    return db.scalar(select(Collector).where(Collector.token_hash == hash_token(token)))


def get_or_create_site(db: Session, client: Client, name: str) -> Site:
    slug = slugify(name)
    site = db.scalar(select(Site).where(Site.client_id == client.id, Site.slug == slug))
    if site is None:
        site = Site(client_id=client.id, slug=slug, name=name)
        db.add(site)
        db.flush()
    return site


def enroll(db: Session, enrollment_token: str, site_name: str, probe_name: str | None) -> tuple[Collector, str]:
    """Validate an enrollment token, create/reuse the site + collector under its
    client, mint a permanent token. Idempotent per (site, probe name): re-enrolling
    the same host rotates its token instead of creating a duplicate."""
    enrollment = db.scalar(
        select(EnrollmentToken).where(EnrollmentToken.token_hash == hash_token(enrollment_token))
    )
    if enrollment is None or not enrollment.is_valid(utcnow()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    client = db.get(Client, enrollment.client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enrollment token's client no longer exists")

    site = get_or_create_site(db, client, site_name)
    name = probe_name or f"{site.slug}-agent"

    collector = db.scalar(select(Collector).where(Collector.site_id == site.id, Collector.name == name))
    if collector is None:
        collector = Collector(site_id=site.id, name=name)
        db.add(collector)

    new_token = generate_token()
    collector.token_hash = hash_token(new_token)
    enrollment.last_used_at = utcnow()
    db.flush()
    return collector, new_token
