#!/usr/bin/env bash
# Health-checks every component of the stack. Exit code = number of failed checks.
set -uo pipefail
G="http://${GRAFANA_ADMIN_USER:-admin}:${GRAFANA_ADMIN_PASSWORD:-admin}@localhost:3000"
FAIL=0
ok()   { echo "✅ $1"; }
bad()  { echo "❌ $1"; FAIL=$((FAIL+1)); }
warn() { echo "⚠️  $1"; }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }
promq() { curl -s -G http://localhost:9090/api/v1/query --data-urlencode "query=$1" | jq -e '.data.result | length > 0'; }
command -v jq >/dev/null || { echo "jq is required (brew install jq / apt install jq)"; exit 1; }

check "store-api /health"           curl -sf http://localhost:8000/health
check "inventory-service /health"   curl -sf http://localhost:8001/health
# Tempo's /ready only turns "ready" 15s after it is first polled, so retry for up to 30s
check "Tempo ready"                 bash -c 'for i in $(seq 1 15); do curl -sf http://localhost:3200/ready | grep -q ready && exit 0; sleep 2; done; exit 1'
check "Prometheus ready"            curl -sf http://localhost:9090/-/ready

TARGETS=$(curl -s http://localhost:9090/api/v1/targets)
for job in node store-api inventory-service tempo prometheus grafana; do
  h=$(echo "$TARGETS" | jq -r --arg j "$job" '.data.activeTargets[] | select(.labels.job==$j) | .health')
  [ "$h" = "up" ] && ok "Prometheus target $job up" || bad "Prometheus target $job ($h)"
done
h=$(echo "$TARGETS" | jq -r '.data.activeTargets[] | select(.labels.job=="cadvisor") | .health')
[ "$h" = "up" ] && ok "Prometheus target cadvisor up" || warn "cadvisor target $h (expected unless --profile full)"

check "App metrics in Prometheus"            promq 'sum(rate(http_requests_total[1m]))'
check "Tempo metrics-generator → Prometheus" promq 'traces_spanmetrics_calls_total'
check "Tempo service-graph metrics"          promq 'traces_service_graph_request_total'
check "Tempo search returns traces"          bash -c 'curl -s "http://localhost:3200/api/search?limit=5" | jq -e ".traces | length > 0"'
check "Grafana health"                       curl -sf "$G/api/health"
check "Grafana data sources (prometheus, tempo)" bash -c "curl -s '$G/api/datasources' | jq -e '[.[].uid] | index(\"prometheus\") != null and index(\"tempo\") != null'"
check "Grafana dashboards (3)"               bash -c "curl -s '$G/api/search?tag=devops-ia' | jq -e 'length == 3'"
check "Grafana alert rules (>= 6)"           bash -c "curl -s '$G/api/v1/provisioning/alert-rules' | jq -e 'length >= 6'"
check "Mailpit API"                          curl -sf http://localhost:8025/api/v1/messages

echo
[ $FAIL -eq 0 ] && echo "All checks passed." || echo "$FAIL check(s) failed. (Tempo metrics need ~1-2 min after startup.)"
exit $FAIL
