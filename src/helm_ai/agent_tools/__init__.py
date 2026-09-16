"""The tools the agent may call, grouped by what they can do.

Read tools are ungated; write tools pass through the safety gates and
default to dry runs. :data:`TOOLS` is the full roster handed to the
model, read tier first so the cheapest, safest options are listed before
anything that can change a cluster.
"""

from __future__ import annotations

from typing import Any

from .read import READ_TOOLS
from .write import WRITE_TOOLS

__all__ = ["READ_TOOLS", "TOOLS", "WRITE_TOOLS"]

TOOLS: list[Any] = [*READ_TOOLS, *WRITE_TOOLS]
