#!/usr/bin/env bash
# Make store-api return HTTP 500 for a fraction of /api/* requests.
# Usage: ./scripts/chaos-errors.sh [rate=0.4] [duration_s=120]
set -euo pipefail
RATE=${1:-0.4}; DUR=${2:-120}
echo "▶ store-api will fail ${RATE} of /api/* requests for ${DUR}s"
curl -sf -X POST "http://localhost:8000/chaos/errors?rate=${RATE}&duration=${DUR}"; echo
echo "Watch: Error Rate stat, 5xx bars, 'Recent Error Traces' table; alert 'High HTTP Error Rate' → email."
