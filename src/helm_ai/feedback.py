"""Live feedback for long-running Helm operations.

Two pieces work together so a client never watches a silent, stuck-looking
call:

* :func:`capture_native_logs` routes the Helm SDK's own log stream (the
  ``waiting for resources...`` lines Go emits during installs and waits)
  into Python logging AND keeps the most recent line available to poll.
* :func:`run_blocking` executes a blocking tool-layer call on a worker
  thread while a heartbeat coroutine reports progress every few seconds —
  elapsed time plus the latest native log line — through a caller-supplied
  callback (the MCP ``ctx.report_progress`` in the server).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, TypeVar

import helm_python as helm

__all__ = ["capture_native_logs", "last_native_line", "run_blocking"]

T = TypeVar("T")

#: Seconds between heartbeat progress reports.
HEARTBEAT_SECONDS = 5.0

_lock = threading.Lock()
_last_line = ""
_capturing = False


class _LastLineHandler(logging.Handler):
    """Remember the most recent record; emit runs on arbitrary Go threads."""

    def emit(self, record: logging.LogRecord) -> None:
        global _last_line
        try:
            message = record.getMessage()
        except Exception:
            return
        with _lock:
            _last_line = message


def capture_native_logs(level: int = logging.INFO) -> None:
    """Start mirroring the Helm SDK's log stream (idempotent).

    Records land on the ``helm_python.native`` logger (so normal logging
    configuration shows them on stderr) and the latest line is kept for
    :func:`last_native_line`.
    """
    global _capturing
    with _lock:
        if _capturing:
            return
        _capturing = True
    native_logger = logging.getLogger("helm_python.native")
    # The logger must pass records itself: without an explicit level it
    # inherits the root's (WARNING by default) and drops the info stream.
    native_logger.setLevel(level)
    native_logger.addHandler(_LastLineHandler())
    helm.enable_logging(level, logger=native_logger)


def last_native_line() -> str:
    """The most recent Helm SDK log line, or ``""`` before any arrived."""
    with _lock:
        return _last_line


async def run_blocking(
    description: str,
    fn: Callable[..., T],
    *args: Any,
    report: Callable[[float, str], Awaitable[None]] | None = None,
    **kwargs: Any,
) -> T:
    """Run ``fn`` on a worker thread, reporting liveness while it runs.

    ``report`` receives ``(elapsed_seconds, message)`` roughly every
    :data:`HEARTBEAT_SECONDS`; the message carries the latest native Helm
    log line when one exists, so waits read as "what Helm is doing", not
    silence. Without ``report`` this is just a thread offload.
    """
    import anyio  # deferred: only the MCP server extra installs it

    call = partial(fn, *args, **kwargs)
    if report is None:
        return await anyio.to_thread.run_sync(call)

    start = time.monotonic()
    finished = anyio.Event()
    await report(0.0, f"{description}: started")

    async def heartbeat() -> None:
        while True:
            with anyio.move_on_after(HEARTBEAT_SECONDS):
                await finished.wait()
                return
            elapsed = time.monotonic() - start
            detail = last_native_line()
            message = (
                f"{description}: {detail} ({elapsed:.0f}s)"
                if detail
                else f"{description}: running for {elapsed:.0f}s"
            )
            await report(elapsed, message)

    # The worker swallows its own exception into a box so the task group
    # never raises an ExceptionGroup (Python 3.10 has no except* to unwrap
    # it); the original exception is re-raised as itself below.
    outcome: list[T] = []
    failure: list[BaseException] = []

    async def work() -> None:
        try:
            outcome.append(await anyio.to_thread.run_sync(call))
        # Broad by design: cancellation and crashes alike are re-raised
        # by the caller once the heartbeat has stopped.
        except BaseException as exc:  # NOSONAR(S5754)
            failure.append(exc)
        finally:
            finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(heartbeat)
        task_group.start_soon(work)

    if failure:
        raise failure[0]
    await report(time.monotonic() - start, f"{description}: finished")
    return outcome[0]
