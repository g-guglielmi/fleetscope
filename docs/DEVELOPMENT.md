# Development

## Backend (FastAPI + SQLite)

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate    # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
FS_INGEST_KEY=devkey uvicorn app.main:app --reload
```

- API docs at http://localhost:8000/docs
- SQLite file `fleetscope.db` is created in the working dir (override with `FS_DATABASE_URL`).
- On first start it creates tables, an admin user (`FS_ADMIN_EMAIL` / `FS_ADMIN_PASSWORD`,
  default `admin@local` / `changeme`), and a starter advisory set.
- Set `FS_INGEST_KEY` or ingest returns 503.

## Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8000
```

In the Docker image the SPA is built and served by the backend at `/`, so there is
no separate frontend server in production.

## End-to-end smoke test

Probes **self-register** — no enrollment step. Just push with the shared ingest key
and the client/site appear automatically.

1. Push a snapshot (auto-creates client "ACME Corp" / site "Milan DC1"):
   ```bash
   curl -s localhost:8000/api/ingest -H "Authorization: Bearer devkey" \
     -H 'Content-Type: application/json' -d '{
       "client":"ACME Corp","site":"Milan DC1","probe":"DDC01",
       "collectedAt":"2026-09-03T10:00:00Z",
       "components":[{"type":"netscaler","hostname":"ns01","build":"13.1-30.0"}]
     }'
   ```
2. Log in and view the overview:
   ```bash
   TOKEN=$(curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' \
     -d '{"email":"admin@local","password":"changeme"}' | jq -r .access_token)
   curl -s localhost:8000/api/overview -H "Authorization: Bearer $TOKEN"
   ```
   The `ACME Corp` card appears with an open finding (the old NetScaler build matches
   the seeded CitrixBleed advisory).
3. In the real UI, sign in and the section is there. Push again with a different
   `client` and a new section appears — that is the auto-adapt behaviour.

To run a probe against a real farm: fill `collector/config.json` (from
`config.example.json`) with `dashboardUrl`, the shared `ingestKey`, and the
`client`/`site` names, then:
```powershell
Import-Module .\collector\FleetScopeCollector.psm1
Invoke-FleetScopeCollection -ConfigPath .\collector\config.json
```

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
- Shared ingest key trades per-probe scoping for zero-touch onboarding; move to
  per-probe keys if that trade stops being acceptable.
- Build out hypervisor **version** collection (PowerCLI / Hyper-V), config-driven per host.
- Add OIDC to the pluggable auth layer when needed.
