#!/usr/bin/env bash
# Stop inventory-service: store-api returns 503, service map shows failures, 'Service Down' alert fires.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "▶ Stopping inventory-service"
docker compose stop inventory-service
echo "Watch: Service Health = DOWN, failed requests on the service map, 'Service Down' alert → email."
echo "Restore with ./scripts/chaos-restore.sh"
