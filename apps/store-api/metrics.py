"""Prometheus RED metrics recorded from Flask request hooks, with trace_id exemplars."""
import logging
import time

from flask import g, request
from opentelemetry import trace
from prometheus_client import Counter, Gauge, Histogram

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

REQUESTS = Counter("http_requests_total", "Total HTTP requests",
                   ["service", "method", "route", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency",
                    ["service", "method", "route"], buckets=BUCKETS)
INFLIGHT = Gauge("http_requests_in_progress", "In-flight HTTP requests", ["service"])

SKIP = ("/metrics", "/health")
log = logging.getLogger("request")


def register_metrics(app, service_name: str):
    @app.before_request
    def _start():
        if request.path.startswith(SKIP):
            return
        g._start = time.perf_counter()
        INFLIGHT.labels(service_name).inc()

    @app.after_request
    def _record(response):
        if request.path.startswith(SKIP) or not hasattr(g, "_start"):
            return response
        duration = time.perf_counter() - g._start
        route = request.url_rule.rule if request.url_rule else "unmatched"
        REQUESTS.labels(service_name, request.method, route, str(response.status_code)).inc()

        ctx = trace.get_current_span().get_span_context()
        trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        LATENCY.labels(service_name, request.method, route).observe(
            duration, exemplar={"trace_id": trace_id} if trace_id else None)
        log.info("%s %s %s %.1fms trace_id=%s", request.method, request.path,
                 response.status_code, duration * 1000, trace_id)
        return response

    @app.teardown_request
    def _end(_exc):
        if hasattr(g, "_start"):
            INFLIGHT.labels(service_name).dec()
