"""Shared plumbing for the agent's tool functions.

Every tool returns a string to the model, so a failure has to come back
as readable text rather than an exception: :func:`guard` does that once
instead of each tool repeating the same try/except.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Any, TypeVar

import helm_python as helm

from .. import safety, tools

__all__ = ["CAUGHT", "as_json", "guard"]

F = TypeVar("F", bound=Callable[..., str])

#: Failures that are part of normal operation: a chart that will not load,
#: a refused gate, a malformed values document, an unreachable cluster.
#: The model can act on these, so they are reported, not raised.
CAUGHT = (helm.HelmError, safety.SafetyError, ValueError, OSError)


def as_json(value: Any) -> str:
    """Render a tool result for the model, bounded in size."""
    return tools.clamp_output(json.dumps(value, indent=2, default=str))


def guard(fn: F) -> F:
    """Return anticipated failures as text the model can read and act on."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except CAUGHT as exc:
            return f"ERROR ({type(exc).__name__}): {exc}"

    return wrapper  # type: ignore[return-value]
