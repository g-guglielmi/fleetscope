# FleetScope

Central dashboard that inventories **Citrix farm components and versions** across
multiple MSP clients and sites, enriches them with known vulnerabilities/issues,
and tracks **Citrix license** and **certificate** (StoreFront / NetScaler) expiry.

## Architecture

```
  CLIENT A / Site 1     CLIENT A / Site 2      CLIENT B / Site 1
  ┌────────────┐        ┌────────────┐         ┌────────────┐
  │ Collector  │        │ Collector  │         │ Collector  │   PowerShell probe,
  │ (PS probe) │        │ (PS probe) │         │ (PS probe) │   scheduled task
  └─────┬──────┘        └─────┬──────┘         └─────┬──────┘
        │  HTTPS + shared ingest key (PUSH JSON, self-declares client) │
        └──────────────────────┬──────────────────────────────────────┘
                               ▼
                    your reverse proxy (TLS)
                               ▼
                 ┌─────────────────────────────┐
                 │  fs-app  (single container)  │
                 │  FastAPI: API + built React  │
                 │  UI + scheduler (NVD, email) │
                 │  SQLite on a bind mount       │
                 └─────────────────────────────┘
```

One container does everything (UI + API + jobs); data is a SQLite file on a host
bind mount under `/docker/fleetscope`. TLS is terminated by your existing proxy.

### Decisions
- **Push model, zero-touch onboarding**: each probe carries a shared **ingest key**
  and self-declares its **client**/**site**; the server auto-provisions them, so a
  new probe makes a new dashboard section appear automatically.
- **Single image**: the React SPA is built and served by the FastAPI app.
- **SQLite** on a bind mount — adequate for this scale, keeps it to one container.
- **No Docker Compose**: image built in GitHub Actions → GHCR, deployed with
  `deploy/deploy.sh` (one `docker run`, bind mounts, no named volumes).
- **TLS**: handled by your own reverse proxy in front of `APP_PORT`.
- **UI auth**: local accounts (v1), built pluggable so OIDC can be added later.
- **Vuln lookup**: build-number matching against a curated Citrix advisory table
  (CTX bulletins). A daily NVD sync adds review candidates (no auto-match until a
  build predicate is curated) — not pure NVD/CPE auto-matching.
- **Alerting**: daily email (SMTP) digest of upcoming cert/license expiries and criticals.
- **Access**: MSP staff only (no per-tenant client logins in v1).

## Repo layout
```
Dockerfile   single image: Node builds the SPA, FastAPI serves it + the API
backend/     FastAPI app (ingest, auth, overview, clients, admin, enrichment)
frontend/    React + Vite + Tailwind UI (built into the image)
collector/   PowerShell probe module + scheduled-task installer
deploy/      deploy.sh (docker run, bind mounts) + deploy.env.example
docs/        collector JSON contract + development guide
```

## Deploy (Debian VM with Docker)
```bash
cd deploy
cp deploy.env.example deploy.env   # set REGISTRY, secrets, FS_INGEST_KEY
./deploy.sh                        # runs fs-app on APP_PORT with a bind mount
```
Then point your reverse proxy at `http://127.0.0.1:${APP_PORT}` and put the same
`FS_INGEST_KEY` in each probe's `config.json`. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Status
v1. The probe→ingest→overview path is verified end to end (auto-provisioning,
advisory matching, cert/license expiry, email digest). Collector queries need
validating against live farms; advisory predicates need curating.
