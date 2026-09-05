"""The safety gate every mutating Helm operation passes through.

Three tiers govern the tool layer:

* **read** — list/status/history/values/show/template/lint: never gated.
* **write** — install/upgrade applying real changes: allowed when
  ``HELM_AI_ALLOW_WRITES=1`` is set, or when an interactive approval hook
  says yes. Without either, installs and upgrades still run — but only as
  dry runs.
* **destructive** — uninstall/rollback: additionally require the caller to
  echo the release name in ``confirm``, so a model (or a typo) cannot
  destroy a release it merely mentioned.

The environment gates exist because an MCP server has no terminal to ask
on; the hook exists so the agent CLI can ask the human at the keyboard.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from . import audit

__all__ = [
    "DESTRUCTIVE_ENV",
    "WRITES_ENV",
    "SafetyError",
    "ensure_destructive_allowed",
    "ensure_writes_allowed",
    "set_approval_hook",
]

WRITES_ENV = "HELM_AI_ALLOW_WRITES"
DESTRUCTIVE_ENV = "HELM_AI_ALLOW_DESTRUCTIVE"

_approval_hook: Callable[[str], bool] | None = None


class SafetyError(PermissionError):
    """A gated operation was attempted without the required authorization."""


def set_approval_hook(hook: Callable[[str], bool] | None) -> None:
    """Install a callable asked to approve gated operations interactively.

    The hook receives a one-line description of the pending operation and
    returns ``True`` to allow it. Pass ``None`` to remove the hook.
    """
    global _approval_hook
    _approval_hook = hook


def _hook_approves(description: str) -> bool:
    return _approval_hook is not None and _approval_hook(description)


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def ensure_writes_allowed(description: str) -> None:
    """Allow a cluster-mutating operation or raise :class:`SafetyError`."""
    if _env_enabled(WRITES_ENV) or _hook_approves(description):
        audit.emit("safety.decision", tier="write", decision="allowed", action=description)
        return
    audit.emit("safety.decision", tier="write", decision="refused", action=description)
    raise SafetyError(
        f"refused: {description}. Cluster writes are disabled by default; "
        f"set {WRITES_ENV}=1 (or approve the prompt) to apply changes, or "
        "re-run as a dry run."
    )


def ensure_destructive_allowed(description: str, name: str, confirm: str) -> None:
    """Allow a destructive operation on release ``name`` or raise.

    ``confirm`` must equal the release name exactly, and the environment
    gate (or the interactive hook) must also allow it.
    """
    if confirm != name:
        audit.emit(
            "safety.decision",
            tier="destructive",
            decision="refused",
            reason="confirm mismatch",
            action=description,
        )
        raise SafetyError(
            f"refused: {description}. Destructive operations require the "
            f'exact release name echoed back: pass confirm="{name}".'
        )
    if _env_enabled(DESTRUCTIVE_ENV) or _hook_approves(description):
        audit.emit("safety.decision", tier="destructive", decision="allowed", action=description)
        return
    audit.emit("safety.decision", tier="destructive", decision="refused", action=description)
    raise SafetyError(
        f"refused: {description}. Destructive operations are disabled by "
        f"default; set {DESTRUCTIVE_ENV}=1 (or approve the prompt) to allow "
        "uninstall/rollback."
    )
