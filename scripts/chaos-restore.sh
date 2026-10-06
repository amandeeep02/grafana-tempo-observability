#!/usr/bin/env bash
# Undo every chaos experiment.
set -uo pipefail
cd "$(dirname "$0")/.."
echo "▶ Starting inventory-service"
docker compose start inventory-service
for i in $(seq 1 30); do curl -sf http://localhost:8001/health >/dev/null && break; sleep 1; done
echo "▶ Resetting latency/error injection and stopping CPU burners"
curl -s -X POST http://localhost:8000/chaos/reset >/dev/null && echo "  store-api reset"
curl -s -X POST http://localhost:8001/chaos/reset >/dev/null && echo "  inventory-service reset"
echo "✅ Restored. 'Resolved' emails arrive in Mailpit within ~1 minute."
