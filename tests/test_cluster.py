"""The release lifecycle against a real cluster, through the safety tiers.

Runs only when a cluster is reachable (``pytest -m cluster``; CI provides
kind). The refusal paths are unit-tested offline; here the *allowed*
paths run for real: dry-run leaves no trace, apply installs, upgrade
creates a revision, rollback restores, uninstall removes — through the
tool layer and once through the full MCP wire.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path

import helm_python as helm
import pytest

from helm_ai import safety, tools

pytestmark = pytest.mark.cluster

RELEASE = "e2e-demo"


@pytest.fixture(scope="module", autouse=True)
def _cluster() -> None:
    with helm.Config() as probe:
        try:
            probe.check_reachable()
        except helm.HelmKubeError:
            pytest.skip("no reachable Kubernetes cluster")


@pytest.fixture(autouse=True)
def _gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(safety.WRITES_ENV, "1")
    monkeypatch.setenv(safety.DESTRUCTIVE_ENV, "1")
    monkeypatch.delenv("HELM_AI_STORAGE_DRIVER", raising=False)
    safety.set_approval_hook(None)


@pytest.fixture(scope="module")
def chart_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("charts")
    helm.Chart.create("demo", root).close()
    return root / "demo"


@pytest.fixture()
def namespace() -> Iterator[str]:
    name = f"helm-ai-e2e-{uuid.uuid4().hex[:8]}"
    yield name
    # Best-effort cleanup; the namespaced release is removed by the tests.
    with helm.Config(namespace=name) as cfg:
        for release in cfg.list(all_states=True):
            cfg.uninstall(str(release["name"]), ignore_not_found=True)


def test_dry_run_leaves_no_trace(chart_dir: Path, namespace: str) -> None:
    result = tools.install_release(
        str(chart_dir), RELEASE, namespace=namespace, create_namespace=True
    )
    assert result["name"] == RELEASE
    assert "manifest" in result
    assert tools.list_releases(namespace) == []


def test_full_lifecycle(chart_dir: Path, namespace: str) -> None:
    installed = tools.install_release(
        str(chart_dir),
        RELEASE,
        namespace=namespace,
        apply=True,
        create_namespace=True,
        timeout=120,
    )
    assert installed["namespace"] == namespace

    status = tools.release_status(RELEASE, namespace)
    assert status["status"] == "deployed"
    assert status["revision"] == 1
    assert tools.release_manifest(RELEASE, namespace)

    upgraded = tools.upgrade_release(
        str(chart_dir),
        RELEASE,
        {"replicaCount": 2},
        namespace,
        apply=True,
        timeout=120,
    )
    assert upgraded["revision"] == 2
    assert tools.release_values(RELEASE, namespace) == {"replicaCount": 2}

    history = tools.release_history(RELEASE, namespace)
    assert [entry["revision"] for entry in history] == [1, 2]

    rolled = tools.rollback_release(RELEASE, namespace, confirm=RELEASE, revision=1)
    assert rolled["revision"] == 3
    # Revision 1 carried no user values; the SDK reports that as null.
    assert not tools.release_values(RELEASE, namespace)

    removed = tools.uninstall_release(RELEASE, namespace, confirm=RELEASE)
    assert removed["release"]["name"] == RELEASE
    assert tools.list_releases(namespace) == []


def test_apply_over_mcp_wire(chart_dir: Path, namespace: str) -> None:
    mcp_module = pytest.importorskip("helm_ai.mcp_server")
    client_cls = pytest.importorskip("mcp").Client

    async def scenario() -> None:
        async with client_cls(mcp_module.mcp) as client:
            installed = await client.call_tool(
                "helm_install_release",
                {
                    "chart_ref": str(chart_dir),
                    "name": RELEASE,
                    "namespace": namespace,
                    "apply": True,
                    "create_namespace": True,
                },
            )
            assert not installed.is_error, installed.content[0].text
            removed = await client.call_tool(
                "helm_uninstall_release",
                {"name": RELEASE, "confirm": RELEASE, "namespace": namespace},
            )
            assert not removed.is_error, removed.content[0].text

    asyncio.run(scenario())


def test_no_handles_leaked_by_cluster_suite() -> None:
    assert helm.open_handles_count() == 0
