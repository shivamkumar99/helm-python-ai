"""The shared Helm tool layer: plain functions over helm-python-sdk.

Both fronts — the MCP server and the agent — register these functions as
model-callable tools. Everything here returns JSON-serializable data (or
plain text) and raises ``helm_python.HelmError`` / ``safety.SafetyError``;
presentation and error formatting belong to the fronts.

Cluster access uses the standard resolution (``KUBECONFIG``, then
``~/.kube/config``, then in-cluster). ``HELM_AI_STORAGE_DRIVER`` overrides
the release storage driver (used by the offline test suite).
"""

from __future__ import annotations

import json
import os
from contextlib import closing
from typing import Any

import helm_python as helm

from . import audit, safety

__all__ = [
    "DEFAULT_TIMEOUT",
    "MAX_OUTPUT_CHARS",
    "MAX_VALUES_BYTES",
    "chart_tags",
    "clamp_output",
    "ensure_values_size",
    "install_release",
    "lint_chart",
    "list_releases",
    "parse_values_json",
    "release_history",
    "release_manifest",
    "release_status",
    "release_values",
    "rollback_release",
    "search_repository",
    "show_chart",
    "template_chart",
    "uninstall_release",
    "upgrade_release",
]

Json = dict[str, Any]

#: Ceiling on install/upgrade wait time so a wedged rollout cannot hang the
#: serving process indefinitely (OWASP MCP guide: resource usage limits).
DEFAULT_TIMEOUT = 300

#: Ceiling on the size of a values document accepted from the model.
MAX_VALUES_BYTES = 1_000_000

#: Ceiling on tool output returned to the model; oversized results are
#: truncated with a marker rather than flooding the caller's context.
MAX_OUTPUT_CHARS = 200_000

def parse_values_json(values_json: str | None) -> Json | None:
    """Parse a model-supplied values document, strictly.

    Raises:
        ValueError: when the payload is oversized, malformed, or not a
            JSON object.
    """
    if not values_json:
        return None
    if len(values_json.encode("utf-8", "ignore")) > MAX_VALUES_BYTES:
        raise ValueError(f"values_json exceeds {MAX_VALUES_BYTES} bytes")
    try:
        parsed = json.loads(values_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"values_json is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("values_json must be a JSON object")
    return parsed


def ensure_values_size(values: Json | None) -> Json | None:
    """Enforce the values-size ceiling on an already-parsed document."""
    if values is not None and len(json.dumps(values).encode()) > MAX_VALUES_BYTES:
        raise ValueError(f"values document exceeds {MAX_VALUES_BYTES} bytes")
    return values


def clamp_output(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate oversized tool output, marking the truncation explicitly."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated: {len(text) - limit} characters omitted]"


def _config(namespace: str | None = None) -> helm.Config:
    return helm.Config(
        namespace=namespace,
        storage_driver=os.environ.get("HELM_AI_STORAGE_DRIVER"),
    )


# --- read tier ------------------------------------------------------------


@audit.observed
def list_releases(
    namespace: str | None = None,
    *,
    all_namespaces: bool = False,
    all_states: bool = True,
    name_filter: str | None = None,
) -> list[Json]:
    """Release summaries; ``name_filter`` is a regex on release names."""
    with closing(_config(namespace)) as cfg:
        return cfg.list(
            all_states=all_states,
            all_namespaces=all_namespaces,
            name_filter=name_filter,
        )


@audit.observed
def release_status(name: str, namespace: str | None = None, revision: int | None = None) -> Json:
    """Full release summary, without the (often huge) manifest body."""
    with closing(_config(namespace)) as cfg:
        status = cfg.status(name, revision=revision)
    manifest = status.pop("manifest", "")
    status["manifest_size_bytes"] = len(manifest)
    return status


@audit.observed
def release_manifest(name: str, namespace: str | None = None, revision: int | None = None) -> str:
    """The rendered manifest stored for a release revision."""
    with closing(_config(namespace)) as cfg:
        manifest = cfg.status(name, revision=revision).get("manifest", "")
    return str(manifest)


@audit.observed
def release_history(
    name: str, namespace: str | None = None, max_revisions: int | None = None
) -> list[Json]:
    """The release's revisions, oldest first."""
    with closing(_config(namespace)) as cfg:
        return cfg.history(name, max_revisions=max_revisions)


@audit.observed
def release_values(
    name: str,
    namespace: str | None = None,
    *,
    all_values: bool = False,
    revision: int | None = None,
) -> Json:
    """User-supplied values (or the fully computed ones with ``all_values``)."""
    with closing(_config(namespace)) as cfg:
        return cfg.get_values(name, all_values=all_values, revision=revision)


@audit.observed
def show_chart(
    chart_ref: str,
    *,
    output_format: str = "all",
    version: str | None = None,
    repo_url: str | None = None,
) -> str:
    """``helm show``: chart definition, values, readme, or CRDs as text."""
    return helm.show(
        chart_ref,
        output_format=output_format,
        version=version,
        repo_url=repo_url,
    )


@audit.observed
def template_chart(
    chart_path: str,
    values: Json | None = None,
    *,
    name: str = "release-name",
    namespace: str | None = None,
) -> dict[str, str]:
    """Render a local chart offline; returns template path -> manifest."""
    with closing(helm.Chart.load(chart_path)) as chart:
        return chart.render(values, name=name, namespace=namespace)


@audit.observed
def lint_chart(
    chart_path: str,
    values: Json | None = None,
    *,
    strict: bool | None = None,
    kube_version: str | None = None,
) -> Json:
    """Lint a chart; findings are data, not errors."""
    return helm.lint(chart_path, values, strict=strict, kube_version=kube_version)


@audit.observed
def search_repository(repo_url: str, name_filter: str | None = None) -> Json:
    """Chart names and their most recent versions from a repository index."""
    index = helm.repo_index(repo_url)
    entries: dict[str, Any] = index.get("entries", {})
    summary: dict[str, list[str]] = {}
    for chart_name, versions in entries.items():
        if name_filter and name_filter.lower() not in chart_name.lower():
            continue
        summary[chart_name] = [entry.get("version", "?") for entry in versions[:5]]
    return {"repository": repo_url, "charts": summary}


@audit.observed
def chart_tags(oci_ref: str) -> list[str]:
    """Semver tags of an ``oci://host/path/chart`` reference, newest first."""
    with closing(helm.RegistryClient()) as client:
        return client.tags(oci_ref)


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
    with closing(_config(namespace)) as cfg:
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
    with closing(_config(namespace)) as cfg:
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
    with closing(_config(namespace)) as cfg:
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
    with closing(_config(namespace)) as cfg:
        cfg.rollback(name, version=revision)
        return cfg.status(name)
