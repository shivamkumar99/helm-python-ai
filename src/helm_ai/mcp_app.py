"""The server object and everything the tool modules build on.

Kept apart from the tools themselves because order matters: the MCP Apps
dashboard has to be registered on the extension *before* the server is
constructed with it, so the extension, that one tool, and the server are
created here, and :mod:`helm_ai.mcp_tools` attaches the rest afterwards.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from mcp.server.apps import Apps
    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
    from mcp.server.mcpserver import Context, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "the MCP server needs the 'mcp' package (2.x): pip install helm-python-ai[server]"
    ) from exc

import helm_python as helm

from . import audit, tools
from .apps_html import RELEASES_APP_HTML, RELEASES_APP_URI
from .safety import SafetyError

#: Failures whose message is meant for the caller: they surface verbatim
#: as tool errors instead of the SDK's generic "Error executing tool".
ANTICIPATED = (helm.HelmError, SafetyError, ValueError)


def tool_errors(fn: Any) -> Any:
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except ANTICIPATED as exc:
                raise ToolError(str(exc)) from exc

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ANTICIPATED as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


# Audit trail on stderr: MCP stdio framing owns stdout, stderr is ours.
logging.basicConfig(
    stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)

apps = Apps()


class AuditMiddleware:
    """Ties each tools/call request id to the audit trail and its outcome.

    Runs inside the SDK's OpenTelemetry middleware, so the emitted event
    carries the request's trace/span IDs; the per-tool detail (arguments,
    duration) comes from the tool layer's own ``tool.call`` events.
    """

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        tool = (ctx.params or {}).get("name")
        try:
            result = await call_next(ctx)
        except Exception as exc:
            audit.emit(
                "mcp.request",
                tool=tool,
                request_id=str(ctx.request_id),
                outcome=type(exc).__name__,
            )
            raise
        is_error = bool(getattr(result, "is_error", False)) or (
            isinstance(result, dict) and result.get("isError") is True
        )
        audit.emit(
            "mcp.request",
            tool=tool,
            request_id=str(ctx.request_id),
            outcome="tool_error" if is_error else "success",
        )
        return result


def dump(value: Any) -> str:
    return tools.clamp_output(json.dumps(value, indent=2, default=str))


def reporter(ctx: Context) -> Callable[[float, str], Awaitable[None]]:
    """Adapt ``ctx.report_progress`` to the feedback callback shape."""

    async def report(elapsed: float, message: str) -> None:
        await ctx.report_progress(progress=elapsed, message=message)

    return report


# --- MCP Apps tool (registered on the extension, before the server) -------


@apps.tool(
    resource_uri=RELEASES_APP_URI,
    description="List Helm releases (all states). name_filter is a regex on names.",
)
@tool_errors
def helm_list_releases(
    namespace: str | None = None,
    all_namespaces: bool = False,
    name_filter: str | None = None,
) -> str:
    return dump(
        tools.list_releases(namespace, all_namespaces=all_namespaces, name_filter=name_filter)
    )


apps.add_html_resource(RELEASES_APP_URI, RELEASES_APP_HTML, title="Helm releases")

mcp = MCPServer("helm", extensions=[apps], middleware=[AuditMiddleware()])
