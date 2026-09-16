"""Tools that can change a cluster, each behind its safety gate.

Install and upgrade are dry runs unless ``apply`` is set and writes are
permitted; uninstall and rollback additionally require the release name
echoed back in ``confirm``.
"""

from __future__ import annotations

from contextlib import closing

import helm_python as helm

from .. import audit, safety
from ._base import DEFAULT_TIMEOUT, Json, config

# --- write tier (dry-run by default) --------------------------------------


@audit.observed
def install_release(
    chart_ref: str,
    name: str,
    values: Json | None = None,
    namespace: str | None = None,
    *,
    apply: bool = False,
    dry_run_mode: str = "server",
    create_namespace: bool = False,
    chart_repo_url: str | None = None,
    chart_version: str | None = None,
    timeout: int | None = None,
) -> Json:
    """Install a chart. A dry run unless ``apply=True`` and writes allowed."""
    helm.validate_release_name(name)
    if apply:
        safety.ensure_writes_allowed(
            f"helm install {name} {chart_ref} (namespace={namespace or 'default'})"
        )
    with closing(config(namespace)) as cfg:
        return cfg.install(
            chart_ref,
            name,
            values,
            dry_run=None if apply else dry_run_mode,
            create_namespace=create_namespace,
            chart_repo_url=chart_repo_url,
            chart_version=chart_version,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )


@audit.observed
def upgrade_release(
    chart_ref: str,
    name: str,
    values: Json | None = None,
    namespace: str | None = None,
    *,
    apply: bool = False,
    dry_run_mode: str = "server",
    reuse_values: bool = False,
    chart_repo_url: str | None = None,
    chart_version: str | None = None,
    timeout: int | None = None,
) -> Json:
    """Upgrade a release. A dry run unless ``apply=True`` and writes allowed."""
    helm.validate_release_name(name)
    if apply:
        safety.ensure_writes_allowed(
            f"helm upgrade {name} {chart_ref} (namespace={namespace or 'default'})"
        )
    with closing(config(namespace)) as cfg:
        return cfg.upgrade(
            chart_ref,
            name,
            values,
            dry_run=None if apply else dry_run_mode,
            reuse_values=reuse_values,
            chart_repo_url=chart_repo_url,
            chart_version=chart_version,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )


# --- destructive tier ------------------------------------------------------


@audit.observed
def uninstall_release(
    name: str,
    namespace: str | None = None,
    *,
    confirm: str = "",
    keep_history: bool = False,
) -> Json:
    """Uninstall a release; ``confirm`` must echo the release name."""
    safety.ensure_destructive_allowed(
        f"helm uninstall {name} (namespace={namespace or 'default'})", name, confirm
    )
    with closing(config(namespace)) as cfg:
        return cfg.uninstall(name, keep_history=keep_history)


@audit.observed
def rollback_release(
    name: str,
    namespace: str | None = None,
    *,
    confirm: str = "",
    revision: int | None = None,
) -> Json:
    """Roll a release back; ``confirm`` must echo the release name."""
    safety.ensure_destructive_allowed(
        f"helm rollback {name} to revision {revision or 'previous'} "
        f"(namespace={namespace or 'default'})",
        name,
        confirm,
    )
    with closing(config(namespace)) as cfg:
        cfg.rollback(name, version=revision)
        return cfg.status(name)
