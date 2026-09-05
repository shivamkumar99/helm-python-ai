"""The MCP front: registration and tier coverage of the exposed tools."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp")

from helm_ai import mcp_server

READ_TOOLS = {
    "helm_list_releases",
    "helm_release_status",
    "helm_release_manifest",
    "helm_release_history",
    "helm_release_values",
    "helm_show_chart",
    "helm_template_chart",
    "helm_lint_chart",
    "helm_search_repository",
    "helm_chart_tags",
    "helm_versions",
}
WRITE_TOOLS = {"helm_install_release", "helm_upgrade_release"}
DESTRUCTIVE_TOOLS = {"helm_uninstall_release", "helm_rollback_release"}


def test_all_tools_registered_with_schemas() -> None:
    listed = asyncio.run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in listed}
    assert names == READ_TOOLS | WRITE_TOOLS | DESTRUCTIVE_TOOLS
    assert all(tool.input_schema for tool in listed)


def test_destructive_tools_require_confirm_in_schema() -> None:
    listed = asyncio.run(mcp_server.mcp.list_tools())
    for tool in listed:
        if tool.name in DESTRUCTIVE_TOOLS:
            assert "confirm" in tool.input_schema.get("required", [])
