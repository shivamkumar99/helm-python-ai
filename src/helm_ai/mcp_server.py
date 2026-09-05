"""The Helm MCP server: the shared tool layer exposed over MCP stdio.

Run with ``helm-ai-mcp`` (or ``python -m helm_ai.mcp_server``) and register
it in any MCP client. Requires the ``server`` extra (``pip install
helm-python-ai[server]``).

Cluster writes stay dry-run only unless the process environment sets
``HELM_AI_ALLOW_WRITES=1``; uninstall/rollback additionally need
``HELM_AI_ALLOW_DESTRUCTIVE=1``. There is no interactive prompt over MCP,
so the environment is the only authorization channel here.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "the MCP server needs the 'mcp' package (2.x): "
        "pip install helm-python-ai[server]"
    ) from exc

import helm_python as helm

from . import tools

mcp = MCPServer("helm")

# Audit trail on stderr: MCP stdio framing owns stdout, stderr is ours.
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")


def _dump(value: Any) -> str:
    return tools.clamp_output(json.dumps(value, indent=2, default=str))


@mcp.tool()
def helm_list_releases(
    namespace: str | None = None,
    all_namespaces: bool = False,
    name_filter: str | None = None,
) -> str:
    """List Helm releases (all states). name_filter is a regex on names."""
    return _dump(
        tools.list_releases(
            namespace, all_namespaces=all_namespaces, name_filter=name_filter
        )
    )


@mcp.tool()
def helm_release_status(
    name: str, namespace: str | None = None, revision: int | None = None
) -> str:
    """Status of a release: state, chart, versions, notes (manifest omitted)."""
    return _dump(tools.release_status(name, namespace, revision))


@mcp.tool()
def helm_release_manifest(
    name: str, namespace: str | None = None, revision: int | None = None
) -> str:
    """The full rendered Kubernetes manifest stored for a release revision."""
    return tools.clamp_output(tools.release_manifest(name, namespace, revision))


@mcp.tool()
def helm_release_history(
    name: str, namespace: str | None = None, max_revisions: int | None = None
) -> str:
    """A release's revision history, oldest first."""
    return _dump(tools.release_history(name, namespace, max_revisions))


@mcp.tool()
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
def helm_show_chart(
    chart_ref: str,
    output_format: str = "all",
    version: str | None = None,
    repo_url: str | None = None,
) -> str:
    """Show a chart's definition/values/readme/crds without installing it."""
    return tools.clamp_output(
        tools.show_chart(
            chart_ref, output_format=output_format, version=version, repo_url=repo_url
        )
    )


@mcp.tool()
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
def helm_lint_chart(chart_path: str, strict: bool = False, kube_version: str | None = None) -> str:
    """Lint a local chart; returns findings (severity 1=info 2=warn 3=error)."""
    return _dump(tools.lint_chart(chart_path, strict=strict or None, kube_version=kube_version))


@mcp.tool()
def helm_search_repository(repo_url: str, name_filter: str | None = None) -> str:
    """Chart names and recent versions from an HTTP chart repository index."""
    return _dump(tools.search_repository(repo_url, name_filter))


@mcp.tool()
def helm_chart_tags(oci_ref: str) -> str:
    """Available tags of an oci://host/path/chart reference, newest first."""
    return _dump(tools.chart_tags(oci_ref))


@mcp.tool()
def helm_install_release(
    chart_ref: str,
    name: str,
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
    return _dump(
        tools.install_release(
            chart_ref,
            name,
            values,
            namespace,
            apply=apply,
            create_namespace=create_namespace,
            chart_repo_url=chart_repo_url,
            chart_version=chart_version,
        )
    )


@mcp.tool()
def helm_upgrade_release(
    chart_ref: str,
    name: str,
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
    return _dump(
        tools.upgrade_release(
            chart_ref,
            name,
            values,
            namespace,
            apply=apply,
            reuse_values=reuse_values,
            chart_repo_url=chart_repo_url,
            chart_version=chart_version,
        )
    )


@mcp.tool()
def helm_uninstall_release(
    name: str, confirm: str, namespace: str | None = None, keep_history: bool = False
) -> str:
    """Uninstall a release. confirm must equal the release name exactly, and
    the server env must set HELM_AI_ALLOW_DESTRUCTIVE=1."""
    return _dump(
        tools.uninstall_release(name, namespace, confirm=confirm, keep_history=keep_history)
    )


@mcp.tool()
def helm_rollback_release(
    name: str, confirm: str, namespace: str | None = None, revision: int | None = None
) -> str:
    """Roll a release back to a revision (previous when omitted). confirm
    must equal the release name; needs HELM_AI_ALLOW_DESTRUCTIVE=1."""
    return _dump(tools.rollback_release(name, namespace, confirm=confirm, revision=revision))


@mcp.tool()
def helm_versions() -> str:
    """Versions of the Helm SDK stack this server is running on."""
    return _dump(
        {
            "helm_sdk": helm.helm_sdk_version(),
            "helm_c": helm.helm_c_version(),
            "helm_python": helm.__version__,
        }
    )


def main() -> None:
    """Entry point for ``helm-ai-mcp``: serve over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
