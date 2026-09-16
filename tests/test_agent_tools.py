"""The roster the agent hands the model, and how failures reach it.

A tool that raises would abort the model's turn, so every anticipated
failure has to come back as readable text instead. The schemas matter
just as much: they are what the model reads when deciding what to call.
"""

from __future__ import annotations

import pytest

pytest.importorskip("anthropic")

from helm_ai import safety
from helm_ai.agent_tools import READ_TOOLS, TOOLS, WRITE_TOOLS
from helm_ai.agent_tools._support import guard

READ_NAMES = {
    "list_releases",
    "release_status",
    "release_manifest",
    "release_history",
    "release_values",
    "show_chart",
    "template_chart",
    "lint_chart",
    "search_repository",
    "chart_tags",
}
WRITE_NAMES = {"install_release", "upgrade_release", "uninstall_release", "rollback_release"}


def _named(tools: list) -> dict[str, dict]:
    return {t.to_dict()["name"]: t.to_dict() for t in tools}


def test_roster_is_split_by_tier() -> None:
    assert set(_named(READ_TOOLS)) == READ_NAMES
    assert set(_named(WRITE_TOOLS)) == WRITE_NAMES
    # The full roster is both tiers, with reads offered first.
    assert [t.to_dict()["name"] for t in TOOLS][: len(READ_NAMES)] == [
        t.to_dict()["name"] for t in READ_TOOLS
    ]


def test_every_tool_describes_itself_to_the_model() -> None:
    for name, schema in _named(TOOLS).items():
        assert schema["description"].strip(), f"{name} has no description"
        assert schema["input_schema"]["type"] == "object"
        for argument, spec in schema["input_schema"]["properties"].items():
            # The Args section of each docstring becomes the per-argument
            # description the model reads; an undocumented argument means
            # the model is guessing what to put there.
            assert spec.get("description", "").strip(), f"{name} does not document {argument}"


def test_destructive_tools_require_the_confirmation_argument() -> None:
    for name in ("uninstall_release", "rollback_release"):
        properties = _named(WRITE_TOOLS)[name]["input_schema"]["properties"]
        assert "confirm" in properties, f"{name} must take a confirm argument"


def test_guard_turns_anticipated_failures_into_text() -> None:
    @guard
    def refuses() -> str:
        raise safety.SafetyError("refused: gate closed")

    result = refuses()
    assert result.startswith("ERROR (SafetyError):")
    assert "gate closed" in result


def test_guard_lets_unexpected_failures_through() -> None:
    @guard
    def breaks() -> str:
        raise KeyboardInterrupt

    # Only the anticipated set is converted; a real bug must not be
    # silently reported to the model as a tool result.
    with pytest.raises(KeyboardInterrupt):
        breaks()


def test_guard_preserves_the_schema_the_model_sees() -> None:
    schema = _named(READ_TOOLS)["release_status"]
    assert set(schema["input_schema"]["properties"]) == {"name", "namespace", "revision"}
    assert "release status" in schema["description"].lower()


def test_a_refused_write_reaches_the_model_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(safety.WRITES_ENV, raising=False)
    safety.set_approval_hook(None)
    install = [t for t in WRITE_TOOLS if t.to_dict()["name"] == "install_release"][0]
    result = install.call({"chart_ref": "./chart", "name": "demo", "apply": True})
    assert "ERROR" in result
    assert safety.WRITES_ENV in result
