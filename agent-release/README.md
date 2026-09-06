# agent-release/

Populated by CI (`.github/workflows/build.yml`): `FleetScopeAgent.exe` (self-contained
single-file build of `agent/`) and the Ed25519-signed `release.json` describing it.
The Docker image copies this directory to `/app/agent`, from where the dashboard
serves `GET /api/agent/release` and `/api/agent/release/download`.

Locally this directory only holds this file, so those endpoints return 404 — as designed.
