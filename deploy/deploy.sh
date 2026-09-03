#!/usr/bin/env bash
# FleetScope deployment — one container, SQLite on a bind mount, no Compose.
# TLS is handled by your existing reverse proxy in front of APP_PORT.
# Idempotent: re-run to update to a new TAG.
#
#   cp deploy.env.example deploy.env   # then edit deploy.env
#   ./deploy.sh
set -euo pipefail

cd "$(dirname "$0")"
[ -f deploy.env ] || { echo "Missing deploy.env (copy deploy.env.example)"; exit 1; }
set -a; source ./deploy.env; set +a

DATA_DIR=/docker/fleetscope/db
mkdir -p "$DATA_DIR"

echo "==> Pulling image"
docker pull "$REGISTRY/app:$TAG"

echo "==> App (UI + API + SQLite)"
docker rm -f fs-app 2>/dev/null || true
docker run -d --name fs-app --restart unless-stopped \
  -p "${APP_PORT:-8080}:8000" \
  -v "$DATA_DIR:/data" \
  -e TZ="${TZ:-Europe/Rome}" \
  -e FS_DATABASE_URL="sqlite:////data/fleetscope.db" \
  -e FS_JWT_SECRET="$FS_JWT_SECRET" \
  -e FS_ADMIN_EMAIL="$FS_ADMIN_EMAIL" \
  -e FS_ADMIN_PASSWORD="$FS_ADMIN_PASSWORD" \
  -e FS_ENROLLMENT_TTL_HOURS="${FS_ENROLLMENT_TTL_HOURS:-24}" \
  -e FS_NVD_SYNC_ENABLED="${FS_NVD_SYNC_ENABLED:-true}" \
  -e FS_NVD_API_KEY="${FS_NVD_API_KEY:-}" \
  -e FS_SMTP_HOST="${FS_SMTP_HOST:-}" \
  -e FS_SMTP_PORT="${FS_SMTP_PORT:-587}" \
  -e FS_SMTP_STARTTLS="${FS_SMTP_STARTTLS:-true}" \
  -e FS_SMTP_USER="${FS_SMTP_USER:-}" \
  -e FS_SMTP_PASSWORD="${FS_SMTP_PASSWORD:-}" \
  -e FS_ALERT_FROM="${FS_ALERT_FROM:-fleetscope@localhost}" \
  -e FS_ALERT_TO="${FS_ALERT_TO:-}" \
  "$REGISTRY/app:$TAG"

echo "==> Done. Point your reverse proxy at http://127.0.0.1:${APP_PORT:-8080}"
docker ps --filter 'name=fs-app' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
