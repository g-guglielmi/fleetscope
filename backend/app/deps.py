from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Collector, User
from .security import decode_access_token
from .services.enrollment import resolve_agent

# Endpoints a user may still call while a password change is pending.
_PASSWORD_CHANGE_ALLOWLIST = {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout"}


def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return authorization.split(" ", 1)[1]


def client_ip(request: Request) -> str | None:
    """Best-effort caller address; honours the reverse proxy's X-Forwarded-For."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate a dashboard user from a UI JWT."""
    token = bearer_token(authorization)
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = db.scalar(select(User).where(User.email == payload.get("sub")))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    if user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    if user.must_change_password and request.url.path not in _PASSWORD_CHANGE_ALLOWLIST:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


def get_agent(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Collector:
    """Authenticate an agent from its permanent token."""
    collector = resolve_agent(db, bearer_token(authorization))
    if collector is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid agent token")
    return collector
