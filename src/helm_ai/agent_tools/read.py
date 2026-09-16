"""The agent's read-only tools: they never change a cluster.

These carry no gate, so the agent can investigate freely before it
proposes anything. Each docstring is the description the model reads when
it chooses a tool, so it states what the tool returns and what every
argument means.
"""

from __future__ import annotations

from typing import Any

from anthropic import beta_tool

from .. import tools
from ._support import as_json, guard

__all__ = ["READ_TOOLS"]


@beta_tool
@guard
def list_releases(namespace: str = "", all_namespaces: bool = False, name_filter: str = "") -> str:
    """List Helm releases in every state.

    Args:
        namespace: Namespace to list; empty means the default namespace.
        all_namespaces: List releases across all namespaces.
        name_filter: Regular expression matched against release names.
    """
    return as_json(
        tools.list_releases(
            namespace or None,
            all_namespaces=all_namespaces,
            name_filter=name_filter or None,
        )
    )


@beta_tool
@guard
def release_status(name: str, namespace: str = "", revision: int = 0) -> str:
    """Release status: state, chart, app version, notes (manifest omitted).

    Args:
        name: The release name.
        namespace: Namespace of the release; empty means default.
        revision: Specific revision to inspect; 0 means the latest.
    """
    return as_json(tools.release_status(name, namespace or None, revision or None))


@beta_tool
@guard
def release_manifest(name: str, namespace: str = "", revision: int = 0) -> str:
    """The full rendered Kubernetes manifest stored for a release revision.

    Args:
        name: The release name.
        namespace: Namespace of the release; empty means default.
        revision: Specific revision to read; 0 means the latest.
    """
    return tools.clamp_output(tools.release_manifest(name, namespace or None, revision or None))


@beta_tool
@guard
def release_history(name: str, namespace: str = "", max_revisions: int = 0) -> str:
    """A release's revision history, oldest first.

    Args:
        name: The release name.
        namespace: Namespace of the release; empty means default.
        max_revisions: Cap on returned revisions; 0 means no cap.
    """
    return as_json(tools.release_history(name, namespace or None, max_revisions or None))


@beta_tool
@guard
def release_values(
    name: str, namespace: str = "", all_values: bool = False, revision: int = 0
) -> str:
    """A release's values; compare revisions to spot what changed.

    Args:
        name: The release name.
        namespace: Namespace of the release; empty means default.
        all_values: Return the fully computed values, not just user-supplied.
        revision: Specific revision to read; 0 means the latest.
    """
    return as_json(
        tools.release_values(
            name, namespace or None, all_values=all_values, revision=revision or None
        )
    )


@beta_tool
@guard
def show_chart(
    chart_ref: str, output_format: str = "all", version: str = "", repo_url: str = ""
) -> str:
    """Show a chart's definition, values, readme, or CRDs without installing.

    Args:
        chart_ref: Local path, repository chart name (with repo_url), or an
            oci:// reference.
        output_format: One of "all", "chart", "values", "readme", "crds".
        version: Chart version constraint; empty means the latest.
        repo_url: HTTP chart repository URL when chart_ref is a bare name.
    """
    return tools.clamp_output(
        tools.show_chart(
            chart_ref,
            output_format=output_format,
            version=version or None,
            repo_url=repo_url or None,
        )
    )


@beta_tool
@guard
def template_chart(
    chart_path: str, values_json: str = "", name: str = "release-name", namespace: str = ""
) -> str:
    """Render a local chart offline; returns template path -> manifest.

    Args:
        chart_path: Path to a chart directory or .tgz archive.
        values_json: JSON document of override values.
        name: Release name to render with.
        namespace: Namespace to render with; empty means default.
    """
    values = tools.parse_values_json(values_json)
    return as_json(tools.template_chart(chart_path, values, name=name, namespace=namespace or None))


@beta_tool
@guard
def lint_chart(chart_path: str, strict: bool = False, kube_version: str = "") -> str:
    """Lint a local chart; findings have severity 1=info 2=warning 3=error.

    Args:
        chart_path: Path to a chart directory or .tgz archive.
        strict: Treat warnings as errors.
        kube_version: Kubernetes version to lint against, e.g. "v1.30.0".
    """
    return as_json(
        tools.lint_chart(chart_path, strict=strict or None, kube_version=kube_version or None)
    )


@beta_tool
@guard
def search_repository(repo_url: str, name_filter: str = "") -> str:
    """Chart names and recent versions from an HTTP chart repository.

    Args:
        repo_url: The chart repository URL.
        name_filter: Case-insensitive substring filter on chart names.
    """
    return as_json(tools.search_repository(repo_url, name_filter or None))


@beta_tool
@guard
def chart_tags(oci_ref: str) -> str:
    """Available tags of an oci://host/path/chart reference, newest first.

    Args:
        oci_ref: The OCI chart reference without a tag.
    """
    return as_json(tools.chart_tags(oci_ref))


#: Declared tools are SDK objects with their own parameter types, so the
#: list is typed loosely and validated by the SDK when a call is made.
READ_TOOLS: list[Any] = [
    list_releases,
    release_status,
    release_manifest,
    release_history,
    release_values,
    show_chart,
    template_chart,
    lint_chart,
    search_repository,
    chart_tags,
]
