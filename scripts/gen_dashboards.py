#!/usr/bin/env python3
"""Generate the three provisioned Grafana dashboards (grafana/dashboards/*.json).

Run after editing:  python3 scripts/gen_dashboards.py
Panel numbers match the tables in the implementation guide (sections 10.4 - 10.6);
alert rules link to panels by these ids.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"
PROM = {"type": "prometheus", "uid": "prometheus"}
TEMPO = {"type": "tempo", "uid": "tempo"}
NODE_NET = 'device!~"lo|veth.*|docker.*|br-.*"'
# Real disks only; also hides Docker Desktop VM pseudo-filesystems (virtiofs, fakeowner, fuse, ...)
FS = 'fstype!~"tmpfs|overlay|squashfs|erofs|fakeowner|selfowner|virtiofs.*|fuse.*"'
# "/" on a Linux host; Docker Desktop's VM has no "/" disk, its data disk is /var/lib/docker
ROOT = f'mountpoint=~"/|/var/lib/docker",{FS}'


def thresholds(*steps):
    """steps: (value, color) pairs after the green base."""
    return {"mode": "absolute",
            "steps": [{"color": "green", "value": None}] + [{"color": c, "value": v} for v, c in steps]}


PCT = thresholds((60, "yellow"), (80, "red"))


def q(expr, legend="", ref="A", instant=False, exemplar=False):
    return {"datasource": PROM, "refId": ref, "expr": expr, "legendFormat": legend,
            "instant": instant, "range": not instant, "exemplar": exemplar}


def traceql(query, ref="A", limit=20):
    return {"datasource": TEMPO, "refId": ref, "queryType": "traceql", "query": query,
            "limit": limit, "tableType": "traces"}


def panel(pid, title, ptype, x, y, w, h, targets, unit=None, thr=None, minmax=None,
          custom=None, overrides=None, options=None, mappings=None, ds=PROM, description=""):
    defaults = {}
    if unit:
        defaults["unit"] = unit
    if thr:
        defaults["thresholds"] = thr
    if minmax:
        for k, v in zip(("min", "max"), minmax):
            if v is not None:
                defaults[k] = v
    if custom:
        defaults["custom"] = custom
    if mappings:
        defaults["mappings"] = mappings
    return {"id": pid, "title": title, "type": ptype, "datasource": ds, "description": description,
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
            "options": options or {}}


def gauge(pid, title, x, expr, thr=PCT, w=4):
    return panel(pid, title, "gauge", x, 0, w, 6, [q(expr)], unit="percent", thr=thr, minmax=(0, 100),
                 options={"reduceOptions": {"calcs": ["lastNotNull"]}, "showThresholdMarkers": True})


def stat(pid, title, x, y, w, targets, unit="none", thr=None, **kw):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": kw.pop("color_mode", "value"),
            "graphMode": kw.pop("graph_mode", "none"), "textMode": "auto"}
    return panel(pid, title, "stat", x, y, w, 6, targets, unit=unit,
                 thr=thr or thresholds(), options=opts, **kw)


def ts(pid, title, x, y, w, targets, unit, stack=False, line_at=None, bars=False, overrides=None, h=8):
    custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 2, "fillOpacity": 60 if bars else 15,
              "showPoints": "never", "spanNulls": True,
              "stacking": {"mode": "normal" if stack or bars else "none", "group": "A"}}
    thr = None
    if line_at is not None:
        custom["thresholdsStyle"] = {"mode": "line"}
        thr = thresholds((line_at, "red"))
    return panel(pid, title, "timeseries", x, y, w, h, targets, unit=unit, thr=thr, custom=custom,
                 minmax=(0, None) if bars else None,
                 overrides=overrides,
                 options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                          "tooltip": {"mode": "multi", "sort": "desc"}})


def color_override(match, color, by="byName"):
    return {"matcher": {"id": by, "options": match},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}


def dashboard(uid, title, panels, description, templating=None):
    return {
        "uid": uid, "title": title, "description": description, "tags": ["devops-ia"],
        "schemaVersion": 41, "version": 1, "editable": True, "graphTooltip": 1,
        "refresh": "5s", "time": {"from": "now-15m", "to": "now"}, "timezone": "browser",
        "links": [{"type": "dashboards", "tags": ["devops-ia"], "asDropdown": False,
                   "includeVars": False, "keepTime": True, "title": "DevOps IA dashboards"}],
        "templating": {"list": templating or []}, "annotations": {"list": []},
        "panels": panels,
    }


# --------------------------------------------------------------------------- 1. System overview
CPU = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)'
MEM = "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100"
DISK = (f'max(100 - (node_filesystem_avail_bytes{{{ROOT}}} '
        f'/ node_filesystem_size_bytes{{{ROOT}}} * 100))')
CORES = "count(count by (cpu) (node_cpu_seconds_total))"

system = dashboard("system-overview", "01 - System Overview", description=(
    "Host CPU, memory, disk and network from Node Exporter (Prometheus)."), panels=[
    gauge(1, "CPU Usage", 0, CPU),
    gauge(2, "Memory Usage", 4, MEM),
    gauge(3, "Disk Usage (root disk)", 8, DISK, thr=thresholds((70, "yellow"), (90, "red"))),
    stat(4, "Uptime", 12, 0, 4, [q("time() - node_boot_time_seconds")], unit="s"),
    stat(5, "CPU Cores", 16, 0, 4, [q(CORES)]),
    stat(6, "Total RAM", 20, 0, 4, [q("node_memory_MemTotal_bytes")], unit="bytes"),
    ts(7, "CPU Usage Over Time by Mode", 0, 6, 12,
       [q(f'sum by (mode) (rate(node_cpu_seconds_total{{mode!="idle"}}[1m])) / scalar({CORES}) * 100', "{{mode}}")],
       "percent", stack=True, line_at=80),
    ts(8, "Memory Breakdown", 12, 6, 12, [
        q("node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes", "Used", "A"),
        q("node_memory_Cached_bytes", "Cached", "B"),
        q("node_memory_MemAvailable_bytes", "Available", "C")], "bytes"),
    ts(9, "Network Traffic", 0, 14, 12, [
        q(f"sum(rate(node_network_receive_bytes_total{{{NODE_NET}}}[1m]))", "Receive", "A"),
        q(f"sum(rate(node_network_transmit_bytes_total{{{NODE_NET}}}[1m]))", "Transmit", "B")], "Bps",
       overrides=[{"matcher": {"id": "byName", "options": "Transmit"},
                   "properties": [{"id": "custom.transform", "value": "negative-Y"}]}]),
    ts(10, "Disk I/O", 12, 14, 12, [
        q("sum(rate(node_disk_read_bytes_total[1m]))", "Read", "A"),
        q("sum(rate(node_disk_written_bytes_total[1m]))", "Write", "B")], "Bps"),
    ts(11, "System Load", 0, 22, 12, [
        q("node_load1", "1m", "A"), q("node_load5", "5m", "B"), q("node_load15", "15m", "C")], "none"),
    panel(12, "Filesystem Usage Table", "table", 12, 22, 12, 8,
          [{**q(f"100 - (node_filesystem_avail_bytes{{{FS}}} / node_filesystem_size_bytes{{{FS}}} * 100)",
                instant=True), "format": "table"}],
          unit="percent", thr=thresholds((70, "yellow"), (90, "red")), minmax=(0, 100),
          custom={"cellOptions": {"type": "gauge", "mode": "gradient"}},
          overrides=[{"matcher": {"id": "byName", "options": "Value"},
                      "properties": [{"id": "displayName", "value": "Used %"}]}]),
])
system["panels"][-1]["transformations"] = [
    {"id": "organize", "options": {"includeByName": {"mountpoint": True, "fstype": True, "device": True,
                                                     "Value": True}}}]

# --------------------------------------------------------------------------- 2. Application performance
S = 'service=~"$service"'
ERR = (f'100 * (sum(rate(http_requests_total{{{S},status=~"5.."}}[1m])) or vector(0)) '
       f'/ clamp_min(sum(rate(http_requests_total{{{S}}}[1m])), 0.001)')


def pct_latency(p, ref):
    return q(f"histogram_quantile({p}, sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[1m])))",
             f"p{int(p * 100)}", ref, exemplar=(p == 0.95))


app = dashboard("app-performance", "02 - Application Performance", description=(
    "RED metrics (Rate, Errors, Duration) of store-api and inventory-service, with exemplars to Tempo."),
    templating=[{
        "name": "service", "label": "Service", "type": "query", "datasource": PROM,
        "query": {"query": "label_values(http_requests_total, service)", "refId": "service"},
        "definition": "label_values(http_requests_total, service)", "refresh": 2,
        "multi": True, "includeAll": True, "allValue": ".*",
        "current": {"text": ["All"], "value": ["$__all"]}}],
    panels=[
    stat(1, "Service Health", 0, 0, 5, [q('up{job=~"store-api|inventory-service"}', "{{job}}")],
         thr=thresholds(), color_mode="background",
         mappings=[{"type": "value", "options": {"1": {"text": "UP", "color": "green"},
                                                 "0": {"text": "DOWN", "color": "red"}}}]),
    stat(2, "Request Rate", 5, 0, 5, [q(f"sum(rate(http_requests_total{{{S}}}[1m]))")], unit="reqps",
         graph_mode="area"),
    stat(3, "Error Rate", 10, 0, 5, [q(ERR)], unit="percent", thr=thresholds((1, "yellow"), (5, "red")),
         graph_mode="area"),
    stat(4, "p95 Latency", 15, 0, 5,
         [q(f"histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{S}}}[1m])))")],
         unit="s", thr=thresholds((0.5, "yellow"), (1, "red")), graph_mode="area"),
    panel(5, "In-flight Requests", "gauge", 20, 0, 4, 6, [q(f"sum(http_requests_in_progress{{{S}}})")],
          thr=thresholds((20, "yellow"), (40, "red")), minmax=(0, 50),
          options={"reduceOptions": {"calcs": ["lastNotNull"]}}),
    ts(6, "Requests per Second by Route", 0, 6, 12,
       [q(f"sum by (service, route) (rate(http_requests_total{{{S}}}[1m]))", "{{service}} {{route}}")], "reqps"),
    ts(7, "Responses by Status Code", 12, 6, 12,
       [q(f"sum by (status) (rate(http_requests_total{{{S}}}[1m]))", "{{status}}")], "reqps", bars=True,
       overrides=[color_override("/^2../", "green", "byRegexp"), color_override("/^4../", "orange", "byRegexp"),
                  color_override("/^5../", "red", "byRegexp")]),
    ts(8, "Latency Percentiles (with exemplars)", 0, 14, 12,
       [pct_latency(0.50, "A"), pct_latency(0.95, "B"), pct_latency(0.99, "C")], "s", line_at=1),
    ts(9, "Error Rate Over Time", 12, 14, 12, [q(ERR, "error %")], "percent", line_at=5),
    ts(10, "Latency by Route (p95)", 0, 22, 12,
       [q(f"histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket{{{S}}}[1m])))",
          "{{route}}")], "s"),
    ts(11, "Orders (business KPI, per minute)", 12, 22, 12,
       [q("sum by (result) (rate(orders_total[1m])) * 60", "{{result}}")], "none",
       overrides=[color_override("success", "green"), color_override("failed", "red")]),
    panel(12, "Inventory Stock", "bargauge", 0, 30, 12, 9, [q("inventory_stock_units", "{{product}}")],
          thr=thresholds((0, "blue")), minmax=(0, 1000),
          options={"orientation": "horizontal", "displayMode": "gradient",
                   "reduceOptions": {"calcs": ["lastNotNull"]}}),
    panel(13, "Active Chaos Experiments", "state-timeline", 12, 30, 12, 9,
          [q("chaos_active", "{{service}} {{type}}")], thr=thresholds((1, "red")),
          mappings=[{"type": "value", "options": {"0": {"text": "off", "color": "green"},
                                                  "1": {"text": "ACTIVE", "color": "red"}}}],
          options={"showValue": "never", "mergeValues": True, "legend": {"showLegend": False}}),
    {"id": 100, "type": "row", "title": "Containers (requires --profile full)", "collapsed": True,
     "gridPos": {"x": 0, "y": 39, "w": 24, "h": 1}, "panels": [
        ts(14, "Container CPU %", 0, 40, 12,
           [q('sum by (name) (rate(container_cpu_usage_seconds_total{name=~".+"}[1m])) * 100', "{{name}}")],
           "percent"),
        ts(15, "Container Memory", 12, 40, 12,
           [q('sum by (name) (container_memory_working_set_bytes{name=~".+"})', "{{name}}")], "bytes"),
     ]},
])

# --------------------------------------------------------------------------- 3. Traces & service map
SERVER = 'span_kind="SPAN_KIND_SERVER"'
HOW_TO = """### How to use this dashboard (Grafana Tempo)

