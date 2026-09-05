"""Check-module manifest and agent release descriptor (docs/AGENT.md §5.1, §4.7).

Both are files shipped inside the image:
  <checks_dir>/manifest.json           signed in CI by tools/sign/sign.py
  <agent_release_dir>/release.json     signed in CI; plus FleetScopeAgent.exe

If checks/manifest.json is absent (local dev), an UNSIGNED manifest is built
from the *.ps1 headers on the fly so the UI and API still work. Agents refuse
unsigned manifests, which is the intended behaviour outside dev.

Each check script starts with a header the server and the signing tool parse
identically:

    <# FLEETSCOPE
    { "name": "netscaler", "version": "1.0.0", "requires": [], "timeoutSeconds": 300,
      "description": "...", "settingsSchema": { ... } }
    #>
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

from ..config import settings

log = logging.getLogger(__name__)

_HEADER_RE = re.compile(r"<#\s*FLEETSCOPE\s*(\{.*?\})\s*#>", re.DOTALL)
_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # backend/


def _first_existing(*candidates: str) -> str:
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return candidates[-1]


CHECKS_DIR = _first_existing(
    settings.checks_dir,
    os.path.join(_BASE, "checks"),                       # /app/checks in the image
    os.path.join(os.path.dirname(_BASE), "checks"),      # <repo>/checks in dev
)
AGENT_DIR = _first_existing(
    settings.agent_release_dir,
    os.path.join(_BASE, "agent"),                        # /app/agent in the image
    os.path.join(os.path.dirname(_BASE), "agent-release"),
)


def canonical_json(obj) -> bytes:
    """Deterministic serialization used for signatures (mirrors tools/sign)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def parse_header(text: str) -> dict:
    m = _HEADER_RE.search(text)
    if not m:
        raise ValueError("missing <# FLEETSCOPE {...} #> header")
    return json.loads(m.group(1))


def build_unsigned_manifest(checks_dir: str = CHECKS_DIR) -> dict:
    checks = []
    if os.path.isdir(checks_dir):
        for fname in sorted(os.listdir(checks_dir)):
            if not fname.endswith(".ps1"):
                continue
            path = os.path.join(checks_dir, fname)
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                header = parse_header(data.decode("utf-8-sig"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                log.warning("check %s skipped: %s", fname, exc)
                continue
            name = header.get("name") or fname[:-4]
            if name != fname[:-4]:
                log.warning("check %s: header name %r does not match filename; skipped", fname, name)
                continue
            checks.append({
                "name": name,
                "version": header.get("version", "0.0.0"),
                "description": header.get("description", ""),
                "file": fname,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "shell": header.get("shell", "powershell"),
                "requires": header.get("requires", []),
                "timeoutSeconds": int(header.get("timeoutSeconds", 300)),
                "settingsSchema": header.get("settingsSchema", {}),
            })
    return {
        "schema": 1,
        "generated": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "checks": checks,
        "signature": None,
    }


_cache: dict = {"key": None, "manifest": None}


def load_manifest() -> dict:
    """Signed manifest.json if present, else an unsigned one built from headers.
    Cached on the directory's mtimes so edits in dev show up without restarts."""
    signed_path = os.path.join(CHECKS_DIR, "manifest.json")
    try:
        entries = os.listdir(CHECKS_DIR) if os.path.isdir(CHECKS_DIR) else []
        key = tuple(sorted((e, os.path.getmtime(os.path.join(CHECKS_DIR, e))) for e in entries))
    except OSError:
        key = ()
    if _cache["key"] == key and _cache["manifest"] is not None:
        return _cache["manifest"]

    if os.path.isfile(signed_path):
        with open(signed_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    else:
        manifest = build_unsigned_manifest()
    _cache.update(key=key, manifest=manifest)
    return manifest


def is_signed(manifest: dict) -> bool:
    return bool(manifest.get("signature"))


def get_check(name: str) -> tuple[dict, str] | None:
    for entry in load_manifest().get("checks", []):
        if entry["name"] == name:
            return entry, os.path.join(CHECKS_DIR, entry.get("file", f"{name}.ps1"))
    return None


def check_names() -> set[str]:
    return {c["name"] for c in load_manifest().get("checks", [])}


def load_release() -> dict | None:
    path = os.path.join(AGENT_DIR, "release.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def release_exe_path() -> str | None:
    rel = load_release()
    if not rel:
        return None
    path = os.path.join(AGENT_DIR, rel.get("file", "FleetScopeAgent.exe"))
    return path if os.path.isfile(path) else None
