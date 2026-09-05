"""The shared tool layer against the real native library, fully offline.

Chart tools use a scaffolded chart; release tools run on the in-memory
storage driver so no cluster is involved.
"""

from __future__ import annotations

from pathlib import Path

import helm_python as helm
import pytest

from helm_ai import safety, tools

pytestmark = pytest.mark.filterwarnings("ignore::ResourceWarning")


@pytest.fixture(autouse=True)
def _memory_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HELM_AI_STORAGE_DRIVER", "memory")
    monkeypatch.delenv(safety.WRITES_ENV, raising=False)
    monkeypatch.delenv(safety.DESTRUCTIVE_ENV, raising=False)
    safety.set_approval_hook(None)


@pytest.fixture(scope="module")
def chart_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("charts")
    with helm.Chart.create("demo", root):
        pass
    return root / "demo"


def test_template_chart(chart_dir: Path) -> None:
    manifests = tools.template_chart(str(chart_dir), name="demo")
    assert any(path.endswith("deployment.yaml") for path in manifests)
    rendered = "".join(manifests.values())
    assert "demo" in rendered


def test_template_chart_applies_values(chart_dir: Path) -> None:
    manifests = tools.template_chart(
        str(chart_dir), {"replicaCount": 3}, name="demo"
    )
    deployment = next(body for path, body in manifests.items() if "deployment" in path)
    assert "replicas: 3" in deployment


def test_lint_chart(chart_dir: Path) -> None:
    report = tools.lint_chart(str(chart_dir))
    assert report["total_charts_linted"] == 1
    assert report.get("errors") in (None, [])


def test_show_chart(chart_dir: Path) -> None:
    text = tools.show_chart(str(chart_dir), output_format="chart")
    assert "name: demo" in text


def test_install_defaults_to_dry_run(chart_dir: Path) -> None:
    with helm.Config(namespace="default", storage_driver="memory") as probe:
        try:
            probe.check_reachable()
        except helm.HelmKubeError:
            # Install (even dry-run) and list both probe the cluster first.
            pytest.skip("no reachable Kubernetes cluster")
    release = tools.install_release(
        str(chart_dir), "demo", namespace="default", dry_run_mode="client"
    )
    assert release["name"] == "demo"
    # A dry run must leave no trace in storage.
    assert tools.list_releases("default") == []


def test_install_apply_refused_without_gate(chart_dir: Path) -> None:
    with pytest.raises(safety.SafetyError):
        tools.install_release(str(chart_dir), "demo", apply=True)


def test_uninstall_refused_without_confirm() -> None:
    with pytest.raises(safety.SafetyError, match="exact release name"):
        tools.uninstall_release("demo", confirm="")


def test_rollback_refused_without_gate() -> None:
    with pytest.raises(safety.SafetyError):
        tools.rollback_release("demo", confirm="demo")


def test_no_native_handles_leak(chart_dir: Path) -> None:
    tools.template_chart(str(chart_dir), name="demo")
    tools.lint_chart(str(chart_dir))
    assert helm.open_handles_count() == 0
