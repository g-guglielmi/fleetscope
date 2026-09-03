"""Daily email digest: upcoming cert/license expiries and current critical findings.

Idempotent by design — it reports the *current* state each run (a digest), so no
per-item alert state is needed for v1. Set FS_SMTP_HOST to enable; otherwise the
sweep computes the digest and logs that email is disabled.
"""

import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Advisory, Certificate, Client, Finding, License, Site, utcnow

log = logging.getLogger("alerts")


def _client_name(db: Session, site_id: int) -> str:
    site = db.get(Site, site_id)
    if not site:
        return "?"
    client = db.get(Client, site.client_id)
    return f"{client.name if client else '?'} / {site.name}"


def build_digest(db: Session) -> tuple[str, list[str]]:
    now = utcnow()
    cert_cutoff = now + timedelta(days=settings.cert_warn_days)
    lic_cutoff = now + timedelta(days=settings.license_warn_days)
    lines: list[str] = []

    certs = list(db.scalars(
        select(Certificate).where(Certificate.not_after <= cert_cutoff).order_by(Certificate.not_after)
    ))
    if certs:
        lines.append(f"Certificates expiring within {settings.cert_warn_days} days:")
        for c in certs:
            days = (c.not_after - now).days
            lines.append(f"  - {_client_name(db, c.site_id)}: {c.subject} ({c.source}) in {days}d [{c.not_after:%Y-%m-%d}]")
        lines.append("")

    lics = list(db.scalars(
        select(License).where(License.expires.is_not(None), License.expires <= lic_cutoff).order_by(License.expires)
    ))
    if lics:
        lines.append(f"Licenses expiring within {settings.license_warn_days} days:")
        for l in lics:
            days = (l.expires - now).days
            lines.append(f"  - {_client_name(db, l.site_id)}: {l.product} in {days}d [{l.expires:%Y-%m-%d}]")
        lines.append("")

    crits = list(db.execute(
        select(Finding, Advisory).join(Advisory, Advisory.id == Finding.advisory_id)
        .where(Advisory.severity == "critical")
    ))
    if crits:
        lines.append("Critical findings:")
        for finding, adv in crits:
            lines.append(f"  - {_client_name(db, finding.site_id)}: {adv.cve or adv.title} — {adv.title[:80]}")
        lines.append("")

    subject = f"FleetScope digest — {len(certs)} certs, {len(lics)} licenses, {len(crits)} criticals"
    return subject, lines


def send_digest() -> dict:
    with SessionLocal() as db:
        subject, lines = build_digest(db)

    if not lines:
        log.info("Digest empty; nothing to send.")
        return {"sent": False, "reason": "nothing to report"}

    body = "\n".join(lines)
    recipients = [r.strip() for r in settings.alert_to.split(",") if r.strip()]
    if not settings.smtp_host or not recipients:
        log.info("SMTP not configured; digest not emailed.\n%s", body)
        return {"sent": False, "reason": "smtp disabled", "preview": subject}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.alert_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)

    log.info("Digest emailed to %s", recipients)
    return {"sent": True, "recipients": recipients, "subject": subject}
