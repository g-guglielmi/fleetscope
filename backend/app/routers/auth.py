from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, get_current_user
from ..models import User, utcnow
from ..schemas import ChangePasswordRequest, LoginRequest, TokenResponse
from ..security import create_access_token, hash_password, verify_password
from ..services.audit import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or user.disabled or not verify_password(body.password, user.password_hash):
        audit(db, body.email, "auth.login_failed", "user", None, ip=client_ip(request))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    user.last_login = utcnow()
    audit(db, user.email, "auth.login", "user", user.id, ip=client_ip(request))
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.email),
        role=user.role,
        mustChangePassword=user.must_change_password,
    )


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"email": user.email, "role": user.role, "mustChangePassword": user.must_change_password}


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(body.currentPassword, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if body.newPassword == body.currentPassword:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must differ from the current one")
    user.password_hash = hash_password(body.newPassword)
    user.must_change_password = False
    audit(db, user.email, "user.password_changed", "user", user.id, ip=client_ip(request))
    db.commit()
    return {"ok": True}
