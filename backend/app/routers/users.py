"""Dashboard user management (admin only). docs/AGENT.md §6.5."""

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, require_admin
from ..models import User
from ..security import hash_password
from ..services.audit import audit

router = APIRouter(prefix="/api/admin/users", tags=["users"])

ROLES = {"admin", "viewer"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserIn(BaseModel):
    email: str
    password: str = Field(min_length=12, max_length=256)
    role: str = "viewer"


class UserPatch(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


def _out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "role": u.role, "disabled": u.disabled,
        "mustChangePassword": u.must_change_password, "lastLogin": u.last_login, "createdAt": u.created_at,
    }


def _active_admins(db: Session) -> int:
    return db.scalar(
        select(func.count(User.id)).where(User.role == "admin", User.disabled.is_(False))
    ) or 0


@router.get("")
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    return [_out(u) for u in db.scalars(select(User).order_by(User.email))]


@router.post("", status_code=201)
def create_user(body: UserIn, request: Request, me: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Invalid email address")
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {sorted(ROLES)}")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "User already exists")
    user = User(email=email, password_hash=hash_password(body.password), role=body.role, must_change_password=True)
    db.add(user)
    db.flush()
    audit(db, me.email, "user.create", "user", user.id, {"email": email, "role": body.role}, client_ip(request))
    db.commit()
    return _out(user)


@router.patch("/{user_id}")
def update_user(
    user_id: int, body: UserPatch, request: Request,
    me: User = Depends(require_admin), db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown user")
    changes: dict = {}

    if body.role is not None and body.role != user.role:
        if body.role not in ROLES:
            raise HTTPException(422, f"role must be one of {sorted(ROLES)}")
        if user.role == "admin" and not user.disabled and _active_admins(db) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "Cannot demote the last active admin")
        user.role = body.role
        changes["role"] = body.role

    if body.disabled is not None and body.disabled != user.disabled:
        if user.id == me.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot disable your own account")
        if body.disabled and user.role == "admin" and _active_admins(db) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "Cannot disable the last active admin")
        user.disabled = body.disabled
        changes["disabled"] = body.disabled

    if body.password is not None:
        user.password_hash = hash_password(body.password)
        user.must_change_password = True
        changes["passwordReset"] = True

    if changes:
        audit(db, me.email, "user.update", "user", user.id, changes, client_ip(request))
    db.commit()
    return _out(user)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request, me: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown user")
    if user.id == me.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot delete your own account")
    if user.role == "admin" and not user.disabled and _active_admins(db) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot delete the last active admin")
    audit(db, me.email, "user.delete", "user", user.id, {"email": user.email}, client_ip(request))
    db.delete(user)
    db.commit()
