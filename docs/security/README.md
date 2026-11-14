# Security model

Agent skills are supply-chain artifacts. A harness loads `SKILL.md` straight into the model's context, and many skills bundle scripts the agent is told to run. Skillporter treats every third-party skill as untrusted input.

This page describes what Skillporter protects, how, and where its guarantees stop.

## Four different questions

Skillporter keeps these separate. A good answer to one says nothing about the others.

| Question | What answers it | What it tells you |
|---|---|---|
| Does the skill contain known dangerous patterns? | Static analysis (`skillporter scan`) | Known patterns were or were not found in the files. |
| Is the package well formed and contained? | Structural validation | No path traversal, no escaping symlinks, valid `SKILL.md`. |
| Is this the same content I approved? | Content integrity (`skillporter.lock`) | The bytes on disk match the pinned hashes. |
| What will the skill do when an agent runs it? | Nothing in Skillporter | Runtime behavior depends on the model, the harness and the host. |

**A clean scan does not prove a skill is safe at runtime.**

## Skillporter never runs skill code

During cloning, extraction, validation, scanning and installation, Skillporter does not execute scripts, hooks or setup files from a skill. Analysis reads files. It does not import or run them.

## Source ingestion

- Git refs are validated before use, and the repository URL is passed after an explicit `--` so it cannot be read as an option.
- Clones run with `protocol.ext.allow=never`, `core.fsmonitor=false` and `core.symlinks=false`.
- Archive members are rejected when they contain `..` traversal, absolute paths, Windows drive paths, reserved device names such as `CON` or `NUL`, NTFS alternate data streams, trailing dots or spaces, control bytes, symlinks, hardlinks or special device files.
- Names that collide after Unicode normalization or case folding are rejected.
- Extraction is bounded: 1,000 files, 10 MiB per file, 50 MiB in total.
- Extracted files are created exclusively without following links where the operating system supports it, and setuid, setgid and world-write bits are stripped.

## Installation

- Skill names are validated as single path segments, so `install`, `remove` and `rollback` cannot leave the target harness directory.
- A harness directory whose parent path escapes the workspace through a symlink is rejected.
- Multi-harness installs are staged and journaled. A failure or a killed process rolls back the unfinished part.
- State, manifest and lockfile writes are atomic: written to a temporary file in the same directory, flushed, then renamed.

## Conflict override is not risk acceptance

| Flag | Authorizes | Does not authorize |
|---|---|---|
| `--force` | Overwriting an existing destination. | Skipping a security block. |
| `--allow-risky` | Proceeding despite non-structural static findings. The findings are printed and recorded in `.skillporter/audit.jsonl`. | Structural escapes. |

`sec-symlink-escape` and `sec-path-traversal` cannot be overridden by any flag.

An incomplete scan, where a file was too large or unreadable, is never treated as a pass. Installing a partially inspected skill requires an explicit `--allow-risky`.

## MCP server boundaries

`skillporter mcp` is designed to be called by a model, so it assumes its arguments may be hostile.

- **Workspace containment.** The workspace root comes from `--root`, `SKILLPORTER_MCP_ROOT` or the server's working directory. Tool arguments cannot redefine it. Paths with `..`, escaping symlinks, UNC paths, drive paths or NUL bytes are rejected.
- **Read-only by default.** `detect`, `diagnose`, `scan`, `inspect` and `matrix` are available. `add`, `install`, `sync` and `remove` are denied unless the server is started with `--allow-writes`.
- **No remote fetches in read-only mode.** `inspect` is limited to workspace paths unless writes or remote access are enabled.
- **User scope is opt-in.** `scope="user"` requires `--allow-user-scope`.
- **Strict types.** Booleans must be JSON booleans. The strings `"false"` and `"0"` are rejected, not coerced.

See [MCP integration](../mcp/README.md).

## Audit log

Security-relevant events are appended to `.skillporter/audit.jsonl`, created with owner-only permissions on POSIX systems. URL credentials, tokens and PEM keys are scrubbed before writing. `skillporter audit` reads it back.

## Installer integrity

The standalone installer accepts immutable release tags only, verifies the SHA-256 checksum, and fails closed unless an independent check succeeds: a GitHub artifact attestation, a digest you pin yourself, or a detached signature. See [Installation](../installation/README.md).

Release artifacts are built by the repository's publish workflow, which generates Sigstore-backed build provenance attestations. You can verify a download yourself:

```bash
gh attestation verify skillporter.pyz --repo Shanmukh-l33t/skillporter
```

## Limitations

Static analysis has hard limits, and Skillporter does not hide them.

- **Novel prompt injection.** Instructions written in ordinary prose, without known override phrasing, can still steer a model. No pattern set catches all of them.
- **Runtime-fetched content.** A URL can serve harmless content when it is inspected and something else when the agent fetches it later.
- **Obfuscation.** Encoded-payload inspection is bounded. Multi-layer encoding, encryption or logic that only triggers on certain dates or inputs can evade it.
- **Host isolation.** Which tools an agent may call, and what those tools can reach, is decided by the harness and the host environment. Skillporter does not sandbox the agent.

Use the scanner to remove known hazards and to make review faster. Do not use it as the only control.

## Reporting a vulnerability

Do not open a public issue. Report privately through [GitHub Security Advisories](https://github.com/Shanmukh-l33t/skillporter/security/advisories/new). The [security policy](../../SECURITY.md) lists supported versions and response times.
