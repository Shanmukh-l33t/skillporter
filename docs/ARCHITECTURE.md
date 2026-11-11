# Architecture

See the root [ARCHITECTURE.md](../ARCHITECTURE.md) and [ARCHITECTURE_REVIEW.md](../ARCHITECTURE_REVIEW.md) for the full system diagram and architectural audit.

## Module Layering (Zero Runtime Dependencies)

```
cli.py / ui.py / mcp_server.py     User & agent interfaces, exit codes, JSON/ANSI output
   |
   +-- diagnose.py                 Reachability, SHA-256 content drift, duplicates, explicit states
   +-- install.py                  Staged transactional copy/symlink, rollback, path-segment guard
   +-- sources.py                  GitHub, Git URL, bounded ZIP/tar extraction, local/registry
   +-- security.py                 SHA-256 tree hashing (no-follow-links) & static pattern scan
   +-- frontmatter.py / formats.py Line-anchored YAML frontmatter, spec validator, rule adaptation
   +-- state.py / manifest.py      .skillporter/state.json, backups, skillporter.yaml & .lock
   +-- registry.py                 Seed catalog, bounded remote JSON index, immutable .tar.gz pack
   +-- atomic.py                   Crash-safe atomic_write_text (os.replace+fsync) & workspace_lock
   |
   +-- harnesses.py                19-harness declarative adapter registry & extension SDK
```

## Key Invariants

1. **Single Authoritative Core**: All CLI, `npx`, `uvx`, standalone `.pyz`, GitHub Action, and MCP operations execute the Python standard-library core in `skillporter/`.
2. **Staged & Reversible Transactions**: Directory installations stage into `.skillporter/tmp/txn-<id>/` and preserve any overwritten targets in `prev-<id>` slots until the entire multi-harness transaction succeeds; any failure restores both newly created and overwritten directories to their exact pre-transaction state.
3. **Stop-at-Skill-Root Discovery**: `discover()` halts recursion inside a directory once `SKILL.md` is found and tracks `(st_dev, st_ino)` inodes to prevent symlink infinite loops.
