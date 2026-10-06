"""inventory-service: downstream service with an in-memory product "database"."""
import os
import random
import threading
import time

from flask import Flask, jsonify, request
from prometheus_client import Gauge, make_wsgi_app
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from chaos import apply_latency, register_chaos
from metrics import register_metrics
from telemetry import init_tracing

SERVICE_NAME = os.getenv("SERVICE_NAME", "inventory-service")

STOCK = Gauge("inventory_stock_units", "Units in stock per product", ["product"])

NAMES = ["Laptop", "Mouse", "Keyboard", "Monitor", "Headphones",
         "Webcam", "USB Hub", "SSD 1TB", "Router", "Desk Lamp"]
PRICES = [65000, 799, 2499, 14999, 3999, 2999, 1299, 7499, 3499, 1199]
PRODUCTS = {i + 1: {"id": i + 1, "name": n, "price": p, "stock": random.randint(300, 1000)}
            for i, (n, p) in enumerate(zip(NAMES, PRICES))}
_lock = threading.Lock()  # gunicorn runs 8 threads

app = Flask(__name__)
tracer = init_tracing(app, SERVICE_NAME)
register_metrics(app, SERVICE_NAME)
register_chaos(app, SERVICE_NAME)

for p in PRODUCTS.values():
    STOCK.labels(p["name"]).set(p["stock"])


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/inventory")
def inventory():
    with tracer.start_as_current_span("db.query") as span:
        span.set_attribute("db.system", "in-memory")
        span.set_attribute("db.statement", "SELECT * FROM products")
        time.sleep(random.uniform(0.005, 0.040))
        apply_latency()
        with _lock:
            items = [dict(p) for p in PRODUCTS.values()]
    return jsonify(items)


@app.post("/reserve")
def reserve():
    body = request.get_json(silent=True) or {}
    item_id, qty = int(body.get("item_id", 0)), int(body.get("qty", 1))
    if item_id not in PRODUCTS:
        return jsonify({"error": f"unknown item {item_id}"}), 404

    with tracer.start_as_current_span("db.update") as span:
        span.set_attribute("db.system", "in-memory")
        span.set_attribute("db.statement", "UPDATE products SET stock = stock - ? WHERE id = ?")
        time.sleep(random.uniform(0.005, 0.030))
        apply_latency()
        with _lock:
            product = PRODUCTS[item_id]
            if qty > product["stock"]:
                return jsonify({"error": "insufficient stock", "stock": product["stock"]}), 409
            product["stock"] -= qty
            if product["stock"] == 0:
                product["stock"] = 1000  # restock so the demo runs forever
            STOCK.labels(product["name"]).set(product["stock"])
            result = dict(product)
    return jsonify(result)


application = DispatcherMiddleware(app, {"/metrics": make_wsgi_app()})
