# Development

## Backend (FastAPI + SQLite)

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate    # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- API docs at http://localhost:8000/docs
- SQLite file `fleetscope.db` is created in the working dir (override with `FS_DATABASE_URL`).
- On first start it creates tables, an admin user (`FS_ADMIN_EMAIL` / `FS_ADMIN_PASSWORD`,
  default `admin@local` / `changeme`), and a starter advisory set.
- `TZ` (e.g. `Europe/Rome`) sets the timezone for the scheduled NVD sync and digest.

## Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8000
```

In the Docker image the SPA is built and served by the backend at `/`, so there is
no separate frontend server in production.

## End-to-end smoke test

1. Log in and create a client — this returns a temporary **enrollment token**:
   ```bash
   TOKEN=$(curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' \
     -d '{"email":"admin@local","password":"changeme"}' | jq -r .access_token)
   ENR=$(curl -s localhost:8000/api/admin/clients -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"name":"ACME Corp"}' | jq -r .enrollment.token)
   ```
2. Enroll a probe with it — the response's `collectorToken` is the permanent token:
   ```bash
   curl -s localhost:8000/api/ingest -H "Authorization: Bearer $ENR" \
     -H 'Content-Type: application/json' -d '{
       "site":"Milan DC1","probe":"DDC01","collectedAt":"2026-09-03T10:00:00Z",
       "components":[{"type":"netscaler","hostname":"ns01","build":"13.1-30.0"}]
     }'
   ```
3. `curl -s localhost:8000/api/overview -H "Authorization: Bearer $TOKEN"` — the
   `ACME Corp` card appears with an open finding (the old NetScaler build matches the
   seeded CitrixBleed advisory). A second probe enrolled with the same token adds a
   new site under ACME automatically.

## Collector (management VM, remote mode)

One probe per site runs on a **management VM** as a **domain service account** and
reaches everything remotely — nothing is network-scanned:

- **Controllers / VDAs / hypervisor connections** — Citrix **Remote PowerShell SDK**
  pointed at a DDC (`-AdminAddress`); enumerates the whole site.
- **StoreFront** (version, OS, IIS certs) — PowerShell Remoting (WinRM) per server.
- **License** pools — remote CIM (WinRM) per server.
- **NetScaler** — NITRO REST with its own credentials.

Prerequisites on the management VM / account:
- Install the free **Citrix Remote PowerShell SDK**.
- The service account needs Citrix **Read Only Administrator** (delegated admin) and
  **WinRM/CIM** rights on the StoreFront and license servers. A **gMSA** is ideal.

Configure `collector/config.json` (from `config.example.json`): `dashboardUrl`, the
enrollment `token`, `client`/`site`, the `citrix.deliveryControllers`,
`storefrontServers`, `licenseServers`, and any `netscalers`. Then install:
```powershell
.\collector\Install-Collector.ps1 -ServiceAccount 'CONTOSO\svc-fleetscope$'
```
or run once by hand:
```powershell
Import-Module .\collector\FleetScopeCollector.psm1
Invoke-FleetScopeCollection -ConfigPath .\collector\config.json
```
Unreachable or misconfigured targets log a WARN and are skipped; the probe still
pushes what it could collect.

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
SQLite ALTERs use Alembic batch mode (configured in `migrations/env.py`).

## Notes / TODO
- Enrollment tokens are reusable within their window; tighten to single-use if needed.
- Build out hypervisor **version** collection (PowerCLI / Hyper-V), config-driven per host.
- Add OIDC to the pluggable auth layer when needed.
