# FleetScope

Central dashboard that inventories **Citrix farm components and versions** across
multiple MSP clients and sites, enriches them with known vulnerabilities/issues,
and tracks **Citrix license** and **certificate** (StoreFront / NetScaler) expiry.

## Architecture

```
  CLIENT A / Site 1     CLIENT A / Site 2      CLIENT B / Site 1
  ┌────────────┐        ┌────────────┐         ┌────────────┐
  │ Collector  │        │ Collector  │         │ Collector  │   PowerShell,
  │ (PS module)│        │ (PS module)│         │ (PS module)│   scheduled task
  └─────┬──────┘        └─────┬──────┘         └─────┬──────┘
        │  HTTPS + per-collector bearer token (PUSH JSON)      │
        └──────────────────────┬──────────────────────────────┘
                               ▼
                        ┌──────────────┐
                        │    Caddy     │  auto-TLS reverse proxy
                        └──────┬───────┘
                    ┌──────────┴──────────┐
                    ▼                     ▼
             ┌────────────┐        ┌────────────┐
             │  backend   │        │  frontend  │
             │ (FastAPI)  │        │ (React)    │
             └─────┬──────┘        └────────────┘
                   ▼
             ┌────────────┐
             │  Postgres  │  raw JSONB snapshots + derived typed tables
             └────────────┘
```

### Decisions
- **Push model**: collectors reach out to an internet-facing dashboard; nothing inbound to client networks.
- **Central multi-tenant**: one dashboard, per-client data isolation. Overview tab + per-client sections.
- **No Docker Compose**: images built in GitHub Actions → GHCR, deployed with `deploy/deploy.sh` (plain `docker run` on a shared network).
- **Collector auth**: per-collector tokens, stored **hashed**, scoped to one client/site, ingest is **write-only**.
- **UI auth**: local accounts (v1), built pluggable so OIDC can be added later.
- **Vuln lookup**: build-number matching against a curated Citrix advisory table (CTX bulletins). A daily NVD sync adds review candidates (no auto-match until a build predicate is curated) — not pure NVD/CPE auto-matching.
- **Alerting**: daily email (SMTP) digest of upcoming cert/license expiries and critical findings.
- **Access**: MSP staff only (no per-tenant client logins in v1).

## Repo layout
```
backend/     FastAPI app (ingest, auth, overview, clients, enrichment)
frontend/    React + Vite + Tailwind UI
collector/   PowerShell collector module + installer
deploy/      deploy.sh + Caddyfile (no compose)
.github/     GHCR build workflow
docs/        collector JSON contract + notes
```

## Quick start (local dev)
See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). In short: run Postgres, `uvicorn app.main:app` in `backend/`, `npm run dev` in `frontend/`, and point a collector at `http://localhost:8000`.

## Status
Scaffold / v1 skeleton. The collector→ingest→overview path works end-to-end for OS,
Citrix controller/VDA, StoreFront, NetScaler, license, and certificate data.
