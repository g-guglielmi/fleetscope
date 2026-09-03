# Development

## Backend (FastAPI)

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate    # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Point at a local Postgres (or run one in Docker):
#   docker run -d --name fs-db -e POSTGRES_USER=farm -e POSTGRES_PASSWORD=farm \
#     -e POSTGRES_DB=fleetscope -p 5432:5432 postgres:16-alpine
uvicorn app.main:app --reload
```

- API docs at http://localhost:8000/docs
- On first start it creates tables, an admin user (`FS_ADMIN_EMAIL` / `FS_ADMIN_PASSWORD`,
  default `admin@local` / `changeme`), and a starter advisory set.

## Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8000
```

## End-to-end smoke test

1. Log in via the API and grab a JWT:
   ```bash
   curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' \
     -d '{"email":"admin@local","password":"changeme"}'
   ```
2. Enroll a client → site → collector (returns the collector token **once**):
   ```bash
   TOKEN=<jwt>
   curl -s localhost:8000/api/admin/clients -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"slug":"acme","name":"ACME Corp"}'
   curl -s localhost:8000/api/admin/clients/acme/sites -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"slug":"milan-dc1","name":"Milan DC1"}'
   curl -s localhost:8000/api/admin/clients/acme/sites/milan-dc1/collectors \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name":"dc1-collector"}'
   ```
3. Point `collector/config.json` at the dashboard with that collector token and run:
   ```powershell
   Import-Module .\collector\FleetScopeCollector.psm1
   Invoke-FleetScopeCollection -ConfigPath .\collector\config.json
   ```
4. Open the UI, sign in, and the client card appears on the Overview with live data.

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

## Notes / TODO
- Swap `Base.metadata.create_all` for **Alembic** migrations before production.
- Harden collector secrets (NetScaler/hypervisor) from env vars to a DPAPI-encrypted config.
- Build out hypervisor **version** collection (PowerCLI / Hyper-V), config-driven per host.
- Add OIDC to the pluggable auth layer when needed.
