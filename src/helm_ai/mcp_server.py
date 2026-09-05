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
        "the MCP server needs the 'mcp' package (2.x): "
        "pip install helm-python-ai[server]"
    ) from exc

import helm_python as helm

from . import audit, feedback, telemetry, tools
from .apps_html import RELEASES_APP_HTML, RELEASES_APP_URI
from .safety import SafetyError

#: Failures whose message is meant for the caller: they surface verbatim
#: as tool errors instead of the SDK's generic "Error executing tool".
_ANTICIPATED = (helm.HelmError, SafetyError, ValueError)


def _tool_errors(fn: Any) -> Any:
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except _ANTICIPATED as exc:
                raise ToolError(str(exc)) from exc

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except _ANTICIPATED as exc:
            raise ToolError(str(exc)) from exc

    return wrapper

# Audit trail on stderr: MCP stdio framing owns stdout, stderr is ours.
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

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


def _dump(value: Any) -> str:
    return tools.clamp_output(json.dumps(value, indent=2, default=str))


def _reporter(ctx: Context) -> Callable[[float, str], Awaitable[None]]:
    """Adapt ``ctx.report_progress`` to the feedback callback shape."""

    async def report(elapsed: float, message: str) -> None:
        await ctx.report_progress(progress=elapsed, message=message)

    return report


# --- MCP Apps tool (registered on the extension, before the server) -------


@apps.tool(
    resource_uri=RELEASES_APP_URI,
    description="List Helm releases (all states). name_filter is a regex on names.",
)
@_tool_errors
def helm_list_releases(
    namespace: str | None = None,
    all_namespaces: bool = False,
    name_filter: str | None = None,
) -> str:
    return _dump(
        tools.list_releases(
            namespace, all_namespaces=all_namespaces, name_filter=name_filter
        )
    )


apps.add_html_resource(RELEASES_APP_URI, RELEASES_APP_HTML, title="Helm releases")

mcp = MCPServer("helm", extensions=[apps], middleware=[AuditMiddleware()])


# --- fast read tools (sync; they finish well under a heartbeat) -----------


@mcp.tool()
@_tool_errors
def helm_release_status(
    name: str, namespace: str | None = None, revision: int | None = None
) -> str:
    """Status of a release: state, chart, versions, notes (manifest omitted)."""
    return _dump(tools.release_status(name, namespace, revision))


@mcp.tool()
@_tool_errors
def helm_release_manifest(
    name: str, namespace: str | None = None, revision: int | None = None
) -> str:
    """The full rendered Kubernetes manifest stored for a release revision."""
    return tools.clamp_output(tools.release_manifest(name, namespace, revision))


@mcp.tool()
@_tool_errors
def helm_release_history(
    name: str, namespace: str | None = None, max_revisions: int | None = None
) -> str:
    """A release's revision history, oldest first."""
    return _dump(tools.release_history(name, namespace, max_revisions))


@mcp.tool()
@_tool_errors
def helm_release_values(
    name: str,
    namespace: str | None = None,
    all_values: bool = False,
    revision: int | None = None,
) -> str:
    """A release's user-supplied values (computed values with all_values)."""
    return _dump(
        tools.release_values(name, namespace, all_values=all_values, revision=revision)
    )


@mcp.tool()
@_tool_errors
def helm_template_chart(
    chart_path: str,
    values_json: str | None = None,
    name: str = "release-name",
    namespace: str | None = None,
) -> str:
    """Render a local chart offline. values_json is a JSON values document."""
    values = tools.parse_values_json(values_json)
    return _dump(tools.template_chart(chart_path, values, name=name, namespace=namespace))


@mcp.tool()
@_tool_errors
def helm_lint_chart(chart_path: str, strict: bool = False, kube_version: str | None = None) -> str:
    """Lint a local chart; returns findings (severity 1=info 2=warn 3=error)."""
    return _dump(tools.lint_chart(chart_path, strict=strict or None, kube_version=kube_version))


@mcp.tool()
@_tool_errors
def helm_versions() -> str:
    """Versions of the Helm SDK stack this server is running on."""
    return _dump(
        {
            "helm_sdk": helm.helm_sdk_version(),
            "helm_c": helm.helm_c_version(),
            "helm_python": helm.__version__,
        }
    )


# --- network / long-running tools (async, with progress heartbeats) -------


