# helm-python-ai

AI tooling for [Helm v4](https://helm.sh), built on
[helm-python-sdk](https://github.com/shivamkumar99/helm-python-sdk) — the
Python binding over Helm's real Go SDK. No `helm` binary, no `kubectl`, no
shelling out.

Two fronts share one safety-tiered tool layer:

| Command | What it is | Runtime |
|---|---|---|
| `helm-ai-mcp` | An MCP server exposing Helm operations to any MCP client (Claude Code, Claude Desktop, …) | [`mcp`](https://pypi.org/project/mcp/) ≥ 2 |
| `helm-ai-agent` | An autonomous agent that investigates and operates releases from a plain-language mission | [`anthropic`](https://pypi.org/project/anthropic/) |

```
helm (Go SDK) → helm-c-sdk (C ABI) → helm-python-sdk (ctypes) → helm-python-ai
                                                                 ├─ helm-ai-mcp    (MCP server)
                                                                 └─ helm-ai-agent  (agent CLI)
```

## Install

```bash
pip install "helm-python-ai[all]"       # both fronts
pip install "helm-python-ai[server]"    # MCP server only
pip install "helm-python-ai[agent]"     # agent only
```

Python ≥ 3.10. The native Helm library ships inside the `helm-python-sdk`
wheel — nothing else to install.

## The MCP server

Register in your MCP client (stdio transport):

```json
{
  "mcpServers": {
    "helm": {
      "command": "helm-ai-mcp"
    }
  }
}
```

Fifteen tools in three tiers:

* **Read (always available):** `helm_list_releases`, `helm_release_status`,
  `helm_release_manifest`, `helm_release_history`, `helm_release_values`,
  `helm_show_chart`, `helm_template_chart`, `helm_lint_chart`,
  `helm_search_repository`, `helm_chart_tags`, `helm_versions`.
* **Write (dry-run by default):** `helm_install_release`,
  `helm_upgrade_release`. They run as server-side dry runs unless called
  with `apply=true` **and** the server environment sets
  `HELM_AI_ALLOW_WRITES=1`.
* **Destructive (double-gated):** `helm_uninstall_release`,
  `helm_rollback_release`. They require `confirm=<release name>` echoed
  exactly **and** `HELM_AI_ALLOW_DESTRUCTIVE=1` in the server environment.

Cluster access uses the standard kubeconfig resolution (`KUBECONFIG`, then
`~/.kube/config`, then in-cluster).

### Live feedback

Long-running tools (installs, upgrades, registry operations) are async and
send MCP **progress notifications** every few seconds while they run —
elapsed time plus the Helm SDK's own live log line ("waiting for
resources…") — so the host can show real activity instead of a call that
looks stuck.

### Releases dashboard (MCP Apps)

`helm_list_releases` ships an [MCP Apps](https://modelcontextprotocol.io)
(SEP-1865) UI: hosts that support the extension — Claude among them —
render the releases as an interactive table (status badges, revisions,
chart versions) directly in the conversation. Hosts without the extension
see the same JSON text as before; nothing is lost.

### Docker

```bash
docker build -t helm-ai-mcp .
```

The multi-stage build compiles the native Helm library for the image's own
architecture (amd64 and arm64 both work), assembles the Python stack, and
ships a slim non-root runtime. Supply-chain inputs are pinned: base images
by manifest digest, and the helm-python-sdk clone is verified against the
exact commit its version tag pointed to — a moved tag fails the build.
Only helm-python-sdk is pinned; the helm-c-sdk version is read from
helm-python-sdk's own `EXPECTED_HELM_C_VERSION` pin, so the native
dependency stays owned by the package that declares it. (Once
helm-python-sdk is on PyPI, the build reduces to installing it — the
sdist vendors and compiles helm-c itself.)

Run it with least privilege (no capabilities, no privilege escalation,
read-only root filesystem, tmpfs scratch space):

```json
{
  "mcpServers": {
    "helm": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--init",
               "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges",
               "--tmpfs", "/tmp", "--tmpfs", "/home/helm",
               "-v", "/home/you/.kube/config:/home/helm/.kube/config:ro",
               "helm-ai-mcp"]
    }
  }
}
```

`docker-compose.yml` wraps the same image for `docker compose run --rm
helm-mcp` (compose `run`, not `up`: stdio servers are launched by their
client) with the same hardening baked in (`cap_drop: [ALL]`,
`no-new-privileges`, `read_only`, tmpfs mounts, `pids_limit`). Pass
`-e HELM_AI_ALLOW_WRITES=1` / `-e HELM_AI_ALLOW_DESTRUCTIVE=1` only when
you mean it, and prefer mounting a kubeconfig whose RBAC matches the tier
you enabled.

## The agent

```bash
export ANTHROPIC_API_KEY=...   # or an active `ant auth` profile
helm-ai-agent "why is release payments-api failing in namespace prod?"
```

The agent investigates with the read-only tools first, cites evidence
(revisions, values diffs, manifest details), dry-runs any change it
proposes, and asks at the keyboard before applying or destroying anything:

```
  → list_releases {"namespace": "prod"}
  → release_history {"name": "payments-api", "namespace": "prod"}
  → release_values {"name": "payments-api", "revision": 6}

APPROVAL NEEDED: helm upgrade payments-api ./charts/payments (namespace=prod)
Proceed? [y/N]
```

`--yes` auto-approves gated operations (for scripted use, together with the
environment gates); `--model` selects the Claude model (default
`claude-opus-5`); `-v/--verbose` streams the Helm SDK's own log lines to
stderr while operations run.

## Security model

The design follows the
[MCP security best practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices)
and the OWASP GenAI *Practical Guide for Secure MCP Server Development*
(v1.0, Feb 2026):

* **stdio transport only.** The server is a local child process of its MCP
  client; it never opens a network socket, so the remote-transport attack
  classes (token passthrough, confused deputy, session hijacking) do not
  arise. Do not put it behind an HTTP proxy without adding authentication.
* **Structured, schema-validated invocation.** Every tool has a typed JSON
  schema; values documents are size-capped (1 MB) and must parse to a JSON
  object; release names are validated by Helm's own rules before use.
* **Least privilege by default.** Read tools are ungated; writes are
  dry-run unless explicitly enabled; destructive operations are
  double-gated (exact-name confirmation + a separate environment flag).
  For defense in depth, run the server with a kubeconfig whose RBAC
  matches the tier you enabled — a read-only account when the gates are
  off.
* **Human in the loop.** The agent pauses for keyboard approval on every
  write/destructive operation; over MCP (no terminal), the environment
  gates are the authorization channel and the client's own approval UI
  governs tool use.
* **No secrets in the model's reach.** No tool accepts or returns
  credentials. Registry and cluster credentials come from Helm's and
  Kubernetes' own configuration files; there is no login tool, and error
  messages carry Helm's detail strings, not tracebacks.
* **Untrusted data stays data.** Chart READMEs, notes, values, and
  manifests are cluster-controlled input. The agent's system prompt pins
  them as data-not-instructions; treat MCP tool output the same way in
  your client.
* **Resource limits.** Install/upgrade waits are capped (300 s default)
  and tool output is truncated at 200 K characters with an explicit
  marker, so a wedged rollout or a huge manifest cannot hang the process
  or flood the model's context.
* **Audit trail.** Every allow/refuse decision and every mutating
  operation (with parameters) is logged to stderr, where the MCP host
  captures it — stdout stays reserved for protocol framing.

## Observability & audit

Instrumentation is vendor-neutral OpenTelemetry; no backend is bundled.

* **Tracing** — the MCP SDK emits a span per inbound message
  (`tools/call helm_install_release`, GenAI `execute_tool` attributes,
  W3C trace-context propagation from the caller), and the tool layer adds
  a nested span per operation. The agent wraps each mission in an
  `invoke_agent` span carrying `gen_ai.usage.input_tokens`/
  `output_tokens` and turn count. Export activates only when the standard
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set and the `observability` extra is
  installed (`pip install helm-python-ai[observability]`); point it at
  any OTLP backend (Grafana/Tempo, Jaeger, Langfuse, Datadog, ...).
* **Audit trail** — every tool invocation (with an allowlisted argument
  snapshot; values payloads are recorded as sizes only, never content),
  every safety allow/refuse decision, every MCP request outcome, and each
  agent mission produce structured JSON events on the `helm_ai.audit`
  logger (stderr) and, when `HELM_AI_AUDIT_LOG=/path/file.jsonl` is set,
  an append-only JSONL file. Events carry the active trace/span IDs, so
  audit records and traces cross-reference.
* **Metrics** — `helm_ai.tool.calls` (by tool and outcome) and a
  `helm_ai.tool.duration` histogram flow through the same OTLP pipeline;
  refusal spikes and error rates are the signals worth alerting on.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest            # offline; cluster tests auto-skip
.venv/bin/ruff check src tests
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
