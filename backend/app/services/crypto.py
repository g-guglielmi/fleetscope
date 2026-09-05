"""Encryption at rest for stored credentials (docs/AGENT.md §4.5).

AES-256-GCM under FS_SECRETS_KEY (base64, 32 bytes). The key lives only in the
deployment's env file, never in the database, so a copied SQLite file alone
reveals nothing. There is deliberately no fallback key: with FS_SECRETS_KEY
unset, credential features are disabled.
"""

import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings

_NONCE_BYTES = 12


class SecretsDisabled(RuntimeError):
    pass


def _key() -> bytes | None:
    if not settings.secrets_key:
        return None
    try:
        raw = base64.b64decode(settings.secrets_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("FS_SECRETS_KEY is not valid base64") from exc
    if len(raw) != 32:
        raise ValueError("FS_SECRETS_KEY must decode to exactly 32 bytes")
    return raw


def secrets_enabled() -> bool:
    return _key() is not None


def validate_key() -> str | None:
    """Return an error message if the configured key is malformed, else None.
    Used by the startup checks; an unset key is not an error."""
    try:
        _key()
    except ValueError as exc:
        return str(exc)
    return None


def generate_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    key = _key()
    if key is None:
        raise SecretsDisabled("FS_SECRETS_KEY is not set")
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    key = _key()
    if key is None:
        raise SecretsDisabled("FS_SECRETS_KEY is not set")
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
