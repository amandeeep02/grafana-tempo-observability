#!/usr/bin/env bash
# Burn every CPU core of the (Docker) host from inside store-api.
# Usage: ./scripts/chaos-cpu.sh [seconds=120]   (max 300)
set -euo pipefail
SECS=${1:-120}
echo "▶ Burning all CPU cores for ${SECS}s"
curl -sf -X POST "http://localhost:8000/chaos/cpu?seconds=${SECS}"; echo
echo "Watch: CPU gauge turns red; alert 'High CPU Usage' Pending → Firing (>80% for 30s) → email at http://localhost:8025"
