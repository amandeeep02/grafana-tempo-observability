"""OpenTelemetry tracing setup: spans are exported over OTLP gRPC to Grafana Tempo."""
import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def init_tracing(app, service_name: str):
    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "devops-ia",
        "deployment.environment": "demo",
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://tempo:4317"),
        insecure=True,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FlaskInstrumentor().instrument_app(app, excluded_urls="metrics,health")
    RequestsInstrumentor().instrument()  # injects W3C traceparent into outgoing calls
    return trace.get_tracer(service_name)
