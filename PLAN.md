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
- [ ] Publish to PyPI (after helm-python-sdk lands on PyPI — the
      dependency must be resolvable first)
- [ ] CI: lint + mypy + pytest matrix, same posture as helm-python-sdk
- [ ] Cluster e2e (kind): dry-run vs apply vs gates, agent smoke test
      with recorded transcripts
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
