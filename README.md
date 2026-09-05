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
`claude-opus-5`).

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

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest            # offline; cluster tests auto-skip
.venv/bin/ruff check src tests
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
