from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Collector, User
from .security import decode_access_token, hash_token


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate a dashboard user from a UI JWT."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = db.scalar(select(User).where(User.email == payload.get("sub")))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def get_collector(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Collector:
    """Authenticate a collector from its bearer token (hashed lookup)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing collector token")
    token = authorization.split(" ", 1)[1]
    collector = db.scalar(
        select(Collector).where(Collector.token_hash == hash_token(token))
    )
    if collector is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid collector token")
    return collector
