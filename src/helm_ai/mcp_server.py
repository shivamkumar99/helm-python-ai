"""The Helm MCP server: the shared tool layer exposed over MCP stdio.

Run with ``helm-ai-mcp`` (or ``python -m helm_ai.mcp_server``) and register
it in any MCP client. Requires the ``server`` extra (``pip install
helm-python-ai[server]``).

Client feedback:

* Long-running tools (installs, upgrades, registry pulls) are async and
  report progress every few seconds — elapsed time plus the Helm SDK's own
  live log line — so the host can show activity instead of a stuck call.
* ``helm_list_releases`` ships an MCP Apps (SEP-1865) dashboard: hosts
  supporting the UI extension render the releases as a table; others see
  the JSON text unchanged.

Cluster writes stay dry-run only unless the process environment sets
``HELM_AI_ALLOW_WRITES=1``; uninstall/rollback additionally need
``HELM_AI_ALLOW_DESTRUCTIVE=1``. There is no interactive prompt over MCP,
so the environment is the only authorization channel here.
"""

from __future__ import annotations

from . import feedback, telemetry
from . import mcp_tools as _mcp_tools  # noqa: F401  (importing registers the tools)
from .mcp_app import mcp

__all__ = ["main", "mcp"]


def main() -> None:
    """Entry point for ``helm-ai-mcp``: serve over stdio."""
    telemetry.configure_telemetry("helm-ai-mcp")
    feedback.capture_native_logs()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
