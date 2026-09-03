import hmac

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User
from .security import decode_access_token


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return authorization.split(" ", 1)[1]


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate a dashboard user from a UI JWT."""
    token = _bearer(authorization)
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = db.scalar(select(User).where(User.email == payload.get("sub")))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def verify_ingest_key(authorization: str | None = Header(default=None)) -> None:
    """Authenticate a probe via the shared ingest key (constant-time compare)."""
    if not settings.ingest_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Ingest not configured")
    token = _bearer(authorization)
    if not hmac.compare_digest(token, settings.ingest_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid ingest key")
