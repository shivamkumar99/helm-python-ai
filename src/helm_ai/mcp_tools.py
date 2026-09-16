"""Every Helm tool the MCP server exposes beyond the Apps dashboard.

Importing this module registers them on the server built in
:mod:`helm_ai.mcp_app`. Read tools are plain functions; anything that
touches the network or waits on a cluster is async and reports progress
while it runs, so a slow call never looks like a hung one.
"""

from __future__ import annotations

from typing import Any

import helm_python as helm
from mcp.server.mcpserver import Context

from . import feedback, tools
from .mcp_app import dump, mcp, reporter, tool_errors

# --- fast read tools (sync; they finish well under a heartbeat) -----------


@mcp.tool()
@tool_errors
def helm_release_status(
    name: str, namespace: str | None = None, revision: int | None = None
) -> str:
    """Status of a release: state, chart, versions, notes (manifest omitted)."""
    return dump(tools.release_status(name, namespace, revision))


@mcp.tool()
@tool_errors
def helm_release_manifest(
    name: str, namespace: str | None = None, revision: int | None = None
) -> str:
    """The full rendered Kubernetes manifest stored for a release revision."""
    return tools.clamp_output(tools.release_manifest(name, namespace, revision))


@mcp.tool()
@tool_errors
def helm_release_history(
    name: str, namespace: str | None = None, max_revisions: int | None = None
) -> str:
    """A release's revision history, oldest first."""
    return dump(tools.release_history(name, namespace, max_revisions))


@mcp.tool()
@tool_errors
def helm_release_values(
    name: str,
    namespace: str | None = None,
    all_values: bool = False,
    revision: int | None = None,
) -> str:
    """A release's user-supplied values (computed values with all_values)."""
    return dump(tools.release_values(name, namespace, all_values=all_values, revision=revision))


@mcp.tool()
@tool_errors
def helm_template_chart(
    chart_path: str,
    values: dict[str, Any] | None = None,
    name: str = "release-name",
    namespace: str | None = None,
) -> str:
    """Render a local chart offline. values is a JSON object of overrides."""
    tools.ensure_values_size(values)
    return dump(tools.template_chart(chart_path, values, name=name, namespace=namespace))


@mcp.tool()
@tool_errors
def helm_lint_chart(chart_path: str, strict: bool = False, kube_version: str | None = None) -> str:
    """Lint a local chart; returns findings (severity 1=info 2=warn 3=error)."""
    return dump(tools.lint_chart(chart_path, strict=strict or None, kube_version=kube_version))


@mcp.tool()
@tool_errors
def helm_versions() -> str:
    """Versions of the Helm SDK stack this server is running on."""
    return dump(
        {
            "helm_sdk": helm.helm_sdk_version(),
            "helm_c": helm.helm_c_version(),
            "helm_python": helm.__version__,
        }
    )


# --- network / long-running tools (async, with progress heartbeats) -------


@mcp.tool()
@tool_errors
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
        report=reporter(ctx),
    )
    return tools.clamp_output(text)


@mcp.tool()
@tool_errors
async def helm_search_repository(
    repo_url: str, ctx: Context, name_filter: str | None = None
) -> str:
    """Chart names and recent versions from an HTTP chart repository index."""
    result = await feedback.run_blocking(
        f"fetching index {repo_url}",
        tools.search_repository,
        repo_url,
        name_filter,
        report=reporter(ctx),
    )
    return dump(result)


@mcp.tool()
@tool_errors
async def helm_chart_tags(oci_ref: str, ctx: Context) -> str:
    """Available tags of an oci://host/path/chart reference, newest first."""
    result = await feedback.run_blocking(
        f"listing tags {oci_ref}", tools.chart_tags, oci_ref, report=reporter(ctx)
    )
    return dump(result)


@mcp.tool()
@tool_errors
async def helm_install_release(
    chart_ref: str,
    name: str,
    ctx: Context,
    values: dict[str, Any] | None = None,
    namespace: str | None = None,
    apply: bool = False,
    create_namespace: bool = False,
    chart_repo_url: str | None = None,
    chart_version: str | None = None,
) -> str:
    """Install a chart. Runs as a server-side dry run unless apply=true
    (real installs also need HELM_AI_ALLOW_WRITES=1 in the server env)."""
    tools.ensure_values_size(values)
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
        report=reporter(ctx),
    )
    return dump(result)


@mcp.tool()
@tool_errors
async def helm_upgrade_release(
    chart_ref: str,
    name: str,
    ctx: Context,
    values: dict[str, Any] | None = None,
    namespace: str | None = None,
    apply: bool = False,
    reuse_values: bool = False,
    chart_repo_url: str | None = None,
    chart_version: str | None = None,
) -> str:
    """Upgrade a release. Runs as a server-side dry run unless apply=true
    (real upgrades also need HELM_AI_ALLOW_WRITES=1 in the server env)."""
    tools.ensure_values_size(values)
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
        report=reporter(ctx),
    )
    return dump(result)


@mcp.tool()
@tool_errors
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
        report=reporter(ctx),
    )
    return dump(result)


@mcp.tool()
@tool_errors
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
        report=reporter(ctx),
    )
    return dump(result)
