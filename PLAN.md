# helm-python-ai — plan

The AI layer over helm-python-sdk. One shared, safety-tiered tool layer
(`helm_ai.tools` + `helm_ai.safety`), two fronts.

## 1. Architecture

```
helm (Go SDK) → helm-c-sdk (C ABI) → helm-python-sdk (ctypes) → helm-python-ai
```

* `tools.py` — plain functions over `helm_python`; JSON-serializable
  results; raises `HelmError`/`SafetyError`. Presentation belongs to the
  fronts.
* `safety.py` — three tiers: read (ungated), write (dry-run unless
  `HELM_AI_ALLOW_WRITES=1` or interactive approval), destructive
  (`confirm=<name>` echo + `HELM_AI_ALLOW_DESTRUCTIVE=1` or approval).
  Audit log on `helm_ai.audit`.
* `mcp_server.py` — `mcp` ≥ 2 (`MCPServer`), stdio only, 15 tools.
* `agent.py` — Anthropic SDK tool runner, 14 tools, terminal approval
  hook, evidence-first system prompt.

## 2. Status

- [x] Repo scaffolding, packaging (hatchling, extras: server/agent/all/dev)
- [x] Shared tool layer with safety tiers and audit logging
- [x] MCP server on the 2.x SDK (`MCPServer`, `run(transport="stdio")`)
- [x] Agent CLI (`helm-ai-agent`) with approval hook and tool-call trace
- [x] Security hardening pass against the MCP security best practices
      (2026-07-28) and the OWASP GenAI secure-MCP-server guide v1.0:
      input size caps, strict values parsing, release-name validation,
      output clamping, default timeouts, stderr audit trail
- [x] Offline test suite (safety gates, chart tools, leak gate);
      cluster-dependent tests auto-skip
- [x] Client feedback: async long-running tools with progress-notification
      heartbeats fed by the Helm SDK's log-callback bridge
      (`feedback.py`); MCP Apps (SEP-1865) releases dashboard
      (`apps_html.py`); agent live narration + `--verbose` native logs
- [x] Docker: multi-stage Dockerfile (arch-native build of libhelm_c,
      non-root slim runtime) + compose wrapper for `docker compose run`
- [x] Docker security pass: digest-pinned bases, commit-verified clone,
      helm-c version derived from helm-python-sdk's own pin, venv
      installers stripped + msgpack floor, system pip/ensurepip removed
      from runtime, least-privilege runtime (cap_drop ALL,
      no-new-privileges, read_only, tmpfs, pids_limit, init) verified
      working. Base images since moved to Docker Hardened Images
      (dhi.io/python 3.13, Debian/glibc: -dev builds the venv, the
      no-shell non-root runtime variant ships) — trivy HIGH/CRITICAL
      dropped 54 → 10 (Python 0, none fixable; residue is
      ncurses/expat/uuid libs Debian has no fix for), image 744 → 632 MB.
      Pulling dhi.io needs a free Docker login
- [x] Observability & audit: vendor-neutral OTLP wiring (`telemetry.py`,
      env-gated, `observability` extra), structured JSONL audit trail
      with trace correlation (`audit.py`: tool.call/safety.decision/
      mcp.request/agent.mission events, allowlisted args), tool-layer
      spans + metrics, agent `invoke_agent` span with token usage, MCP
      AuditMiddleware, anticipated errors surfaced verbatim via ToolError.
      Backend deliberately unbundled (OTEL_EXPORTER_OTLP_ENDPOINT).
- [x] helm-python-sdk 0.2.1 published to PyPI (all three wheels + sdist,
      GitHub release with the published files) — the dependency resolves,
      CI installs it from PyPI, and the trivy image-scan gate is in CI
- [x] Pure-pip Docker build: helm-c-sdk v0.2.2 (five platforms) and
      helm-python-sdk 0.2.2 (five wheels incl. linux-arm64) shipped, so
      the golang stage and source clone chain are gone — the DHI dev
      stage installs from PyPI and the hardened runtime ships it
      (632 → 486 MB, trivy fixable 0)
- [x] Published: helm-python-ai 0.1.0 on PyPI (wheel + sdist, trusted
      publishing, GitHub release) — verified by a clean-venv
      `pip install helm-python-ai[all]` pulling helm-python-sdk 0.2.2
- [x] CI: lint + mypy + 3-OS pytest matrix (deps from PyPI), bandit SAST,
      pip-audit, gitleaks, in-process DAST probe (scripts/dast_check.py),
      trivy image scan gate (fixable HIGH/CRITICAL fail); SonarQube local
      analysis clean (0 issues, quality gate OK)
- [x] Cluster e2e (kind): dry-run leaves no trace, gated
      install/upgrade/rollback/uninstall lifecycle through the tool layer
      and over the MCP wire, leak gate — green against a local kind
      cluster; CI job added (helm/kind-action)
- [ ] Optional: MCP elicitation-based confirmation once broadly supported
      by clients, replacing the env-only channel over MCP

## 3. Decisions

* **Python over Go for this layer** — it consumes and showcases
  helm-python-sdk; the AI ecosystem argument applies to the agent.
  (A Go MCP server directly on the Helm SDK remains a valid alternative
  with better binary distribution; revisit if installation friction
  matters more than stack reuse.)
* **Official `mcp` SDK (2.x)** rather than the standalone FastMCP fork —
  fewest dependencies; sync tools run on worker threads, which suits the
  blocking ctypes calls.
* **One repo for server + agent** — identical dependencies, security
  envelope, and release cadence; the shared tool layer makes a split
  artificial. Split only if they diverge.
* **kwargs surfaces stay** — mirrors helm-python-sdk's decided style.
