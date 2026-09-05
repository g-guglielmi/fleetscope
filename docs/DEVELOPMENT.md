# Development

Architecture and roadmap: `AGENT.md`. Ingest payload: `COLLECTOR_CONTRACT.md`.

## Backend (FastAPI + SQLite)

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate    # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
FS_DEV_MODE=true uvicorn app.main:app --reload
```

- API docs at http://localhost:8000/docs
- SQLite file `fleetscope.db` is created in the working dir (override with `FS_DATABASE_URL`).
- On first start it runs the Alembic migrations, creates the admin user
  (`FS_ADMIN_EMAIL` / `FS_ADMIN_PASSWORD`, default `admin@local` / `changeme`) and a
  starter advisory set.
- **`FS_DEV_MODE=true` is required locally**: without it the app refuses to start on
  default secrets (`FS_JWT_SECRET`, `FS_ADMIN_PASSWORD`) and forces a password change
  on the bootstrap admin. Never set it in a deployment.
- Credential storage needs `FS_SECRETS_KEY` (base64, 32 bytes). Generate one along
  with the signing key pair: `python tools/sign/sign.py keygen`.
- `TZ` (e.g. `Europe/Rome`) sets the timezone for the scheduled NVD sync and digest.

## Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8000
npx tsc --noEmit   # type-check
```

In the Docker image the SPA is built and served by the backend at `/`, so there is
no separate frontend server in production.

## Roles

- **admin** — everything: clients, sites, configuration, credentials, users, audit.
- **viewer** — read-only: overview, clients, sites, inventory, findings.

New users (and the env-seeded bootstrap admin outside dev mode) must change their
password at first login; until then every endpoint except `/api/auth/*` returns 403.

## End-to-end walk-through (UI)

1. Log in → **+ Add Client**.
2. On the client page: **+ Add site**, then add **Credentials** — one `windows`
   credential for the agent's service account (a gMSA needs no password), one
   `device` credential per NetScaler (use a read-only NITRO user).
