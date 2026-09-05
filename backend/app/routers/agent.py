"""Agent-facing API (docs/AGENT.md §6.2): enroll, check in, fetch check modules,
credentials and the agent release. Results are still pushed to /api/ingest."""

import hashlib

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import bearer_token, client_ip, get_agent
from ..models import Client, Collector, Credential, Site, utcnow
from ..schemas import CheckinRequest, EnrollRequest
from ..services import crypto
from ..services.audit import audit
from ..services.enrollment import enroll
from ..services.manifest import get_check, load_manifest, load_release, release_exe_path
from ..services.siteconfig import config_dict, referenced_credentials

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _actor(collector: Collector) -> str:
    return f"agent:{collector.name}"


@router.post("/enroll", status_code=201)
def agent_enroll(
    body: EnrollRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    collector, token = enroll(db, bearer_token(authorization), body.site, body.hostname)
    collector.agent_version = body.agentVersion
    collector.os_version = body.osVersion
    collector.last_checkin = utcnow()
    site = db.get(Site, collector.site_id)
    client = db.get(Client, site.client_id)
    audit(db, _actor(collector), "agent.enroll", "collector", collector.id,
          {"client": client.slug, "site": site.slug, "hostname": body.hostname, "agentVersion": body.agentVersion},
          client_ip(request))
    db.commit()
    return {
        "agentToken": token,
        "client": {"slug": client.slug, "name": client.name},
        "site": {"slug": site.slug, "name": site.name},
        "checkinSeconds": settings.agent_checkin_seconds,
    }


@router.post("/checkin")
def agent_checkin(
    body: CheckinRequest,
    collector: Collector = Depends(get_agent),
    db: Session = Depends(get_db),
) -> dict:
    site = db.get(Site, collector.site_id)
    client = db.get(Client, site.client_id)

    collector.last_checkin = utcnow()
    if body.agentVersion:
        collector.agent_version = body.agentVersion
    if body.osVersion:
        collector.os_version = body.osVersion
    collector.prerequisites = body.prerequisites or {}
    collector.credential_versions = body.credentialVersions or {}
    if body.lastRun is not None:
        collector.last_run = body.lastRun

    actions = list(collector.pending_actions or [])
    collector.pending_actions = []

    config = config_dict(site.config)
    referenced = referenced_credentials(config)
    creds = [
        {"name": c.name, "kind": c.kind, "version": c.version}
        for c in db.scalars(select(Credential).where(Credential.client_id == client.id))
        if c.name in referenced
    ]
    db.commit()

    return {
        "serverTime": utcnow(),
        "checkinSeconds": settings.agent_checkin_seconds,
        "client": {"slug": client.slug, "name": client.name},
        "site": {"slug": site.slug, "name": site.name},
        "config": {k: v for k, v in config.items() if k not in ("updatedAt", "updatedBy")},
        "manifest": load_manifest(),
        "release": load_release(),
        "credentials": creds,
        "actions": actions,
    }


@router.get("/checks/{name}")
def get_check_script(
    name: str,
    _: Collector = Depends(get_agent),
    if_none_match: str | None = Header(default=None),
) -> Response:
    found = get_check(name)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown check")
    entry, path = found
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Check file missing")
    digest = hashlib.sha256(data).hexdigest()
    etag = f'"{digest}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return PlainTextResponse(
        data, media_type="text/plain; charset=utf-8",
        headers={"ETag": etag, "X-Checksum-Sha256": digest, "X-Check-Version": entry.get("version", "")},
    )


@router.get("/credentials/{name}")
def get_credential(
    name: str,
    request: Request,
    collector: Collector = Depends(get_agent),
    db: Session = Depends(get_db),
) -> dict:
    """Deliver one credential — only if this agent's site config references it."""
    site = db.get(Site, collector.site_id)
    if name not in referenced_credentials(config_dict(site.config)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Credential not referenced by this site's configuration")
    cred = db.scalar(select(Credential).where(Credential.client_id == site.client_id, Credential.name == name))
    if cred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown credential")
    try:
        password = crypto.decrypt(cred.secret_ciphertext, cred.secret_nonce)
    except crypto.SecretsDisabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Credential storage is disabled on the server")
    audit(db, _actor(collector), "credential.deliver", "credential", cred.id,
          {"name": cred.name, "version": cred.version, "site": site.slug}, client_ip(request))
    db.commit()
    return {"name": cred.name, "kind": cred.kind, "username": cred.username, "password": password, "version": cred.version}


@router.get("/release")
def get_release(_: Collector = Depends(get_agent)) -> dict:
    rel = load_release()
    if rel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No agent release published on this server")
    return rel


@router.get("/release/download")
def download_release() -> FileResponse:
    """Unauthenticated on purpose: this is how a fresh management VM bootstraps
    the agent before it has any token. The binary is public in GitHub Releases
    too; integrity comes from the signed release.json the agent verifies."""
    path = release_exe_path()
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No agent release published on this server")
    return FileResponse(path, media_type="application/octet-stream", filename="FleetScopeAgent.exe")
