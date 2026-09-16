"""Vendor-neutral OpenTelemetry wiring for both fronts.

:func:`configure_telemetry` is a no-op unless a standard OTLP endpoint
variable is set (``OTEL_EXPORTER_OTLP_ENDPOINT`` or its traces-specific
sibling), so regular users pay nothing. With an endpoint and the
``observability`` extra installed, it stands up trace and metric
providers exporting over OTLP/HTTP; every span the MCP SDK already emits
per message, the tool-layer spans from :mod:`helm_ai.audit`, and the
agent's ``invoke_agent`` spans then flow to whatever backend the
endpoint names. Backend choice stays entirely outside this codebase.
"""

from __future__ import annotations

import logging
import os

__all__ = ["configure_telemetry"]

_ENDPOINT_ENVS = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
)

_logger = logging.getLogger(__name__)
_configured = False


def configure_telemetry(service_name: str) -> bool:
    """Set up OTLP export when configured; returns whether export is live.

    Args:
        service_name: default OTel service name (``OTEL_SERVICE_NAME``
            overrides it, per the standard environment contract).
    """
    global _configured
    if _configured:
        return True
    if not any(os.environ.get(var) for var in _ENDPOINT_ENVS):
        return False

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        _logger.warning(
            "an OTLP endpoint is set but the OpenTelemetry SDK is missing; "
            "install helm-python-ai[observability] to export telemetry"
        )
        return False

    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", service_name)})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    metrics.set_meter_provider(meter_provider)
    _configured = True
    _logger.info("telemetry export enabled for %s", service_name)
    return True