3. Open the site → **Configuration**: pick *Run agent as*, enable checks and fill
   their settings (forms are generated from each check's `settingsSchema`) → Save.
4. Back on the client page → **Install agent** → pick the site → generate the
   command. Run it on the management VM (phase 2 delivers the agent binary; until
   then the API can be exercised as below).

## Agent API smoke test (curl)

```bash
TOKEN=$(curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@local","password":"changeme"}' | jq -r .access_token)
ENR=$(curl -s -X POST localhost:8000/api/admin/clients/enwenta/install-command \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"site":"Bolzano-BCOM"}' | jq -r .enrollment.token)

# enroll -> permanent agent token
AGENT=$(curl -s -X POST localhost:8000/api/agent/enroll -H "Authorization: Bearer $ENR" \
  -H 'Content-Type: application/json' \
  -d '{"site":"Bolzano-BCOM","hostname":"MGMT01","agentVersion":"0.1.0"}' | jq -r .agentToken)

# check-in: config, signed manifest, credential versions, pending actions
curl -s -X POST localhost:8000/api/agent/checkin -H "Authorization: Bearer $AGENT" \
  -H 'Content-Type: application/json' -d '{"agentVersion":"0.1.0","prerequisites":{"cvad-sdk":null}}' | jq .

# a check module, and a credential the site config references
curl -s localhost:8000/api/agent/checks/netscaler -H "Authorization: Bearer $AGENT" | head
curl -s localhost:8000/api/agent/credentials/ns-bolzano -H "Authorization: Bearer $AGENT"
```

Results still go to `POST /api/ingest` (same token), now with an optional
`diagnostics` array (per-check status) that the site page displays.

`scratchpad`-style full regression: see the smoke test used during phase 1 —
it exercises roles, credentials, config validation, enrollment idempotency,
check-in actions, ETag downloads, credential delivery authorization, ingest and
audit (78 assertions).

## Check modules (`checks/*.ps1`)

A check is one Windows PowerShell 5.1 script: JSON in on stdin, JSON out on
stdout, exit 0 (see `AGENT.md` §5). Its header declares metadata and the
`settingsSchema` the UI renders:

```powershell
<# FLEETSCOPE
{ "name": "netscaler", "version": "1.0.0", "requires": [], "timeoutSeconds": 180,
  "description": "...", "settingsSchema": { ... } }
#>
```

Test one by hand on any Windows box (stdin = the input the agent would build):
```powershell
@'
{ "schema": 1, "check": "netscaler", "site": {"client":"ENWENTA","site":"Bolzano-BCOM"},
  "settings": { "targets": [ { "host": "https://10.20.15.201", "credential": "ns", "skipCertificateCheck": true } ] },
  "credentials": { "ns": { "username": "fleetscope-ro", "password": "..." } } }
'@ | powershell -NoProfile -NonInteractive -File checks\netscaler.ps1
```

Adding a check = adding a file. The server rebuilds an **unsigned** manifest from the
headers in dev; CI signs the real one (below). Agents refuse unsigned manifests.

### Prerequisite for `citrix-site`
Install the **CVAD PowerShell SDK** from the CVAD product ISO
(`x64\Citrix Desktop Delivery Controller\Broker_PowerShellSnapIn_x64.msi` is enough),
matching the site's version. The separately downloadable "Remote PowerShell SDK" is
the Citrix Cloud/DaaS variant and is **not** the right one for an on-prem site.

## Signing (`tools/sign/sign.py`)

```bash
python tools/sign/sign.py keygen          # prints FS_SIGNING_KEY, FS_SIGNING_PUBKEY, FS_SECRETS_KEY
python tools/sign/sign.py manifest --checks-dir checks --out checks/manifest.json   # FS_SIGNING_KEY in env
python tools/sign/sign.py verify --file checks/manifest.json --pubkey <FS_SIGNING_PUBKEY>
```
- `FS_SIGNING_KEY` → GitHub Actions repository secret (CI signs `checks/manifest.json`
  before the image build; unsigned with a warning if the secret is missing).
- `FS_SIGNING_PUBKEY` and `FS_SECRETS_KEY` → `deploy/deploy.env`.
- `checks/manifest.json` is generated and gitignored.

## Advisories: curated + NVD
- A daily job (`FS_NVD_SYNC_HOUR`) pulls Citrix CVEs from the NVD API into
  `advisories` as **review candidates** (`source=nvd`, `needsReview=true`) with no
  build predicate, so they do NOT auto-match until curated.
- Curate via `GET /api/admin/advisories?review_only=true` then
  `PATCH /api/admin/advisories/{id}` with `affected_below_build` (re-runs matching).
- Force a run: `POST /api/admin/sync-nvd`.

## Email digest
- A daily job (`FS_ALERT_HOUR`) emails upcoming cert/license expiries and current
  critical findings. Set `FS_SMTP_HOST` + `FS_ALERT_TO` to enable; otherwise it
  logs the digest. Force a run: `POST /api/admin/send-digest`.

## Database migrations (Alembic)
The app runs `alembic upgrade head` on startup, so a fresh DB is created and an
existing one is upgraded automatically — data survives schema changes.

When you change a model, generate a migration and review it before committing:
```bash
cd backend
FS_DATABASE_URL="sqlite:///./dev.db" alembic upgrade head          # get current
FS_DATABASE_URL="sqlite:///./dev.db" alembic revision --autogenerate -m "what changed"
# review migrations/versions/<new>.py, then it applies on next startup
```
SQLite ALTERs use Alembic batch mode (configured in `migrations/env.py`). When adding
a NOT NULL column to an existing table, give it a `server_default` — batch mode
recreates the table and copies the rows, which fails otherwise. Test upgrades against
a DB that already has rows, not only against an empty one.

## Legacy PowerShell collector (`collector/`)
Still works against `/api/ingest` (enrollment on first push) and is removed in phase 3
of `AGENT.md`. Do not extend it.
