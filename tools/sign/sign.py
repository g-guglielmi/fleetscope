#!/usr/bin/env python3
"""FleetScope signing tool (docs/AGENT.md §7.2).

Signs the check-module manifest and the agent release descriptor with an
Ed25519 key. Run in CI (key from the FS_SIGNING_KEY secret) and locally to
generate keys. Only needs `cryptography`.

  sign.py keygen                                   -> prints private + public key (base64)
  sign.py manifest --checks-dir checks --out checks/manifest.json [--unsigned]
  sign.py release  --exe agent-release/FleetScopeAgent.exe --version 1.0.0 --out agent-release/release.json
  sign.py verify   --file checks/manifest.json --pubkey <base64>

Private key: FS_SIGNING_KEY env var or --key. Signature covers the canonical
JSON (sorted keys, no whitespace) of the document without its "signature".
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

HEADER_RE = re.compile(r"<#\s*FLEETSCOPE\s*(\{.*?\})\s*#>", re.DOTALL)


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_private(key_b64: str | None) -> Ed25519PrivateKey:
    key_b64 = key_b64 or os.environ.get("FS_SIGNING_KEY")
    if not key_b64:
        sys.exit("error: no signing key (use --key or FS_SIGNING_KEY)")
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(key_b64))


def sign_document(doc: dict, key: Ed25519PrivateKey | None) -> dict:
    body = {k: v for k, v in doc.items() if k != "signature"}
    if key is None:
        body["signature"] = None
        return body
    sig = key.sign(canonical(body))
    body["signature"] = "ed25519:" + base64.b64encode(sig).decode("ascii")
    return body


def verify_document(doc: dict, pub_b64: str) -> bool:
    sig = doc.get("signature") or ""
    if not sig.startswith("ed25519:"):
        return False
    body = {k: v for k, v in doc.items() if k != "signature"}
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
    try:
        pub.verify(base64.b64decode(sig[len("ed25519:"):]), canonical(body))
        return True
    except Exception:
        return False


def build_manifest(checks_dir: str) -> dict:
    checks = []
    for fname in sorted(os.listdir(checks_dir)):
        if not fname.endswith(".ps1"):
            continue
        path = os.path.join(checks_dir, fname)
        with open(path, "rb") as fh:
            data = fh.read()
        m = HEADER_RE.search(data.decode("utf-8-sig"))
        if not m:
            sys.exit(f"error: {fname}: missing <# FLEETSCOPE {{...}} #> header")
        header = json.loads(m.group(1))
        name = header.get("name") or fname[:-4]
        if name != fname[:-4]:
            sys.exit(f"error: {fname}: header name {name!r} does not match filename")
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
    return {"schema": 1, "generated": now_iso(), "checks": checks}


def cmd_keygen(_args) -> None:
    key = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    priv = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print("FS_SIGNING_KEY    (GitHub Actions secret, keep private):", base64.b64encode(priv).decode())
    print("FS_SIGNING_PUBKEY (deploy.env, embedded in install commands):", base64.b64encode(pub).decode())
    print("FS_SECRETS_KEY    (deploy.env, encrypts stored credentials):", base64.b64encode(os.urandom(32)).decode())


def cmd_manifest(args) -> None:
    doc = build_manifest(args.checks_dir)
    key = None if args.unsigned else load_private(args.key)
    doc = sign_document(doc, key)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    state = "UNSIGNED" if key is None else "signed"
    print(f"{state} manifest with {len(doc['checks'])} checks -> {args.out}")


def cmd_release(args) -> None:
    with open(args.exe, "rb") as fh:
        data = fh.read()
    doc = {
        "schema": 1,
        "version": args.version,
        "file": os.path.basename(args.exe),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "publishedAt": now_iso(),
        "notes": args.notes or "",
    }
    key = None if args.unsigned else load_private(args.key)
    doc = sign_document(doc, key)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    print(f"{'UNSIGNED' if key is None else 'signed'} release {args.version} -> {args.out}")


def cmd_verify(args) -> None:
    with open(args.file, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    ok = verify_document(doc, args.pubkey)
    print("signature OK" if ok else "signature INVALID")
    sys.exit(0 if ok else 1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("keygen").set_defaults(fn=cmd_keygen)

    m = sub.add_parser("manifest")
    m.add_argument("--checks-dir", default="checks")
    m.add_argument("--out", default="checks/manifest.json")
    m.add_argument("--key")
    m.add_argument("--unsigned", action="store_true")
    m.set_defaults(fn=cmd_manifest)

    r = sub.add_parser("release")
    r.add_argument("--exe", required=True)
    r.add_argument("--version", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--notes")
    r.add_argument("--key")
    r.add_argument("--unsigned", action="store_true")
    r.set_defaults(fn=cmd_release)

    v = sub.add_parser("verify")
    v.add_argument("--file", required=True)
    v.add_argument("--pubkey", required=True)
    v.set_defaults(fn=cmd_verify)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
