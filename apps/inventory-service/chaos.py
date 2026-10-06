"""Fault injection (latency, errors, CPU burn) used to drive the demo scenarios."""
import os
import random
import subprocess
import sys
import threading
import time

from flask import Blueprint, jsonify, request
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from prometheus_client import Gauge

CHAOS_ACTIVE = Gauge("chaos_active", "1 while a chaos experiment is active", ["service", "type"])

# type -> {"until": epoch seconds, ...settings}
_state = {"latency": {"until": 0, "ms": 0}, "errors": {"until": 0, "rate": 0.0}, "cpu": {"until": 0}}
_burners = []  # running CPU burn processes, terminated by /chaos/reset

BURN = "import time\ne=time.time()+{s}\nwhile time.time()<e: pass"
EXEMPT = ("/chaos", "/metrics", "/health")


def _remaining(kind):
    return max(0, round(_state[kind]["until"] - time.time()))


def apply_latency():
    """Call inside a business span so the injected delay shows up on that span in Tempo."""
    if _remaining("latency"):
        time.sleep(_state["latency"]["ms"] / 1000)


def burn_cpu(seconds: int):
    n = os.cpu_count() or 2
    for _ in range(n):
        p = subprocess.Popen([sys.executable, "-c", BURN.format(s=int(seconds))])
        _burners.append(p)
        threading.Thread(target=p.wait, daemon=True).start()  # reap, no zombies
    return n


def register_chaos(app, service_name: str):
    for kind in _state:
        CHAOS_ACTIVE.labels(service_name, kind).set_function(lambda k=kind: 1 if _remaining(k) else 0)

    bp = Blueprint("chaos", __name__, url_prefix="/chaos")

    def _duration():
        return min(max(int(request.args.get("duration", 120)), 1), 3600)

    @bp.post("/latency")
    def latency():
        _state["latency"] = {"until": time.time() + _duration(), "ms": max(0, int(request.args.get("ms", 1500)))}
        return jsonify(status())

    @bp.post("/errors")
    def errors():
        rate = min(max(float(request.args.get("rate", 0.5)), 0.0), 1.0)
        _state["errors"] = {"until": time.time() + _duration(), "rate": rate}
        return jsonify(status())

    @bp.post("/cpu")
    def cpu():
        seconds = min(max(int(request.args.get("seconds", 90)), 1), 300)
        _state["cpu"] = {"until": time.time() + seconds}
        return jsonify({"burning_cores": burn_cpu(seconds), "seconds": seconds})

    @bp.post("/reset")
    def reset():
        _state["latency"]["until"] = 0
        _state["errors"]["until"] = 0
        _state["cpu"]["until"] = 0
        while _burners:
            p = _burners.pop()
            if p.poll() is None:
                p.terminate()
        return jsonify(status())

    @bp.get("/status")
    def status():
        return {
            "service": service_name,
            "latency": {"active": bool(_remaining("latency")), "ms": _state["latency"]["ms"],
                        "remaining_s": _remaining("latency")},
            "errors": {"active": bool(_remaining("errors")), "rate": _state["errors"]["rate"],
                       "remaining_s": _remaining("errors")},
            "cpu": {"active": bool(_remaining("cpu")), "remaining_s": _remaining("cpu")},
        }

    app.register_blueprint(bp)

    @app.before_request
    def _inject_errors():
        if request.path == "/" or request.path.startswith(EXEMPT):
            return None
        if _remaining("errors") and random.random() < _state["errors"]["rate"]:
            err = RuntimeError("chaos: injected internal error")
            span = trace.get_current_span()
            span.record_exception(err)
            span.set_status(Status(StatusCode.ERROR, str(err)))
            return jsonify({"error": str(err)}), 500
        return None
