#!/usr/bin/env bash
# Inject extra latency into a service (default: inventory-service, so the slow span is downstream).
# Usage: ./scripts/chaos-latency.sh [ms=1500] [duration_s=120] [inventory|store]
set -euo pipefail
MS=${1:-1500}; DUR=${2:-120}; TARGET=${3:-inventory}
PORT=8001; [ "$TARGET" = "store" ] && PORT=8000
echo "▶ Injecting ${MS} ms latency into ${TARGET} (port ${PORT}) for ${DUR}s"
curl -sf -X POST "http://localhost:${PORT}/chaos/latency?ms=${MS}&duration=${DUR}"; echo
echo "Watch: Dashboard 02 p95 latency → click an exemplar dot → Tempo waterfall shows the slow span."
echo "Alert 'High p95 Latency' fires after ~30-60s → email at http://localhost:8025"
