"""The agent's mutating tools: they can change a cluster.

Install and upgrade run as server-side dry runs unless ``apply`` is set,
and uninstall and rollback demand the release name echoed back. Both
tiers pass through :mod:`helm_ai.safety`, so a refusal comes back to the
model as text explaining which gate stopped it. The docstrings say so
plainly, because they are what the model reads before choosing.
"""

from __future__ import annotations

from typing import Any

from anthropic import beta_tool

from .. import tools
from ._support import as_json, guard

__all__ = ["WRITE_TOOLS"]


@beta_tool
@guard
def install_release(
    chart_ref: str,
    name: str,
    values_json: str = "",
    namespace: str = "",
    apply: bool = False,
    create_namespace: bool = False,
    chart_repo_url: str = "",
    chart_version: str = "",
) -> str:
    """Install a chart as a release. Dry-run by default; apply=true performs
    the real install and requires the operator's approval.

    Args:
        chart_ref: Local path, repository chart name, or oci:// reference.
        name: The release name to create.
        values_json: JSON document of override values.
        namespace: Target namespace; empty means default.
        apply: False = server-side dry run; true = really install.
        create_namespace: Create the namespace if missing (real installs).
        chart_repo_url: HTTP repository URL when chart_ref is a bare name.
        chart_version: Chart version constraint; empty means the latest.
    """
    values = tools.parse_values_json(values_json)
    return as_json(
        tools.install_release(
            chart_ref,
            name,
            values,
            namespace or None,
            apply=apply,
            create_namespace=create_namespace,
            chart_repo_url=chart_repo_url or None,
            chart_version=chart_version or None,
        )
    )


@beta_tool
@guard
def upgrade_release(
    chart_ref: str,
    name: str,
    values_json: str = "",
    namespace: str = "",
    apply: bool = False,
    reuse_values: bool = False,
    chart_repo_url: str = "",
    chart_version: str = "",
) -> str:
    """Upgrade a release. Dry-run by default; apply=true performs the real
    upgrade and requires the operator's approval.

    Args:
        chart_ref: Local path, repository chart name, or oci:// reference.
        name: The release to upgrade.
        values_json: JSON document of override values.
        namespace: Namespace of the release; empty means default.
        apply: False = server-side dry run; true = really upgrade.
        reuse_values: Merge on top of the release's current values.
        chart_repo_url: HTTP repository URL when chart_ref is a bare name.
        chart_version: Chart version constraint; empty means the latest.
    """
    values = tools.parse_values_json(values_json)
    return as_json(
        tools.upgrade_release(
            chart_ref,
            name,
            values,
            namespace or None,
            apply=apply,
            reuse_values=reuse_values,
            chart_repo_url=chart_repo_url or None,
            chart_version=chart_version or None,
        )
    )


@beta_tool
@guard
def uninstall_release(
    name: str, confirm: str, namespace: str = "", keep_history: bool = False
) -> str:
    """Uninstall a release permanently. Requires confirm=<release name> and
    the operator's approval; use only when the mission clearly demands it.

    Args:
        name: The release to uninstall.
        confirm: Must equal the release name exactly.
        namespace: Namespace of the release; empty means default.
        keep_history: Keep the release history (helm uninstall --keep-history).
    """
    return as_json(
        tools.uninstall_release(name, namespace or None, confirm=confirm, keep_history=keep_history)
    )


@beta_tool
@guard
def rollback_release(name: str, confirm: str, namespace: str = "", revision: int = 0) -> str:
    """Roll a release back to an earlier revision. Requires confirm=<release
    name> and the operator's approval.

    Args:
        name: The release to roll back.
        confirm: Must equal the release name exactly.
        namespace: Namespace of the release; empty means default.
        revision: Revision to roll back to; 0 means the previous one.
    """
    return as_json(
        tools.rollback_release(name, namespace or None, confirm=confirm, revision=revision or None)
    )


#: Declared tools are SDK objects with their own parameter types, so the
#: list is typed loosely and validated by the SDK when a call is made.
WRITE_TOOLS: list[Any] = [
    install_release,
    upgrade_release,
    uninstall_release,
    rollback_release,
]
