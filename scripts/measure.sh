#!/usr/bin/env bash
# Collects the evaluation numbers for the report (guide section 13.3). Prints real, measured values.
# Usage: ./scripts/measure.sh [mttd_runs=3]     (MTTD_RUNS=0 skips the ~2-3 min/run alert timing)
set -uo pipefail
cd "$(dirname "$0")/.."
RUNS=${1:-3}
G="http://${GRAFANA_ADMIN_USER:-admin}:${GRAFANA_ADMIN_PASSWORD:-admin}@localhost:3000"
now() { python3 -c 'import time; print(f"{time.time():.2f}")'; }
promq() { curl -s -G http://localhost:9090/api/v1/query --data-urlencode "query=$1" | jq -r '.data.result[0].value[1] // "n/a"'; }
cpu_state() { curl -s "$G/api/prometheus/grafana/api/v1/rules" | jq -r '.data.groups[].rules[] | select(.name=="High CPU Usage") | .state'; }
cpu_mails() { curl -s "http://localhost:8025/api/v1/messages?limit=200" | jq '[.messages[] | select(.Subject | test("FIRING.*High CPU Usage"))] | length'; }

echo "=== 1. Resource footprint (docker stats) ==="
docker stats --no-stream $(docker compose ps -q) --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
docker stats --no-stream $(docker compose ps -q) --format "{{.MemUsage}}" | awk '{v=$1; u=v; gsub(/[0-9.]/,"",u); gsub(/[A-Za-z]/,"",v);
  if (u=="GiB") v*=1024; else if (u=="KiB") v/=1024; t+=v} END {printf "TOTAL stack RAM: %.0f MiB\n", t}'

echo; echo "=== 2. Tempo storage ==="
echo "Tempo container up since: $(docker inspect tempo --format '{{.State.StartedAt}}')"
docker exec tempo du -sh /var/tempo
echo "HTTP request rate (both services): $(promq 'sum(rate(http_requests_total{route!~"/chaos.*"}[5m]))') req/s"

echo; echo "=== 3. Prometheus ==="
echo "Head series: $(promq prometheus_tsdb_head_series)"
docker exec prometheus du -sh /prometheus

echo; echo "=== 4. Trace ingestion ==="
echo "Spans received/s: $(promq 'sum(rate(tempo_distributor_spans_received_total[1m]))')"

echo; echo "=== 5. Trace lookup by ID (5 recent traces) ==="
for id in $(curl -s "http://localhost:3200/api/search?limit=5" | jq -r '.traces[].traceID'); do
  curl -s -o /dev/null -w "%{time_total}\n" "http://localhost:3200/api/traces/$id"
done | awk '{s+=$1; printf "  %.1f ms\n", $1*1000} END {if (NR) printf "  avg %.1f ms\n", s/NR*1000}'

[ "$RUNS" -gt 0 ] || exit 0
echo; echo "=== 6. MTTD: CPU chaos → alert Firing → email (runs: $RUNS) ==="
for r in $(seq 1 "$RUNS"); do
  until [ "$(cpu_state)" = "inactive" ]; do sleep 2; done   # start from a clean state
  before=$(cpu_mails)
  T0=$(now); curl -sf -X POST "http://localhost:8000/chaos/cpu?seconds=300" >/dev/null
  until [ "$(cpu_state)" = "firing" ]; do sleep 1; done; T1=$(now)
  until [ "$(cpu_mails)" -gt "$before" ]; do sleep 1; done; T2=$(now)
  curl -s -X POST http://localhost:8000/chaos/reset >/dev/null   # also stops the CPU burners
  python3 -c "print(f'  run $r: firing after {$T1-$T0:.1f}s, email after {$T2-$T0:.1f}s')" | tee -a /tmp/mttd.$$
done
awk '{f+=$5; e+=$8} END {printf "  AVERAGE: firing %.1fs, email %.1fs\n", f/NR, e/NR}' /tmp/mttd.$$
rm -f /tmp/mttd.$$
