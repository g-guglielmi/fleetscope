import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from .config import settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---- User passwords ----
def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd.verify(password, password_hash)


# ---- Collector tokens ----
def generate_collector_token() -> str:
    """A high-entropy opaque token handed to a collector once, never stored raw."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# ---- JWT for the UI ----
def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
