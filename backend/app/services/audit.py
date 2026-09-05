"""Audit trail for security-relevant actions (users, credentials, config, agent
enrollment, credential delivery). Rows are appended in the caller's session and
committed with it."""

from sqlalchemy.orm import Session

from ..models import AuditLog


def audit(
    db: Session,
    actor: str,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    db.add(AuditLog(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        detail=detail,
        ip=ip,
    ))
