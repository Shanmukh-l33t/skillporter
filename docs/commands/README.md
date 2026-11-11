# CLI Command Reference

Every Skillporter command supports `--help`, and verification commands return deterministic exit codes (`0` clean, `1` findings, `2` usage/runtime error).

## Lifecycle Commands

### `skillporter add <source>`
Resolve, validate, security-scan, and install one or more skills.
- `--harness <id|all>` (repeatable): Target harnesses. Defaults to active/manifest harnesses.
- `--skill <name>` (repeatable): Select specific skill(s) from a multi-skill repository.
- `--ref <branch|tag|sha>`: Pin a specific Git ref or commit SHA.
- `--strategy copy|symlink`: Copy (default, Docker/CI safe) or relative symlink.
- `--scope project|user`: Install into repo or `$HOME`.
- `--adapt`: Also generate adapted rule files (`.cursor/rules/*.mdc`, `.github/instructions/*.instructions.md`).
- `--dry-run`: Compute plan, validate, and run static security scan without writing files.
- `--allow-risky`: Proceed even if static security scan reports `HIGH`/`CRITICAL` findings.
- `--force`: Overwrite existing installations.
- `--json`: Machine-readable JSON output.

### `skillporter diagnose [path]`
Inspect reachability, broken symlinks, SHA-256 content drift across copies, duplicate loading within a harness, and frontmatter spec errors.

### `skillporter doctor [path] [--fix]`
Run an end-to-end workspace health check. Pass `--fix` to automatically remove broken symlinks and synchronize discovered skills across active harnesses.

### `skillporter scan [path]`
Run the static security and supply-chain scanner (`STATIC_SECURITY_ASSESSMENT`) across all discovered skills.

### `skillporter validate [path]`
Validate `SKILL.md` files against the Agent Skills specification.

### `skillporter init [path]` / `sync [path]` / `lock [path]`
- `init`: Generate `skillporter.yaml` from discovered skills and active harnesses.
- `sync`: Reconcile workspace with `skillporter.yaml` (or mirror discovered canonical skills across harnesses) and update `skillporter.lock`.
- `lock`: Write deterministic `skillporter.lock` with SHA-256 content tree hashes.

### `skillporter update [skill]` / `rollback <skill>`
- `update`: Re-fetch tracked skills from their recorded upstream source after snapshotting the current version to `.skillporter/backups/`.
- `rollback <skill>`: Restore the previous snapshot from `.skillporter/backups/` across all installed destinations.

### `skillporter search [query]` / `info <target>` / `inspect <source>` / `pack [path]`
- `search`: Search the seed and configured registry catalog.
- `info`: Show detailed adapter or registry package metadata.
- `inspect`: Inspect a local or remote package (structure, scripts, security, adapted rule previews) without installing.
- `pack`: Emit a deterministic `<name>-<version>.tar.gz` and `provenance.json` checksum manifest.