@mcp.tool()
@_tool_errors
async def helm_show_chart(
    chart_ref: str,
    ctx: Context,
    output_format: str = "all",
    version: str | None = None,
    repo_url: str | None = None,
) -> str:
    """Show a chart's definition/values/readme/crds without installing it."""
    text = await feedback.run_blocking(
        f"helm show {chart_ref}",
        lambda: tools.show_chart(
            chart_ref, output_format=output_format, version=version, repo_url=repo_url
        ),
        report=_reporter(ctx),
    )
    return tools.clamp_output(text)


@mcp.tool()
@_tool_errors
async def helm_search_repository(
    repo_url: str, ctx: Context, name_filter: str | None = None
) -> str:
    """Chart names and recent versions from an HTTP chart repository index."""
    result = await feedback.run_blocking(
        f"fetching index {repo_url}",
        tools.search_repository,
        repo_url,
        name_filter,
        report=_reporter(ctx),
    )
    return _dump(result)


@mcp.tool()
@_tool_errors
async def helm_chart_tags(oci_ref: str, ctx: Context) -> str:
    """Available tags of an oci://host/path/chart reference, newest first."""
    result = await feedback.run_blocking(
        f"listing tags {oci_ref}", tools.chart_tags, oci_ref, report=_reporter(ctx)
    )
    return _dump(result)


@mcp.tool()
@_tool_errors
async def helm_install_release(
    chart_ref: str,
    name: str,
    ctx: Context,
    values_json: str | None = None,
    namespace: str | None = None,
    apply: bool = False,
    create_namespace: bool = False,
    chart_repo_url: str | None = None,
    chart_version: str | None = None,
) -> str:
    """Install a chart. Runs as a server-side dry run unless apply=true
    (real installs also need HELM_AI_ALLOW_WRITES=1 in the server env)."""
    values = tools.parse_values_json(values_json)
    mode = "apply" if apply else "dry-run"
    result = await feedback.run_blocking(
        f"helm install {name} ({mode})",
        lambda: tools.install_release(
            chart_ref,
            name,
            values,
            namespace,
            apply=apply,
            create_namespace=create_namespace,
            chart_repo_url=chart_repo_url,
            chart_version=chart_version,
        ),
        report=_reporter(ctx),
    )
    return _dump(result)


@mcp.tool()
@_tool_errors
async def helm_upgrade_release(
    chart_ref: str,
    name: str,
    ctx: Context,
    values_json: str | None = None,
    namespace: str | None = None,
    apply: bool = False,
    reuse_values: bool = False,
    chart_repo_url: str | None = None,
    chart_version: str | None = None,
) -> str:
    """Upgrade a release. Runs as a server-side dry run unless apply=true
    (real upgrades also need HELM_AI_ALLOW_WRITES=1 in the server env)."""
    values = tools.parse_values_json(values_json)
    mode = "apply" if apply else "dry-run"
    result = await feedback.run_blocking(
        f"helm upgrade {name} ({mode})",
        lambda: tools.upgrade_release(
            chart_ref,
            name,
            values,
            namespace,
            apply=apply,
            reuse_values=reuse_values,
            chart_repo_url=chart_repo_url,
            chart_version=chart_version,
        ),
        report=_reporter(ctx),
    )
    return _dump(result)


@mcp.tool()
@_tool_errors
async def helm_uninstall_release(
    name: str,
    confirm: str,
    ctx: Context,
    namespace: str | None = None,
    keep_history: bool = False,
) -> str:
    """Uninstall a release. confirm must equal the release name exactly, and
    the server env must set HELM_AI_ALLOW_DESTRUCTIVE=1."""
    result = await feedback.run_blocking(
        f"helm uninstall {name}",
        lambda: tools.uninstall_release(
            name, namespace, confirm=confirm, keep_history=keep_history
        ),
        report=_reporter(ctx),
    )
    return _dump(result)


@mcp.tool()
@_tool_errors
async def helm_rollback_release(
    name: str,
    confirm: str,
    ctx: Context,
    namespace: str | None = None,
    revision: int | None = None,
) -> str:
    """Roll a release back to a revision (previous when omitted). confirm
    must equal the release name; needs HELM_AI_ALLOW_DESTRUCTIVE=1."""
    result = await feedback.run_blocking(
        f"helm rollback {name}",
        lambda: tools.rollback_release(name, namespace, confirm=confirm, revision=revision),
        report=_reporter(ctx),
    )
    return _dump(result)


def main() -> None:
    """Entry point for ``helm-ai-mcp``: serve over stdio."""
    telemetry.configure_telemetry("helm-ai-mcp")
    feedback.capture_native_logs()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
