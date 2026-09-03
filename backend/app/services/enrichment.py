"""Advisory matching.

Deliberately simple and Citrix-shaped: most CTX bulletins are published as
"affected below build X, fixed in build Y". We match a component to an advisory
of the same product type when the component's build sorts below the advisory's
`affected_below_build` (or its exact version is in `affected_versions`).

This favours a curated advisory table over generic NVD/CPE auto-matching, which
is unreliable for Citrix products.
"""

import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Advisory, Component, Finding


def _version_key(value: str | None) -> tuple[int, ...]:
    """Turn '2402.0.1000' / '13.1-49.15' into a comparable tuple of ints."""
    if not value:
        return ()
    nums = re.findall(r"\d+", value)
    return tuple(int(n) for n in nums)


def _is_affected(component: Component, adv: Advisory) -> bool:
    if adv.affected_versions and component.version in adv.affected_versions:
        return True
    if adv.affected_below_build:
        comp_key = _version_key(component.build or component.version)
        threshold = _version_key(adv.affected_below_build)
        if comp_key and threshold:
            return comp_key < threshold
    return False


def rematch_site(db: Session, site_id: int) -> int:
    """Recompute findings for a site. Returns the number of findings."""
    db.execute(delete(Finding).where(Finding.site_id == site_id))
    components = list(db.scalars(select(Component).where(Component.site_id == site_id)))
    if not components:
        return 0

    advisories = list(db.scalars(select(Advisory)))
    by_type: dict[str, list[Advisory]] = {}
    for adv in advisories:
        by_type.setdefault(adv.product_type, []).append(adv)

    count = 0
    for comp in components:
        for adv in by_type.get(comp.type, []):
            if _is_affected(comp, adv):
                db.add(Finding(site_id=site_id, component_id=comp.id, advisory_id=adv.id))
                count += 1
    return count
