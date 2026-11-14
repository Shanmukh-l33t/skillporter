# MCP integration

`skillporter mcp` runs a Model Context Protocol server over stdio. It lets an agent inspect the skills in the current workspace through structured tool calls, without shelling out.

The server is read-only unless you opt in to writes.

## Register the server

Claude Code:

```bash
claude mcp add skillporter -- uvx skillporter mcp
```

Codex:

```bash
codex mcp add skillporter -- uvx skillporter mcp
```

Any client that reads an `mcpServers` configuration:

```json
{
  "mcpServers": {
    "skillporter": {
      "command": "uvx",
      "args": ["skillporter", "mcp"]
    }
  }
}
```

The commands above assume `uvx`; the [install page](https://www.skillporter.dev/install) covers setup for `uv`, `pipx` and `npx`.

## Tools

| Tool | Access | Purpose |
|---|---|---|
| `skillporter_diagnose` | Read | Reachability, drift, duplicates and broken symlinks for the workspace. |
| `skillporter_detect` | Read | Which harnesses are installed or active. |
| `skillporter_scan` | Read | Static security assessment of a skill directory. |
| `skillporter_inspect` | Read | Structure, metadata and security posture of a skill package. |
| `skillporter_matrix` | Read | The harness compatibility matrix. |
| `skillporter_add` | Write | Resolve, scan and install a skill. |
| `skillporter_install` | Write | Install a local skill directory. |
| `skillporter_sync` | Write | Synchronize the workspace. |
| `skillporter_remove` | Write | Remove a skill. |

All nine tools are listed to the client. In the default mode, calling a write tool returns an error and changes nothing:

```text
error: MCP write operation 'skillporter_add' is disabled by default; launch with
`skillporter mcp --allow-writes` or set SKILLPORTER_MCP_ALLOW_WRITES=1 to authorize writes
```

## Enabling writes

```bash
claude mcp add skillporter -- uvx skillporter mcp --allow-writes
```

Only do this when you want the agent to install and remove skills on its own. The write tools keep the same gates as the CLI:

- `force` only overwrites an existing destination.
- `accept_risk` is a separate boolean, and it is recorded in the audit log.
- Structural escapes cannot be accepted.

## Workspace boundary

The server treats tool arguments as untrusted, because they come from a model that may have read hostile content.

- The workspace root is fixed when the server starts: `--root`, then `SKILLPORTER_MCP_ROOT`, then the working directory.
- Every path argument is resolved and must stay inside that root. A request for `../..` is refused with an `escapes workspace boundary` error.
- UNC paths, Windows drive paths, NUL bytes and symlinks that leave the workspace are rejected.
- `scope="user"` is refused unless the server was started with `--allow-user-scope`.
- In read-only mode, `skillporter_inspect` only reads workspace paths. It will not fetch a remote repository unless `SKILLPORTER_MCP_ALLOW_REMOTE=1` is set or writes are enabled.

## Options

| Flag | Environment variable | Effect |
|---|---|---|
| `--root <dir>` | `SKILLPORTER_MCP_ROOT` | Set the workspace boundary. |
| `--allow-writes` | `SKILLPORTER_MCP_ALLOW_WRITES=1` | Enable the write tools. |
| `--allow-user-scope` | `SKILLPORTER_MCP_ALLOW_USER_SCOPE=1` | Permit `scope="user"`. |
| | `SKILLPORTER_MCP_ALLOW_REMOTE=1` | Permit remote sources for `inspect` in read-only mode. |

## Type checking

Arguments are validated strictly. A boolean must be a JSON boolean, so `"false"` and `"0"` are rejected, not interpreted. Harness lists must contain registered harness IDs. Malformed JSON-RPC messages receive standard `-32700` and `-32600` errors.

## Audit trail

Tool calls that change the workspace, and any accepted risk, are written to `.skillporter/audit.jsonl` with credentials scrubbed. Review them with:

```bash
skillporter audit .
```

## Protocol details

The server speaks JSON-RPC 2.0 over stdio and reports MCP protocol version `2024-11-05`.

## Registry listing

`server.json` at the repository root is the official MCP registry manifest (schema `2025-12-11`). It registers `io.github.Shanmukh-l33t/skillporter` as the npm package `@shanmukhdheekonda/skillporter`, launched as `npx -y @shanmukhdheekonda/skillporter mcp` over stdio, read-only.

Keep the case of the GitHub account in the name (`Shanmukh-l33t`). Registry namespace grants are case-sensitive prefix matches, and GitHub authentication issues `io.github.Shanmukh-l33t/*`.

Publishing, as the owner:

```bash
curl -L "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_$(uname -s | tr '[:upper:]' '[:lower:]')_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz" | tar xz mcp-publisher
mcp-publisher login github          # device flow; from CI use login github-oidc
mcp-publisher validate server.json
mcp-publisher publish server.json
```

Ownership is proven by the `mcpName` field in the npm package that is actually published. npm `3.0.0` shipped without it, so that version cannot be registered. Publish a new npm version with the current `package.json`, set `version` and `packages[].version` in `server.json` to that version, then publish the manifest.
