"""The mission loop and the CLI around it, driven without a real model.

``run_mission`` is exercised against a stub client so the loop's own
behaviour — accumulating token usage, surfacing the final text, emitting
the audit event — is tested without spending an API call or needing a
credential.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

pytest.importorskip("anthropic")

from helm_ai import agent, safety


class _Block:
    def __init__(self, type_: str, **fields: Any) -> None:
        self.type = type_
        for key, value in fields.items():
            setattr(self, key, value)


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Message:
    def __init__(self, content: list[_Block], usage: _Usage | None = None) -> None:
        self.content = content
        self.usage = usage


class _StubClient:
    """Stands in for anthropic.Anthropic, yielding a scripted transcript."""

    def __init__(self, messages: list[_Message]) -> None:
        self._messages = messages
        self.calls: list[dict[str, Any]] = []
        self.beta = self  # type: ignore[assignment]
        self.messages = self  # type: ignore[assignment]

    def tool_runner(self, **kwargs: Any) -> list[_Message]:
        self.calls.append(kwargs)
        return self._messages


def test_run_mission_returns_the_final_text_and_counts_usage(capsys: pytest.CaptureFixture) -> None:
    client = _StubClient(
        [
            _Message([_Block("tool_use", name="list_releases", input={})], _Usage(10, 5)),
            _Message([_Block("text", text="payments-api is failing")], _Usage(20, 7)),
        ]
    )
    answer = agent.run_mission("why is it failing?", client=client)  # type: ignore[arg-type]

    assert answer == "payments-api is failing"
    sent = client.calls[0]
    assert sent["model"] == agent.DEFAULT_MODEL
    assert sent["messages"] == [{"role": "user", "content": "why is it failing?"}]
    assert sent["tools"] is agent.TOOLS
    # Adaptive thinking is what makes the agent reason before acting.
    assert sent["thinking"] == {"type": "adaptive"}


def test_run_mission_reports_every_message_to_the_caller() -> None:
    seen: list[Any] = []
    client = _StubClient(
        [_Message([_Block("text", text="one")]), _Message([_Block("text", text="two")])]
    )
    agent.run_mission("go", client=client, on_message=seen.append)  # type: ignore[arg-type]
    assert len(seen) == 2


def test_narration_prints_text_and_traces_tool_calls(capsys: pytest.CaptureFixture) -> None:
    agent._narrate(
        _Message(
            [
                _Block("text", text="looking at the release"),
                _Block("tool_use", name="release_status", input={"name": "demo"}),
            ]
        )
    )
    captured = capsys.readouterr()
    # The answer goes to stdout, the trace to stderr, so piping the
    # command still yields just the answer.
    assert "looking at the release" in captured.out
    assert "release_status" in captured.err
    assert "demo" in captured.err


def test_terminal_approval_accepts_only_an_explicit_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    for answer, expected in (("y\n", True), ("yes\n", True), ("n\n", False), ("\n", False)):
        monkeypatch.setattr("sys.stdin", io.StringIO(answer))
        assert agent._terminal_approval("helm uninstall demo") is expected


def test_approval_hook_reaches_the_safety_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(safety.WRITES_ENV, raising=False)
    asked: list[str] = []

    def approve(description: str) -> bool:
        asked.append(description)
        return True

    safety.set_approval_hook(approve)
    try:
        safety.ensure_writes_allowed("helm upgrade demo ./chart")
    finally:
        safety.set_approval_hook(None)
    assert asked == ["helm upgrade demo ./chart"]
