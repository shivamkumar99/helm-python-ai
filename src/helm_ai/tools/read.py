"""Tools that only observe: no gate, nothing written to a cluster."""

from __future__ import annotations

from contextlib import closing
from typing import Any

import helm_python as helm

from .. import audit
from ._base import Json, config

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
    with closing(config(namespace)) as cfg:
        return cfg.list(
            all_states=all_states,
            all_namespaces=all_namespaces,
            name_filter=name_filter,
        )


@audit.observed
def release_status(name: str, namespace: str | None = None, revision: int | None = None) -> Json:
    """Full release summary, without the (often huge) manifest body."""
    with closing(config(namespace)) as cfg:
        status = cfg.status(name, revision=revision)
    manifest = status.pop("manifest", "")
    status["manifest_size_bytes"] = len(manifest)
    return status


@audit.observed
def release_manifest(name: str, namespace: str | None = None, revision: int | None = None) -> str:
    """The rendered manifest stored for a release revision."""
    with closing(config(namespace)) as cfg:
        manifest = cfg.status(name, revision=revision).get("manifest", "")
    return str(manifest)


@audit.observed
def release_history(
    name: str, namespace: str | None = None, max_revisions: int | None = None
) -> list[Json]:
    """The release's revisions, oldest first."""
    with closing(config(namespace)) as cfg:
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
    with closing(config(namespace)) as cfg:
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
