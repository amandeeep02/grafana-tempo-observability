"""store-api: public-facing service. Calls inventory-service, so traces span two services."""
import os
import random
import time

import requests
from flask import Flask, jsonify, request
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from prometheus_client import Counter, make_wsgi_app
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from chaos import apply_latency, register_chaos
from metrics import register_metrics
from telemetry import init_tracing

SERVICE_NAME = os.getenv("SERVICE_NAME", "store-api")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://inventory-service:8001")
TIMEOUT = 2

ORDERS = Counter("orders_total", "Checkout attempts by result", ["result"])

app = Flask(__name__)
tracer = init_tracing(app, SERVICE_NAME)
register_metrics(app, SERVICE_NAME)
register_chaos(app, SERVICE_NAME)


def inventory_unavailable(exc):
    span = trace.get_current_span()
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, "inventory unavailable"))
    return jsonify({"error": "inventory unavailable"}), 503


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/")
def index():
    return {
        "service": SERVICE_NAME,
        "message": "DevOps IA-2 demo store (Grafana + Tempo)",
        "endpoints": ["GET /api/products", "POST /api/checkout", "POST /chaos/latency?ms=&duration=",
                      "POST /chaos/errors?rate=&duration=", "POST /chaos/cpu?seconds=",
                      "POST /chaos/reset", "GET /chaos/status", "GET /health", "GET /metrics"],
    }


@app.get("/api/products")
def products():
    try:
        resp = requests.get(f"{INVENTORY_URL}/inventory", timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return inventory_unavailable(exc)

    with tracer.start_as_current_span("products.enrich") as span:
        items = resp.json()
        span.set_attribute("products.count", len(items))
        time.sleep(random.uniform(0.010, 0.080))
        apply_latency()
    return jsonify(items)


@app.post("/api/checkout")
def checkout():
    body = request.get_json(silent=True) or {}
    item_id, qty = int(body.get("item_id", 1)), int(body.get("qty", 1))

    try:
        resp = requests.post(f"{INVENTORY_URL}/reserve", json={"item_id": item_id, "qty": qty}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        ORDERS.labels("failed").inc()
        return inventory_unavailable(exc)
    if resp.status_code != 200:
        ORDERS.labels("failed").inc()
        return jsonify(resp.json()), resp.status_code
    reservation = resp.json()

    with tracer.start_as_current_span("payment.process") as span:
        amount = round(reservation["price"] * qty, 2)
        span.set_attribute("payment.method", random.choice(["card", "upi", "netbanking"]))
        span.set_attribute("order.amount", amount)
        time.sleep(random.uniform(0.030, 0.150))
        apply_latency()
        if random.random() < 0.02:
            err = TimeoutError("payment gateway timeout")
            span.record_exception(err)
            span.set_status(Status(StatusCode.ERROR, str(err)))
            ORDERS.labels("failed").inc()
            return jsonify({"error": "payment gateway timeout"}), 502

    ORDERS.labels("success").inc()
    return jsonify({"status": "confirmed", "item_id": item_id, "qty": qty, "amount": amount})


# gunicorn entrypoint: /metrics via prometheus_client WSGI app (supports OpenMetrics -> exemplars)
application = DispatcherMiddleware(app, {"/metrics": make_wsgi_app()})
