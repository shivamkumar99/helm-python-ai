"""Limits, input validation, and cluster access for both tool tiers.

The ceilings here are the ones the OWASP guidance calls for: a bound on
what a model may hand us, a bound on what we hand back, and a bound on
how long a cluster operation may run before it is abandoned.
"""

from __future__ import annotations

import json
import os
from typing import Any

import helm_python as helm

Json = dict[str, Any]

#: Ceiling on install/upgrade wait time so a wedged rollout cannot hang the
#: serving process indefinitely (OWASP MCP guide: resource usage limits).
DEFAULT_TIMEOUT = 300

#: Ceiling on the size of a values document accepted from the model.
MAX_VALUES_BYTES = 1_000_000

#: Ceiling on tool output returned to the model; oversized results are
#: truncated with a marker rather than flooding the caller's context.
MAX_OUTPUT_CHARS = 200_000


def parse_values_json(values_json: str | None) -> Json | None:
    """Parse a model-supplied values document, strictly.

    Raises:
        ValueError: when the payload is oversized, malformed, or not a
            JSON object.
    """
    if not values_json:
        return None
    if len(values_json.encode("utf-8", "ignore")) > MAX_VALUES_BYTES:
        raise ValueError(f"values_json exceeds {MAX_VALUES_BYTES} bytes")
    try:
        parsed = json.loads(values_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"values_json is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("values_json must be a JSON object")
    return parsed


def ensure_values_size(values: Json | None) -> Json | None:
    """Enforce the values-size ceiling on an already-parsed document."""
    if values is not None and len(json.dumps(values).encode()) > MAX_VALUES_BYTES:
        raise ValueError(f"values document exceeds {MAX_VALUES_BYTES} bytes")
    return values


def clamp_output(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate oversized tool output, marking the truncation explicitly."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated: {len(text) - limit} characters omitted]"


def config(namespace: str | None = None) -> helm.Config:
    return helm.Config(
        namespace=namespace,
        storage_driver=os.environ.get("HELM_AI_STORAGE_DRIVER"),
    )
