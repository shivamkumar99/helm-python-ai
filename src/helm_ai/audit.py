"""Structured audit trail and per-tool observability.

Every meaningful action produces one JSON event carrying what happened,
when, how long it took, and — when OpenTelemetry is active — the trace
and span IDs, so audit records and traces cross-reference. Events go to
the ``helm_ai.audit`` logger (stderr under the fronts' logging setup) and,
when ``HELM_AI_AUDIT_LOG`` names a file, to that file as append-only
JSON lines.

The :func:`observed` decorator instruments a tool-layer function: one
span (via the OpenTelemetry API — a no-op unless a provider is
configured), one ``tool.call`` audit event with an allowlisted argument
snapshot, and counter/duration metrics. Argument values that may carry
secrets (values documents, kubeconfig content) are never recorded —
only their sizes.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, TypeVar

__all__ = ["emit", "observed"]

F = TypeVar("F", bound=Callable[..., Any])

AUDIT_LOG_ENV = "HELM_AI_AUDIT_LOG"

#: Argument names safe to record verbatim in audit events.
_SAFE_ARGS = frozenset(
    {
        "name",
        "namespace",
        "all_namespaces",
        "all_states",
        "all_values",
        "name_filter",
        "revision",
        "max_revisions",
        "chart_ref",
        "chart_path",
        "chart_repo_url",
        "chart_version",
        "repo_url",
        "oci_ref",
        "output_format",
        "version",
        "apply",
        "dry_run_mode",
        "confirm",
        "create_namespace",
        "keep_history",
        "reuse_values",
        "strict",
        "kube_version",
        "timeout",
    }
)
#: Arguments recorded as sizes only — their content may carry secrets.
_SIZED_ARGS = frozenset({"values", "values_json"})

_logger = logging.getLogger("helm_ai.audit")

_file_lock = threading.Lock()
_file_failed = False

# The OpenTelemetry API is a dependency of the mcp extra but not of the
# bare package; everything here degrades to plain logging without it.
try:
    from opentelemetry import metrics as _metrics
    from opentelemetry import trace as _trace
except ImportError:  # pragma: no cover - agent-only install without mcp
    _metrics = None  # type: ignore[assignment]
    _trace = None  # type: ignore[assignment]

if _metrics is not None:
    _meter = _metrics.get_meter("helm_ai")
    _calls_counter = _meter.create_counter(
        "helm_ai.tool.calls", description="Tool-layer invocations by tool and outcome"
    )
    _duration_histogram = _meter.create_histogram(
        "helm_ai.tool.duration", unit="ms", description="Tool-layer call duration"
    )
else:  # pragma: no cover
    _calls_counter = None
    _duration_histogram = None


def _trace_ids() -> dict[str, str]:
    if _trace is None:
        return {}
    context = _trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {}
    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
    }


def _write_file(line: str) -> None:
    global _file_failed
    path = os.environ.get(AUDIT_LOG_ENV)
    if not path or _file_failed:
        return
    try:
        with _file_lock, open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        _file_failed = True
        _logger.warning("audit file %s unwritable, disabling: %s", path, exc)


def emit(event: str, **fields: Any) -> None:
    """Record one audit event to the logger and the audit file."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
        **_trace_ids(),
        **fields,
    }
    line = json.dumps(record, default=str, separators=(",", ":"))
    _logger.info("%s", line)
    _write_file(line)


def _snapshot_args(
    fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Allowlisted view of a call's arguments for the audit record."""
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
    except TypeError:
        return {}
    snapshot: dict[str, Any] = {}
    for key, value in bound.arguments.items():
        if value is None or value == "":
            continue
        if key in _SAFE_ARGS:
            snapshot[key] = value
        elif key in _SIZED_ARGS:
            snapshot[f"{key}_bytes"] = len(str(value))
    return snapshot


def observed(fn: F) -> F:
    """Instrument a tool-layer function: span + audit event + metrics."""
    tool = fn.__name__

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        span_cm = (
            _trace.get_tracer("helm_ai").start_as_current_span(f"helm_ai.tools.{tool}")
            if _trace is not None
            else None
        )
        start = time.monotonic()
        outcome = "success"
        try:
            if span_cm is not None:
                with span_cm:
                    return fn(*args, **kwargs)
            return fn(*args, **kwargs)
        except Exception as exc:
            outcome = type(exc).__name__
            raise
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            emit(
                "tool.call",
                tool=tool,
                outcome=outcome,
                duration_ms=duration_ms,
                args=_snapshot_args(fn, args, kwargs),
            )
            if _calls_counter is not None and _duration_histogram is not None:
                attributes: Mapping[str, str] = {"tool": tool, "outcome": outcome}
                _calls_counter.add(1, attributes)
                _duration_histogram.record(duration_ms, attributes)

    return wrapper  # type: ignore[return-value]
