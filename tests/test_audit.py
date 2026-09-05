"""The audit trail: structured events, file sink, argument allowlisting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helm_ai import audit, safety


@pytest.fixture()
def audit_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv(audit.AUDIT_LOG_ENV, str(path))
    monkeypatch.setattr(audit, "_file_failed", False)
    return path


def _read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_emit_writes_jsonl(audit_file: Path) -> None:
    audit.emit("unit.test", tool="demo", outcome="success")
    events = _read_events(audit_file)
    assert len(events) == 1
    assert events[0]["event"] == "unit.test"
    assert events[0]["tool"] == "demo"
    assert "ts" in events[0]


def test_observed_records_call_with_allowlisted_args(audit_file: Path) -> None:
    @audit.observed
    def sample(name: str, values_json: str = "", password: str = "") -> str:
        return "ok"

    assert sample("demo", values_json='{"a": 1}', password="secret") == "ok"
    (event,) = _read_events(audit_file)
    assert event["event"] == "tool.call"
    assert event["tool"] == "sample"
    assert event["outcome"] == "success"
    args = event["args"]
    assert args == {"name": "demo", "values_json_bytes": 8}
    assert "password" not in json.dumps(event)
    assert "secret" not in json.dumps(event)


def test_observed_records_failure_outcome(audit_file: Path) -> None:
    @audit.observed
    def broken(name: str) -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError):
        broken("demo")
    (event,) = _read_events(audit_file)
    assert event["outcome"] == "ValueError"


def test_safety_refusal_emits_decision(audit_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(safety.WRITES_ENV, raising=False)
    safety.set_approval_hook(None)
    with pytest.raises(safety.SafetyError):
        safety.ensure_writes_allowed("helm install demo ./chart")
    (event,) = _read_events(audit_file)
    assert event["event"] == "safety.decision"
    assert event["decision"] == "refused"
    assert event["tier"] == "write"


def test_unwritable_file_disables_sink_without_breaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(audit.AUDIT_LOG_ENV, str(tmp_path / "missing" / "audit.jsonl"))
    monkeypatch.setattr(audit, "_file_failed", False)
    audit.emit("unit.test")  # must not raise
    assert audit._file_failed is True
