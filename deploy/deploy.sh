#!/usr/bin/env bash
# FleetScope deployment — plain `docker run`, no Compose.
# Pulls images from GHCR and (re)starts the four containers on a shared network.
# Idempotent: re-run to update to a new TAG.
#
#   cp deploy.env.example deploy.env   # then edit deploy.env
#   ./deploy.sh
set -euo pipefail

cd "$(dirname "$0")"
[ -f deploy.env ] || { echo "Missing deploy.env (copy deploy.env.example)"; exit 1; }
set -a; source ./deploy.env; set +a

NET=fleetscope

docker network inspect "$NET"     >/dev/null 2>&1 || docker network create "$NET"
docker volume  inspect fs-pgdata  >/dev/null 2>&1 || docker volume  create fs-pgdata
docker volume  inspect fs-caddy   >/dev/null 2>&1 || docker volume  create fs-caddy

echo "==> Pulling images"
docker pull "$REGISTRY/backend:$TAG"
docker pull "$REGISTRY/frontend:$TAG"

echo "==> Postgres"
docker rm -f fs-db 2>/dev/null || true
docker run -d --name fs-db --restart unless-stopped --network "$NET" \
  -e POSTGRES_USER=farm \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  -e POSTGRES_DB=fleetscope \
  -v fs-pgdata:/var/lib/postgresql/data \
  postgres:16-alpine

echo "   waiting for Postgres..."
until docker exec fs-db pg_isready -U farm -d fleetscope >/dev/null 2>&1; do sleep 1; done

echo "==> Backend"
docker rm -f fs-backend 2>/dev/null || true
docker run -d --name fs-backend --restart unless-stopped --network "$NET" \
  -e FS_DATABASE_URL="postgresql+psycopg://farm:${POSTGRES_PASSWORD}@fs-db:5432/fleetscope" \
  -e FS_JWT_SECRET="$FS_JWT_SECRET" \
  -e FS_ADMIN_EMAIL="$FS_ADMIN_EMAIL" \
  -e FS_ADMIN_PASSWORD="$FS_ADMIN_PASSWORD" \
  -e FS_NVD_SYNC_ENABLED="${FS_NVD_SYNC_ENABLED:-true}" \
  -e FS_NVD_API_KEY="${FS_NVD_API_KEY:-}" \
  -e FS_SMTP_HOST="${FS_SMTP_HOST:-}" \
  -e FS_SMTP_PORT="${FS_SMTP_PORT:-587}" \
  -e FS_SMTP_STARTTLS="${FS_SMTP_STARTTLS:-true}" \
  -e FS_SMTP_USER="${FS_SMTP_USER:-}" \
  -e FS_SMTP_PASSWORD="${FS_SMTP_PASSWORD:-}" \
  -e FS_ALERT_FROM="${FS_ALERT_FROM:-fleetscope@localhost}" \
  -e FS_ALERT_TO="${FS_ALERT_TO:-}" \
  "$REGISTRY/backend:$TAG"

echo "==> Frontend"
docker rm -f fs-frontend 2>/dev/null || true
docker run -d --name fs-frontend --restart unless-stopped --network "$NET" \
  "$REGISTRY/frontend:$TAG"

echo "==> Caddy (auto-TLS)"
docker rm -f fs-caddy 2>/dev/null || true
docker run -d --name fs-caddy --restart unless-stopped --network "$NET" \
  -p 80:80 -p 443:443 \
  -v "$(pwd)/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v fs-caddy:/data \
  caddy:2

echo "==> Done."
docker ps --filter 'name=fs-' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
