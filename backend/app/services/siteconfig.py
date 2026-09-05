"""Site configuration helpers: defaults, validation against the check manifest
and the client's credentials, and the set of credential names a config
references (which bounds what an agent may fetch)."""

import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client, Credential, Site, SiteConfig
from .manifest import load_manifest

_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_]{0,253}$")
_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


def config_dict(cfg: SiteConfig | None) -> dict:
    """Wire shape for the UI and the agent (docs/AGENT.md §6.3)."""
    if cfg is None:
        return {"intervalMinutes": 360, "autoUpdate": True, "agent": {}, "prerequisites": {}, "checks": {}}
    return {
        "intervalMinutes": cfg.interval_minutes,
        "autoUpdate": cfg.auto_update,
        "agent": cfg.agent or {},
        "prerequisites": cfg.prerequisites or {},
        "checks": cfg.checks or {},
        "updatedAt": cfg.updated_at,
        "updatedBy": cfg.updated_by,
    }


def referenced_credentials(config: dict) -> set[str]:
    """Every credential name a config points at: the agent's service account plus
    any `credential` value anywhere inside check settings."""
    names: set[str] = set()
    sa = (config.get("agent") or {}).get("serviceAccount")
    if sa:
        names.add(str(sa))

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "credential" and isinstance(v, str) and v:
                    names.add(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for check in (config.get("checks") or {}).values():
        if isinstance(check, dict):
            walk(check.get("settings") or {})
    return names


def get_or_create_config(db: Session, site: Site) -> SiteConfig:
    if site.config is None:
        site.config = SiteConfig(site_id=site.id)
        db.add(site.config)
        db.flush()
    return site.config


def _bad(msg: str) -> HTTPException:
    return HTTPException(422, msg)


def _validate_value(path: str, schema, value, creds: dict[str, Credential]) -> None:
    """Validate one settings value against a settingsSchema node.

    Schema nodes are either a string type ("hostList", "list", "url", "host",
    "string", "bool", "int", "credentialRef") or a dict {"type": ..., "item": ...,
    "required": bool}."""
    if isinstance(schema, str):
        schema = {"type": schema}
    typ = schema.get("type", "string")

    if value is None:
        if schema.get("required"):
            raise _bad(f"{path}: required")
        return

    if typ == "hostList":
        if not isinstance(value, list) or not all(isinstance(v, str) and _HOST_RE.match(v) for v in value):
            raise _bad(f"{path}: must be a list of hostnames/IPs")
        if schema.get("required") and not value:
            raise _bad(f"{path}: at least one entry required")
    elif typ == "list":
        if not isinstance(value, list):
            raise _bad(f"{path}: must be a list")
        if schema.get("required") and not value:
            raise _bad(f"{path}: at least one entry required")
        item = schema.get("item")
        if isinstance(item, dict) and "type" not in item:
            # item is an object schema: {field: schemaNode}
            for i, entry in enumerate(value):
                if not isinstance(entry, dict):
                    raise _bad(f"{path}[{i}]: must be an object")
                for field, sub in item.items():
                    _validate_value(f"{path}[{i}].{field}", sub, entry.get(field), creds)
        elif item is not None:
            for i, entry in enumerate(value):
                _validate_value(f"{path}[{i}]", item, entry, creds)
    elif typ == "host":
        if not isinstance(value, str) or not _HOST_RE.match(value):
            raise _bad(f"{path}: invalid hostname")
    elif typ == "url":
        if not isinstance(value, str) or not _URL_RE.match(value):
            raise _bad(f"{path}: invalid URL (must start with http:// or https://)")
    elif typ == "string":
        if not isinstance(value, str):
            raise _bad(f"{path}: must be a string")
    elif typ == "bool":
        if not isinstance(value, bool):
            raise _bad(f"{path}: must be true/false")
    elif typ == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise _bad(f"{path}: must be an integer")
    elif typ == "credentialRef":
        if not isinstance(value, str) or value not in creds:
            raise _bad(f"{path}: unknown credential '{value}' for this client")
        want = schema.get("kind", "device")
        if creds[value].kind != want:
            raise _bad(f"{path}: credential '{value}' is kind '{creds[value].kind}', expected '{want}'")
    else:
        raise _bad(f"{path}: unsupported schema type '{typ}'")


def validate_config(db: Session, client: Client, body: dict) -> dict:
    """Validate and normalize an incoming config. Returns the cleaned dict."""
    manifest = {c["name"]: c for c in load_manifest().get("checks", [])}
    creds = {c.name: c for c in db.scalars(select(Credential).where(Credential.client_id == client.id))}

    interval = body.get("intervalMinutes", 360)
    if not isinstance(interval, int) or isinstance(interval, bool) or not 15 <= interval <= 1440:
        raise _bad("intervalMinutes: must be an integer between 15 and 1440")
    auto_update = body.get("autoUpdate", True)
    if not isinstance(auto_update, bool):
        raise _bad("autoUpdate: must be true/false")

    agent = body.get("agent") or {}
    if not isinstance(agent, dict):
        raise _bad("agent: must be an object")
    sa = agent.get("serviceAccount")
    if sa is not None and sa != "":
        if sa not in creds:
            raise _bad(f"agent.serviceAccount: unknown credential '{sa}' for this client")
        if creds[sa].kind != "windows":
            raise _bad(f"agent.serviceAccount: credential '{sa}' is not a windows credential")
    agent_clean = {"serviceAccount": sa or None}

    prereq = body.get("prerequisites") or {}
    if not isinstance(prereq, dict):
        raise _bad("prerequisites: must be an object")
    prereq_clean = {
        "unattended": bool(prereq.get("unattended", False)),
        "citrixSdkSource": (prereq.get("citrixSdkSource") or None),
    }
    if prereq_clean["citrixSdkSource"] is not None and not isinstance(prereq_clean["citrixSdkSource"], str):
        raise _bad("prerequisites.citrixSdkSource: must be a string path")

    checks_in = body.get("checks") or {}
    if not isinstance(checks_in, dict):
        raise _bad("checks: must be an object")
    checks_clean: dict = {}
    for name, entry in checks_in.items():
        if name not in manifest:
            raise _bad(f"checks.{name}: unknown check")
        if not isinstance(entry, dict):
            raise _bad(f"checks.{name}: must be an object")
        enabled = bool(entry.get("enabled", False))
        settings_in = entry.get("settings") or {}
        if not isinstance(settings_in, dict):
            raise _bad(f"checks.{name}.settings: must be an object")
        schema = manifest[name].get("settingsSchema") or {}
        unknown = set(settings_in) - set(schema)
        if unknown:
            raise _bad(f"checks.{name}.settings: unknown fields {sorted(unknown)}")
        if enabled:
            for field, node in schema.items():
                _validate_value(f"checks.{name}.settings.{field}", node, settings_in.get(field), creds)
        checks_clean[name] = {"enabled": enabled, "settings": settings_in}

    return {
        "intervalMinutes": interval,
        "autoUpdate": auto_update,
        "agent": agent_clean,
        "prerequisites": prereq_clean,
        "checks": checks_clean,
    }