* **Service map** is built by Tempo's *metrics-generator* (`traces_service_graph_*` metrics in Prometheus).
* Click any **Trace ID** in the tables to open the full trace waterfall (store-api &rarr; inventory-service).
* **Explore &rarr; Tempo &rarr; TraceQL**, e.g.
  `{ resource.service.name = "inventory-service" && duration > 1s }`
* On **02 - Application Performance**, hover the *Latency Percentiles* graph and click an
  **exemplar** dot &rarr; *Query with Tempo* to jump from a latency spike to the exact trace.
* Run `./scripts/chaos-latency.sh`, `chaos-errors.sh` or `chaos-kill-inventory.sh` to populate the slow/error tables.
"""


def trace_table(pid, title, x, y, w, query):
    return panel(pid, title, "table", x, y, w, 9, [traceql(query)], ds=TEMPO,
                 options={"showHeader": True, "cellHeight": "sm"})


traces = dashboard("traces-service-map", "03 - Traces & Service Map (Grafana Tempo)", description=(
    "Distributed traces stored in Grafana Tempo: service map, TraceQL searches, span metrics."), panels=[
    panel(1, "Service Map", "nodeGraph", 0, 0, 16, 12,
          [{"datasource": TEMPO, "refId": "A", "queryType": "serviceMap"}], ds=TEMPO),
    panel(10, "How to use", "text", 16, 0, 8, 12, [], ds=None,
          options={"mode": "markdown", "content": HOW_TO}),
    trace_table(2, "Recent Error Traces", 0, 12, 8, "{ status = error }"),
    trace_table(3, "Slow Traces (> 500 ms)", 8, 12, 8, "{ duration > 500ms }"),
    trace_table(4, "Checkout Traces", 16, 12, 8,
                '{ resource.service.name = "store-api" && name = "POST /api/checkout" }'),
    ts(5, "Span Rate by Service (from Tempo metrics-generator)", 0, 21, 12,
       [q(f"sum by (service) (rate(traces_spanmetrics_calls_total{{{SERVER}}}[1m]))", "{{service}}")], "reqps"),
    ts(6, "Span p95 Latency by Service", 12, 21, 12,
       [q(f"histogram_quantile(0.95, sum by (le, service) "
          f"(rate(traces_spanmetrics_latency_bucket{{{SERVER}}}[1m])))", "{{service}}")], "s"),
    ts(7, "Span Error Rate by Service", 0, 29, 8,
       [q('(sum by (service) (rate(traces_spanmetrics_calls_total{status_code="STATUS_CODE_ERROR"}[1m])) '
          'or sum by (service) (rate(traces_spanmetrics_calls_total[1m])) * 0) '
          '/ sum by (service) (rate(traces_spanmetrics_calls_total[1m])) * 100', "{{service}}")], "percent"),
    ts(8, "Service-to-Service Request Rate", 8, 29, 8,
       [q("sum by (client, server) (rate(traces_service_graph_request_total[1m]))", "{{client}} → {{server}}")],
       "reqps"),
    ts(9, "Service-to-Service Failed Requests", 16, 29, 8,
       [q("sum by (client, server) (rate(traces_service_graph_request_failed_total[1m]))",
          "{{client}} → {{server}}")], "reqps",
       overrides=[{"matcher": {"id": "byFrameRefID", "options": "A"},
                   "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}]),
])
traces["panels"][1].pop("datasource")

for name, d in [("01-system-overview", system), ("02-application-performance", app),
                ("03-traces-service-map", traces)]:
    (OUT / f"{name}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    print("wrote", name)
