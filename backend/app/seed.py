"""Idempotent bootstrap: admin user + a starter Citrix advisory set.

The advisory set is a small, illustrative seed. In production this table is the
curated feed you maintain (see docs) — add CTX bulletins as build predicates.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Advisory, User
from .security import hash_password

STARTER_ADVISORIES = [
    {
        "product_type": "netscaler",
        "title": "NetScaler ADC/Gateway sensitive information disclosure (CitrixBleed)",
        "cve": "CVE-2023-4966",
        "severity": "critical",
        "affected_below_build": "13.1-49.15",
        "fixed_build": "13.1-49.15",
        "url": "https://support.citrix.com/article/CTX579459",
        "notes": "Illustrative seed entry. Verify build predicates before relying on them.",
    },
    {
        "product_type": "netscaler",
        "title": "NetScaler ADC/Gateway unauthenticated RCE",
        "cve": "CVE-2023-3519",
        "severity": "critical",
        "affected_below_build": "13.1-49.13",
        "fixed_build": "13.1-49.13",
        "url": "https://support.citrix.com/article/CTX561482",
        "notes": "Illustrative seed entry.",
    },
    {
        "product_type": "storefront",
        "title": "StoreFront example advisory (placeholder)",
        "cve": None,
        "severity": "medium",
        "affected_below_build": "3.0",
        "fixed_build": "3.0",
        "url": None,
        "notes": "Replace with real CTX bulletins.",
    },
]


def run(db: Session) -> None:
    if db.scalar(select(func.count(User.id))) == 0:
        db.add(User(
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password),
            role="admin",
            # The bootstrap password came from an env file; make the first
            # login replace it (skipped in dev mode).
            must_change_password=not settings.dev_mode,
        ))

    if db.scalar(select(func.count(Advisory.id))) == 0:
        for a in STARTER_ADVISORIES:
            db.add(Advisory(**a))

    db.commit()
