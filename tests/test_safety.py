"""The safety gates: environment flags, approval hook, confirm echo."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from helm_ai import safety


@pytest.fixture(autouse=True)
def _clean_gates(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(safety.WRITES_ENV, raising=False)
    monkeypatch.delenv(safety.DESTRUCTIVE_ENV, raising=False)
    safety.set_approval_hook(None)
    yield
    safety.set_approval_hook(None)


def test_writes_refused_by_default() -> None:
    with pytest.raises(safety.SafetyError, match="disabled by default"):
        safety.ensure_writes_allowed("helm install demo ./chart")


def test_writes_allowed_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(safety.WRITES_ENV, "1")
    safety.ensure_writes_allowed("helm install demo ./chart")


def test_writes_allowed_by_hook_and_hook_sees_description() -> None:
    seen: list[str] = []

    def hook(description: str) -> bool:
        seen.append(description)
        return True

    safety.set_approval_hook(hook)
    safety.ensure_writes_allowed("helm upgrade demo ./chart")
    assert seen == ["helm upgrade demo ./chart"]


def test_writes_refused_when_hook_declines() -> None:
    safety.set_approval_hook(lambda _d: False)
    with pytest.raises(safety.SafetyError):
        safety.ensure_writes_allowed("helm install demo ./chart")


def test_destructive_needs_exact_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(safety.DESTRUCTIVE_ENV, "1")
    with pytest.raises(safety.SafetyError, match="exact release name"):
        safety.ensure_destructive_allowed("helm uninstall demo", "demo", "demoo")
    safety.ensure_destructive_allowed("helm uninstall demo", "demo", "demo")


def test_destructive_refused_without_gate() -> None:
    with pytest.raises(safety.SafetyError, match="disabled by default"):
        safety.ensure_destructive_allowed("helm uninstall demo", "demo", "demo")


def test_writes_env_does_not_unlock_destructive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(safety.WRITES_ENV, "1")
    with pytest.raises(safety.SafetyError):
        safety.ensure_destructive_allowed("helm uninstall demo", "demo", "demo")
