#!/usr/bin/env python3
"""Dynamic security check: drive the MCP server with hostile inputs.

Static analysis cannot see how the served surface behaves at runtime, so
this probe connects a real MCP client to the server in-process and
attacks it: malformed and oversized values documents, confirm-echo
violations, invalid release names, unreadable chart paths, and an
unknown tool. Every attack must produce a typed, bounded tool error —
never a hang, a crash, an unhandled traceback on the wire, or a leaked
native handle.

Runs standalone in CI: exit 0 on success, 1 with a report on failure.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import helm_python as helm
from mcp import Client
from mcp.shared.exceptions import MCPError

FAILURES: list[str] = []

#: A path that is guaranteed not to be a chart.
MISSING_CHART = "/nonexistent"

#: Nothing here talks to a network or cluster; the whole probe must fly.
OVERALL_TIMEOUT_SECONDS = 120


def check(condition: bool, label: str) -> None:
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        FAILURES.append(label)


async def expect_tool_error(client: Client, tool: str, args: dict, label: str, needle: str) -> None:
    """The call must fail as a tool error whose message carries ``needle``."""
    try:
        result = await client.call_tool(tool, args)
    except MCPError as exc:
        check(needle.lower() in str(exc).lower(), f"{label} (protocol error carries detail)")
        return
    text = result.content[0].text if result.content else ""
    check(bool(result.is_error), f"{label} (is_error set)")
    check(needle.lower() in text.lower(), f"{label} (message names the cause)")


async def attack() -> None:
    from helm_ai import mcp_server

    async with Client(mcp_server.mcp) as client:
        # Baseline: the server is alive and typed.
        result = await client.call_tool("helm_versions", {})
        check(not result.is_error, "baseline helm_versions succeeds")

        await expect_tool_error(
            client,
            "helm_template_chart",
            {"chart_path": MISSING_CHART, "values": "not an object"},
            "non-object values refused by schema",
            "valid",
        )
        await expect_tool_error(
            client,
            "helm_template_chart",
            {"chart_path": MISSING_CHART, "values": [1, 2]},
            "list values refused by schema",
            "valid",
        )
        await expect_tool_error(
            client,
            "helm_template_chart",
            {"chart_path": MISSING_CHART, "values": {"pad": "x" * 1_100_000}},
            "oversized values refused",
            "exceeds",
        )
        await expect_tool_error(
            client,
            "helm_uninstall_release",
            {"name": "demo", "confirm": "not-demo"},
            "confirm mismatch refused",
            "exact release name",
        )
        await expect_tool_error(
            client,
            "helm_uninstall_release",
            {"name": "demo", "confirm": "demo"},
            "ungated destructive refused",
            "HELM_AI_ALLOW_DESTRUCTIVE",
        )
        await expect_tool_error(
            client,
            "helm_install_release",
            {"chart_ref": "./x", "name": "demo", "apply": True},
            "ungated apply refused",
            "HELM_AI_ALLOW_WRITES",
        )
        await expect_tool_error(
            client,
            "helm_install_release",
            {"chart_ref": "./x", "name": "UPPER_not-valid!"},
            "invalid release name refused",
            "name",
        )
        await expect_tool_error(
            client,
            "helm_template_chart",
            {"chart_path": "/etc/passwd"},
            "non-chart path refused",
            "",
        )

        # Unknown tools are a protocol-level error, not a crash.
        try:
            unknown = await client.call_tool("helm_rm_rf", {})
            check(bool(unknown.is_error), "unknown tool refused")
        except MCPError:
            check(True, "unknown tool refused")

        # A legitimate render still works after all the abuse.
        with tempfile.TemporaryDirectory() as tmp:
            helm.Chart.create("probe", tmp).close()
            rendered = await client.call_tool(
                "helm_template_chart", {"chart_path": f"{tmp}/probe"}
            )
            check(not rendered.is_error, "server still healthy after attacks")

    check(helm.open_handles_count() == 0, "no native handles leaked")


def main() -> int:
    os.environ.pop("HELM_AI_ALLOW_WRITES", None)
    os.environ.pop("HELM_AI_ALLOW_DESTRUCTIVE", None)
    try:
        asyncio.run(asyncio.wait_for(attack(), timeout=OVERALL_TIMEOUT_SECONDS))
    except TimeoutError:
        FAILURES.append(f"probe hung past {OVERALL_TIMEOUT_SECONDS}s")
    if FAILURES:
        print(f"\nDAST FAILED: {len(FAILURES)} finding(s)")
        for failure in FAILURES:
            print(" -", failure)
        return 1
    print("\nDAST passed: all hostile inputs produced typed, bounded refusals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
