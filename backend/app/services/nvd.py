"""NVD auto-sync.

Pulls recent Citrix-related CVEs from the NVD API 2.0 and upserts them into the
`advisories` table as **review candidates** (source='nvd', needs_review=True).

They arrive WITHOUT a build predicate, so they do not auto-match components until
an operator curates `affected_below_build` (see the admin advisories endpoints).
This is the "curated + NVD" model: NVD widens coverage, humans keep matching
precise. The curated table remains the source of truth for what actually matches.
"""

import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Advisory

log = logging.getLogger("nvd")

NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# Keyword -> component type. A CVE matched by keyword is filed under that type.
KEYWORD_TYPES: list[tuple[str, str]] = [
    ("Citrix NetScaler", "netscaler"),
    ("Citrix ADC", "netscaler"),
    ("Citrix Gateway", "netscaler"),
    ("Citrix Virtual Apps and Desktops", "controller"),
    ("Citrix Virtual Delivery Agent", "vda"),
    ("Citrix StoreFront", "storefront"),
    ("Citrix Provisioning", "provisioning"),
    ("Citrix License Server", "license-server"),
]


def _severity_from_metrics(metrics: dict) -> tuple[str, float | None]:
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key)
        if entries:
            data = entries[0].get("cvssData", {})
            score = data.get("baseScore")
            sev = (data.get("baseSeverity") or entries[0].get("baseSeverity") or "unknown").lower()
            return sev, score
    return "unknown", None


def _upsert(db: Session, product_type: str, cve_item: dict) -> bool:
    cve = cve_item.get("id")
    if not cve:
        return False
    descriptions = cve_item.get("descriptions", [])
    title = next((d["value"] for d in descriptions if d.get("lang") == "en"), cve)
    severity, cvss = _severity_from_metrics(cve_item.get("metrics", {}))
    refs = cve_item.get("references", [])
    url = refs[0]["url"] if refs else None
    published = cve_item.get("published")
    pub_dt = None
    if published:
        try:
            pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            pub_dt = None

    existing = db.scalar(select(Advisory).where(Advisory.cve == cve))
    if existing:
        # Refresh NVD-derived fields but never clobber a human-curated predicate.
        existing.severity = severity
        existing.cvss = cvss
        existing.title = title[:512]
        existing.url = url
        existing.published = pub_dt
        if existing.source == "nvd" and existing.product_type != product_type:
            existing.product_type = product_type
        return False
    db.add(Advisory(
        product_type=product_type, title=title[:512], cve=cve, severity=severity,
        cvss=cvss, url=url, source="nvd", needs_review=True, published=pub_dt,
    ))
    return True


def sync_once() -> dict:
    """Run one NVD sync pass across all keywords. Returns a small summary."""
    if not settings.nvd_sync_enabled:
        return {"enabled": False}

    headers = {"apiKey": settings.nvd_api_key} if settings.nvd_api_key else {}
    added = 0
    errors: list[str] = []

    # NVD's public rate limit is 5 requests / 30s without a key, 50 with one.
    pace = 1.0 if settings.nvd_api_key else 6.5

    with SessionLocal() as db, httpx.Client(timeout=30.0, headers=headers) as client:
        for i, (keyword, ptype) in enumerate(KEYWORD_TYPES):
            if i:
                time.sleep(pace)
            try:
                resp = client.get(NVD_URL, params={
                    "keywordSearch": keyword,
                    "resultsPerPage": 200,
                })
                resp.raise_for_status()
                for v in resp.json().get("vulnerabilities", []):
                    if _upsert(db, ptype, v.get("cve", {})):
                        added += 1
            except Exception as e:  # keep going across keywords
                errors.append(f"{keyword}: {e}")
                log.warning("NVD sync failed for %s: %s", keyword, e)
        db.commit()

    result = {"enabled": True, "added": added, "errors": errors, "at": datetime.now(timezone.utc).isoformat()}
    log.info("NVD sync done: %s", result)
    return result
