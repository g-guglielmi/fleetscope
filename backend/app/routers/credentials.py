"""Dashboard-managed credentials (admin only, write-only). docs/AGENT.md §4.5.

Plaintext never leaves this module towards UI users; agents fetch it through
/api/agent/credentials/{name} (routers/agent.py) after authorization."""

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, require_admin
from ..models import Client, Collector, Credential, Site, User
from ..services import crypto
from ..services.audit import audit
from ..services.siteconfig import config_dict, referenced_credentials

router = APIRouter(prefix="/api/admin/credentials", tags=["credentials"])

KINDS = {"device", "windows"}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


class CredentialIn(BaseModel):
    client: str            # client slug
    name: str
    kind: str
    username: str
    password: str = ""


class CredentialPatch(BaseModel):
    username: str | None = None
    password: str | None = None


def _require_secrets() -> None:
    if not crypto.secrets_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Credential storage is disabled: set FS_SECRETS_KEY (see deploy.env.example)",
        )


def _is_gmsa(kind: str, username: str) -> bool:
    return kind == "windows" and username.rstrip().endswith("$")


def _usage(db: Session, cred: Credential) -> tuple[list[dict], list[dict]]:
    """Sites whose config references this credential; agents that hold it."""
    referenced: list[dict] = []
    held: list[dict] = []
    for site in db.scalars(select(Site).where(Site.client_id == cred.client_id)):
        if cred.name in referenced_credentials(config_dict(site.config)):
            referenced.append({"site": site.slug, "siteName": site.name})
        for col in db.scalars(select(Collector).where(Collector.site_id == site.id)):
            ver = (col.credential_versions or {}).get(cred.name)
            if ver is not None:
                held.append({"site": site.slug, "agent": col.name, "version": ver, "current": ver == cred.version})
    return referenced, held


def _out(db: Session, cred: Credential, client: Client) -> dict:
    referenced, held = _usage(db, cred)
    return {
        "id": cred.id, "client": client.slug, "name": cred.name, "kind": cred.kind,
        "username": cred.username, "version": cred.version, "gmsa": _is_gmsa(cred.kind, cred.username),
        "updatedAt": cred.updated_at, "updatedBy": cred.updated_by,
        "referencedBy": referenced, "heldBy": held,
    }


@router.get("")
def list_credentials(client: str | None = None, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Credential, Client).join(Client, Client.id == Credential.client_id).order_by(Client.name, Credential.name)
    if client:
        stmt = stmt.where(Client.slug == client)
    return [_out(db, cred, cl) for cred, cl in db.execute(stmt)]


@router.post("", status_code=201)
def create_credential(body: CredentialIn, request: Request, me: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    _require_secrets()
    client = db.scalar(select(Client).where(Client.slug == body.client))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown client")
    name = body.name.strip().lower()
    if not _NAME_RE.match(name):
        raise HTTPException(422, "name: lowercase letters, digits, '-' or '_' (max 64)")
    if body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    username = body.username.strip()
    if not username:
        raise HTTPException(422, "username is required")
    if not body.password and not _is_gmsa(body.kind, username):
        raise HTTPException(422, "password is required (only a gMSA, username ending in '$', may omit it)")
    if db.scalar(select(Credential).where(Credential.client_id == client.id, Credential.name == name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A credential with this name already exists for the client")

    ct, nonce = crypto.encrypt(body.password)
    cred = Credential(client_id=client.id, name=name, kind=body.kind, username=username,
                      secret_ciphertext=ct, secret_nonce=nonce, version=1, updated_by=me.email)
    db.add(cred)
    db.flush()
    audit(db, me.email, "credential.create", "credential", cred.id,
          {"client": client.slug, "name": name, "kind": body.kind, "username": username}, client_ip(request))
    db.commit()
    return _out(db, cred, client)


@router.patch("/{cred_id}")
def update_credential(cred_id: int, body: CredentialPatch, request: Request, me: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    _require_secrets()
    cred = db.get(Credential, cred_id)
    if cred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown credential")
    client = db.get(Client, cred.client_id)
    changes: dict = {}
    if body.username is not None and body.username.strip() and body.username.strip() != cred.username:
        cred.username = body.username.strip()
        changes["username"] = cred.username
    if body.password is not None:
        if not body.password and not _is_gmsa(cred.kind, cred.username):
            raise HTTPException(422, "password cannot be empty")
        cred.secret_ciphertext, cred.secret_nonce = crypto.encrypt(body.password)
        changes["passwordRotated"] = True
    if changes:
        cred.version += 1
        cred.updated_by = me.email
        changes["version"] = cred.version
        audit(db, me.email, "credential.update", "credential", cred.id, {"name": cred.name, **changes}, client_ip(request))
    db.commit()
    return _out(db, cred, client)


@router.delete("/{cred_id}", status_code=204)
def delete_credential(cred_id: int, request: Request, me: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    cred = db.get(Credential, cred_id)
    if cred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown credential")
    referenced, _ = _usage(db, cred)
    if referenced:
        sites = ", ".join(r["siteName"] for r in referenced)
        raise HTTPException(status.HTTP_409_CONFLICT, f"Credential is referenced by: {sites}. Remove the references first.")
    audit(db, me.email, "credential.delete", "credential", cred.id, {"name": cred.name}, client_ip(request))
    db.delete(cred)
    db.commit()
