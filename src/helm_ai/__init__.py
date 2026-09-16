"""helm-python-ai — the AI layer over helm-python-sdk.

Two fronts share one safety-tiered tool layer (:mod:`helm_ai.tools`):

* ``helm-ai-mcp`` — an MCP server exposing Helm operations to any MCP
  client (Claude Code, Claude Desktop, ...).
* ``helm-ai-agent`` — an autonomous Claude agent that investigates and
  operates Helm releases from a plain-language mission.
"""

from __future__ import annotations

from . import safety, tools
from .safety import SafetyError

__version__ = "0.1.0"

__all__ = ["SafetyError", "__version__", "safety", "tools"]
