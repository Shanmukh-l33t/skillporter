# Architecture

Skillporter is a local-first Python 3.9+ program with no runtime dependencies. One core implements the behavior. The CLI, the `uvx` and `npx` launchers, the standalone zipapp, the GitHub Action and the MCP server are thin entry points into it.

```text
  CLI        npx launcher     GitHub Action     MCP server (stdio)
   |              |                 |                  |
   +--------------+--------+--------+------------------+
                           |
              cli.py -> skillporter/commands/*
                           |
   +-----------+-----------+-----------+-----------+-----------+
   |           |           |           |           |           |
 sources    security    install     manifest    diagnose    harnesses
 resolve    analyze     transact    lock        compare     adapters
```

## Principles

1. **One core.** All behavior lives in `skillporter/` and uses the standard library only: `ast`, `argparse`, `hashlib`, `json`, `pathlib`, `subprocess`, `tarfile`, `zipfile` and others.
2. **Commands are thin.** `cli.py` defines the argument schema and dispatches to handlers in `skillporter/commands/`. Handlers call domain modules and format output.
3. **Writes are crash-safe.** State, manifest, lockfile and journal writes go to a temporary file in the same directory, are flushed, and are renamed into place.
4. **Mutations are serialized.** A re-entrant cross-process workspace lock wraps anything that changes the workspace: `flock` on POSIX, `msvcrt` locking on Windows.
5. **Untrusted input is never executed.** Source resolution, extraction, validation and scanning read files. They do not run them.

## Modules

| Module | Responsibility |
|---|---|
| `cli.py`, `commands/` | Argument parsing, dispatch, text and JSON output, exit codes. |
| `sources.py` | Resolving GitHub shorthand, Git URLs, archives and local paths. Hardened extraction. |
| `security.py`, `scanner_analyzers.py` | Risk scoring, completeness tracking, Python AST, JavaScript, Markdown, encoded-payload and cross-file analyzers, SARIF export. |
| `install.py`, `atomic.py`, `state.py` | Transactional planner and installer, shared-directory ownership, backups, crash recovery, rollback. |
| `manifest.py`, `resolver.py` | `skillporter.yaml` parsing, `skillporter.lock` validation, reproducibility checks, dependency resolution. |
| `harnesses.py` | The adapter registry and the declarative adapter loader. |
| `diagnose.py` | Reachability, drift and duplicate detection. |
| `formats.py`, `frontmatter.py` | Specification validation and adapted rule file export. |
| `mcp_server.py` | The JSON-RPC stdio server with read and write separation. |
| `audit.py` | The scrubbed `.skillporter/audit.jsonl` event log. |

## An install, step by step

1. `sources.py` resolves the source into a temporary directory and records the commit.
2. `frontmatter.py` validates each `SKILL.md`.
3. `security.py` runs the static assessment. A blocking result stops here.
4. `install.py` plans destinations and deduplicates shared directories.
5. Content is staged under `.skillporter/tmp/txn-<id>/` and `journal.json` records every path that will be created or replaced.
6. Directories are moved into place. Replaced content is kept until the whole transaction succeeds.
7. `state.py` records what is managed, and `manifest.py` updates the lockfile when `sync` or `lock` runs.

If any destination fails, the earlier ones are restored. If the process dies, `recover_interrupted_transactions()` rolls back the unfinished transaction on a later run.

## Skill discovery

Discovery stops descending once it finds a `SKILL.md`, so a skill's own subdirectories are not mistaken for more skills. It tracks device and inode numbers to avoid symlink loops, and it skips directories such as `.git` and `node_modules`.

## Adapters are data

Each harness is a declarative record: the paths it reads, their scope and precedence, capabilities, detection rules, support type, verification tier and a link to vendor documentation. The CLI matrix, the installer's destination planning and the compatibility table on the website all come from that one registry.

## The website

The site in `website/` is a static build that reads its harness, CLI and release data from files generated out of the Python sources. It ships nothing into the Python package. See `website/README.md`.

The full design notes are in [ARCHITECTURE.md](../../ARCHITECTURE.md) at the repository root.
