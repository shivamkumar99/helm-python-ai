"""The live-feedback plumbing: heartbeat reports and native-log capture."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

pytest.importorskip("anyio")

from helm_ai import feedback


def test_run_blocking_returns_value_and_reports() -> None:
    reports: list[tuple[float, str]] = []

    async def report(elapsed: float, message: str) -> None:
        reports.append((elapsed, message))

    async def scenario() -> str:
        return await feedback.run_blocking("demo op", lambda: "result", report=report)

    assert asyncio.run(scenario()) == "result"
    messages = [message for _, message in reports]
    assert messages[0] == "demo op: started"
    assert messages[-1] == "demo op: finished"


def test_run_blocking_heartbeats_while_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feedback, "HEARTBEAT_SECONDS", 0.05)
    reports: list[str] = []

    async def report(_elapsed: float, message: str) -> None:
        reports.append(message)

    asyncio.run(feedback.run_blocking("slow op", lambda: time.sleep(0.2), report=report))
    beats = [message for message in reports if "slow op: running" in message]
    assert beats, f"expected heartbeat reports, got {reports}"


def test_run_blocking_without_report_is_plain_offload() -> None:
    assert asyncio.run(feedback.run_blocking("x", lambda: 41 + 1)) == 42


def test_capture_native_logs_tracks_last_line() -> None:
    feedback.capture_native_logs(logging.INFO)
    logging.getLogger("helm_python.native").info("pulled chart %s", "demo")
    assert feedback.last_native_line() == "pulled chart demo"


def test_run_blocking_propagates_exceptions() -> None:
    async def report(_elapsed: float, _message: str) -> None:
        pass

    def boom() -> None:
        raise RuntimeError("kaput")

    scenario = feedback.run_blocking("boom op", boom, report=report)
    with pytest.raises(RuntimeError, match="kaput"):
        asyncio.run(scenario)
