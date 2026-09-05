# FleetScope

Central dashboard that inventories **Citrix farm components and versions** across
multiple MSP clients and sites, enriches them with known vulnerabilities/issues,
and tracks **Citrix license** and **certificate** (StoreFront / NetScaler) expiry.

## Architecture

```
  CLIENT A / Site 1        CLIENT A / Site 2         CLIENT B / Site 1
  ┌───────────────┐        ┌───────────────┐         ┌───────────────┐
  │ FleetScope    │        │ FleetScope    │         │ FleetScope    │   .NET Windows service on a
  │ Agent         │        │ Agent         │         │ Agent         │   management VM; runs signed
  │ + PS checks   │        │ + PS checks   │         │ + PS checks   │   PowerShell check modules
  └──────┬────────┘        └──────┬────────┘         └──────┬────────┘
         │  HTTPS, outbound only: check-in (config, manifest, credentials) · ingest results
         └──────────────────────────┬───────────────────────────┘
                                    ▼
                         your reverse proxy (TLS)
                                    ▼
                      ┌──────────────────────────────┐
                      │  fs-app  (single container)   │
                      │  FastAPI API + built React UI │
                      │  check modules + agent binary │
                      │  scheduler (NVD, email)       │
                      │  SQLite on a bind mount        │
                      └──────────────────────────────┘
```

One container does everything; data is a SQLite file on a host bind mount under
`/docker/fleetscope`. TLS is terminated by your existing proxy. Full design and
roadmap: [docs/AGENT.md](docs/AGENT.md).

### Decisions
- **Server-managed agents.** The agent holds only its token and an encrypted cache.
  Targets, enabled checks, cadence, the Windows service account and device
  credentials are all configured in the dashboard and pulled at each check-in.
  New monitors are check modules shipped inside the image — no site visits.
- **Enrollment**: the dashboard generates a one-line install command with a
  temporary, time-boxed enrollment token; the agent enrolls and receives its own
  permanent per-agent token scoped to its site.
- **Signed code**: check manifests and agent releases are Ed25519-signed in CI with
  your own key; agents pin the public key at install and refuse anything else.
- **Credentials**: AES-256-GCM at rest under `FS_SECRETS_KEY`, write-only in the UI,
  delivered only to the agents whose site references them, audited. Use read-only
  device accounts and monitoring-grade Windows accounts.
- **Roles**: `admin` / `viewer`; no default passwords in production; forced first-login
  password change; audit log.
- **Single image, SQLite, no Compose**: built in GitHub Actions → GHCR, deployed with
  `deploy/deploy.sh` (one `docker run`, bind mounts, no named volumes).
- **Vuln lookup**: build-number matching against a curated Citrix advisory table
  (CTX bulletins). A daily NVD sync adds review candidates (no auto-match until a
  build predicate is curated).
- **Alerting**: daily email (SMTP) digest of upcoming cert/license expiries and criticals.

## Repo layout
```
Dockerfile   single image: Node builds the SPA, FastAPI serves it + the API + checks
backend/     FastAPI app (agent API, ingest, auth/users, credentials, site config, admin)
frontend/    React + Vite + Tailwind UI (built into the image)
checks/      PowerShell 5.1 check modules served to agents (manifest signed in CI)
tools/sign/  Ed25519 key generation + manifest/release signing (used by CI)
collector/   LEGACY PowerShell probe — superseded by the agent, removed in phase 3
deploy/      deploy.sh (docker run, bind mounts) + deploy.env.example
docs/        AGENT.md (design), COLLECTOR_CONTRACT.md (payload), DEVELOPMENT.md
```

## Deploy (Debian VM with Docker)
```bash
python tools/sign/sign.py keygen   # FS_SIGNING_KEY -> GitHub secret; PUBKEY + SECRETS_KEY -> deploy.env
cd deploy
cp deploy.env.example deploy.env   # set secrets, FS_PUBLIC_URL, TZ (default Europe/Rome)
./deploy.sh                        # runs fs-app on APP_PORT with a bind mount
```
Then point your reverse proxy at `http://127.0.0.1:${APP_PORT}`. The container refuses
to start with default secrets. Onboarding a client is done entirely in the UI: add the
client → its sites and credentials → configure each site → generate the agent install
command. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Status
Phase 1 of [docs/AGENT.md](docs/AGENT.md) (dashboard side) is complete: users/roles,
credentials, site configuration, the agent API, four check modules with a signed
manifest, install-command generation, audit log. Phase 2 (the Windows agent itself)
is next; until then the legacy PowerShell collector still pushes to `/api/ingest`.
Check modules still need validating against a live farm; advisory predicates need
curating.
