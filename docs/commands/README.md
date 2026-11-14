# CLI reference

```
skillporter <command> [options]
```

Every command accepts `--help`, `-q` / `--quiet`, `-v` / `--verbose`, and `--no-color`. Most commands accept `--json` (or `--format json`) for machine-readable output.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Clean, or the operation succeeded. |
| `1` | A policy or diagnostic finding: drift, broken symlink, spec error, security block, lockfile mismatch, dependency cycle or conflict. |
| `2` | Usage or runtime error: invalid argument, unknown harness, missing path. |

The split between `1` and `2` lets CI distinguish "the check failed" from "the check could not run".

## Installing and removing

### `skillporter add <source>`

Resolve a source, validate it, run the static security assessment and install the selected skills.

```bash
skillporter add anthropics/skills --skill pdf --harness all
```

| Option | Description |
|---|---|
| `--harness <id>` | Target harness, or `all`, `compatible`, or `detected`. Repeat the flag for several harnesses. |
| `--exclude-harness <id>` | Exclude specific harnesses from target selection. Repeatable or comma-separated. |
| `--on-conflict fail\|skip\|overwrite` | Conflict policy when a destination already exists (`fail` by default). |
| `--isolated` | Prefer dedicated harness folders (such as `.cursor/skills`) over shared `.agents/skills`. |
| `--custom-path <harness=rel/dir>` | Override a harness install directory within the active scope. |
| `--skill <name>` | Select a skill from a repository that contains several. Repeatable. |
| `--ref <ref>` | Git branch, tag or commit to resolve. |
| `--strategy copy\|symlink` | `copy` is the default and is safe in Docker and CI. `symlink` creates relative links. |
| `--scope project\|user` | Install into the repository or into your home directory. |
| `--path <dir>` | Repository root. Defaults to the current directory. |
| `--adapt` | Also write adapted rule files for harnesses that use them. |
| `--dry-run` | Plan, validate and scan without writing files. |
| `--max-risk-score <n>` | Fail when a skill's risk score exceeds `n`. |
| `--engine auto\|skillspector\|static` | Scanner engine. `static` is the built-in engine. |
| `--offline` | Use the built-in scanner only. |
| `--allow-risky` | Accept non-structural security findings. The decision is recorded in the audit log. |
| `--force` | Overwrite an existing installation. It never bypasses a security block. |

See [Skill management](../skill-management/README.md) for the accepted source formats.

### `skillporter install <skill-dir>`

Install a local skill directory. `--harness` is required. It accepts `--strategy`, `--scope`, `--path`, `--adapt`, `--dry-run`, `--allow-risky` and `--force` with the same meaning as `add`.

```bash
skillporter install ./skills/release-notes --harness claude-code --harness codex
```

### `skillporter remove <skill>`

Remove a skill from one or more harnesses. `uninstall` is an alias. A shared `.agents/skills` copy is kept while another managed harness still owns it.

```bash
skillporter remove pdf --harness cursor
```

Options: `--harness`, `--exclude-harness`, `--scope`, `--path`, `--dry-run`.

### `skillporter move <skill>`

Move an installed skill from one set of harnesses to another atomically (`--from` and `--to` are required). Pass `--isolated` when moving to a harness with a dedicated folder (such as `.cursor/skills` or `.gemini/skills`) without sharing `.agents/skills`.

```bash
skillporter move pdf --from claude-code --to cursor --isolated
```

Options: `--from`, `--to`, `--exclude-harness`, `--scope`, `--strategy`, `--path`, `--on-conflict`, `--force`, `--isolated`, `--custom-path`, `--dry-run`.

### `skillporter adopt [skills...]`

Bring existing unmanaged on-disk skills under Skillporter tracking (`state.json` and `skillporter.yaml`) after running specification validation and static security scanning.

```bash
skillporter adopt --all
```

Options: `--all`, `--path`, `--scope`, `--allow-risky`.

### `skillporter outdated [skill]`

Compare managed skills against their upstream sources (version, commit, and SHA-256 tree hash) without modifying any files.

```bash
skillporter outdated
```

Options: `--path`, `--scope`.

### `skillporter update [skill]`

Fetch tracked skills from their recorded source again, run the security gate, snapshot the current version and replace it. Without a skill name it updates every tracked skill.

Options: `--scope`, `--path`, `--dry-run`, `--allow-risky`.

### `skillporter rollback <skill>`

Restore a skill from its most recent snapshot in `.skillporter/backups/`. Pass `all` to roll back every skill.

```bash
skillporter rollback pdf --dry-run
```

Options: `--backup-id <id>`, `--scope`, `--path`, `--dry-run`.

## Manifest and lockfile

### `skillporter init [path]`

Write `skillporter.yaml` from the skills and harnesses found in the workspace. `--force` overwrites an existing manifest.

### `skillporter sync [path]`

Reconcile the workspace with the manifest, resolve dependencies and write `skillporter.lock`.

| Option | Description |
|---|---|
| `--harness <id>` | Limit synchronization to specific harnesses. |
| `--strategy copy\|symlink` | Installation strategy. |
| `--scope project\|user` | Scope to synchronize. |
| `--prefer <path>` | The copy to treat as authoritative when copies differ. |
| `--dry-run` | Preview without modifying files. |
| `--max-risk-score <n>` | Fail when a skill's risk score exceeds `n`. |
| `--allow-risky` | Accept non-structural security findings. |
| `--force` | Overwrite drifted copies after snapshotting them. |

See [Synchronization](../synchronization/README.md).

### `skillporter lock [path]`

Write `skillporter.lock`. With `--check`, write nothing and exit `1` when the lockfile is stale or the files on disk no longer match it.

```bash
skillporter lock --check
```

### `skillporter graph [path]`

Print the resolved dependency graph and the topological install order. `--json` exports it.

## Inspecting a workspace

### `skillporter diagnose [path]`

Show which harnesses can see each skill, and report broken symlinks, content drift, duplicate loading and specification errors.

```bash
skillporter diagnose . --harness claude-code --harness codex
```

Options: `--harness` (repeatable, or `all`), `--scope`.

### `skillporter doctor [path]`

Run the full health check. `--fix` repairs missing or drifted installs and removes broken symlinks. `--dry-run` previews the repair.

### `skillporter status [path]`

Summarize the manifest, the lockfile, detected harnesses, drift and the per-harness installed and locked state.

### `skillporter list [path]`

List installed and discovered skills with their content hash and the harnesses that have them.

### `skillporter audit [path]`

Report each installed skill's origin and security posture, lockfile integrity, and recent events from `.skillporter/audit.jsonl`. `--limit <n>` caps the number of events.

### `skillporter detect [path]`

Detect installed harnesses. `--all` includes harnesses that were not found. `--versions` probes CLI versions where a binary exists.

### `skillporter matrix`

Print the harness compatibility and verification matrix. `--category coding|autonomous` filters it.

### `skillporter info <target>`

Show detailed metadata for a harness adapter, a registry package or a local skill.

```bash
skillporter info cursor
```

### `skillporter inspect <source>`

Inspect a local or remote package without installing it: structure, bundled scripts and security posture. `--preview-adapt <format>` prints how the skill would look as an adapted rule file. Formats: `cursor-mdc`, `copilot-instructions`, `windsurf-rules`, `continue-rules`, `aider-conventions`.

### `skillporter explain <finding>`

Explain a diagnostic, lockfile or security finding code and print the commands that fix it.

```bash
skillporter explain DRIFT
skillporter explain sec-curl-pipe-sh
```

## Security

### `skillporter scan [path]`

Run the static security assessment on every discovered skill.

```bash
skillporter scan . --format sarif > skillporter.sarif
```

Options: `--format text|json|sarif`, `--max-risk-score <n>`, `--engine`, `--offline`.

### `skillporter validate [path]`

Validate `SKILL.md` files against the Agent Skills specification and compute the risk score. It accepts the same options as `scan`.

### `skillporter sandbox run <skill>`

Experimental. Produces a non-mutating dry-run trace of what a skill's instructions and scripts reference. It does not execute the skill and is not a runtime sandbox. Treat its output as a hint.

See [Security scanning](../security-scanning/README.md) for finding codes and scoring.

## Portable environments and profiles

### `skillporter export [output.skillpack]`

Package your managed skill environment into a self-contained, SHA-256 verified `.skillpack` archive (`skillpack.json` + deduplicated `skills/<name>/` contents + lockfile metadata + saved profiles). Automatically strips `.env*`, private keys, and `.git/`, and refuses to export skills containing embedded credentials.

```bash
skillporter export my-environment.skillpack
skillporter export personal.skillpack --scope user
```

Options: `--path`, `--scope`, `--skill` (repeatable), `--managed-only`, `--manifest-only`.

### `skillporter import <file.skillpack>`

Validate archive structure and per-file SHA-256 hashes, run static security checks on every skill without executing scripts, detect missing harnesses on the destination machine, and restore the environment offline.

```bash
skillporter import my-environment.skillpack --dry-run
skillporter import my-environment.skillpack --only-detected --on-conflict skip
```

Options: `--path`, `--scope`, `--harness`, `--exclude-harness`, `--only-detected`, `--on-conflict fail|skip|overwrite`, `--force`, `--dry-run`, `--preview`, `--allow-risky`, `--max-risk-score`, `--no-manifest`.

### `skillporter diff <target>`

Compare the current workspace (or `--base`) against a `.skillpack` archive, another workspace directory, or `profile:<name>`. Exits `0` when identical and `1` when differences exist.

```bash
skillporter diff my-environment.skillpack
```

Options: `--base`, `--scope`.

### `skillporter profile <list|save|show|use|delete>`

Manage named skill environments stored as standard `ProjectManifest` YAML files under `.skillporter/profiles/<name>.yaml`.

```bash
skillporter profile save security-review
skillporter profile list
skillporter profile use security-review --prune
```

### `skillporter harness <list|inspect|status>`

Inspect supported, compatible, detected, selected, and configured harnesses, including shared `.agents/skills` peers and isolated path options.

```bash
skillporter harness list --detected
skillporter harness inspect cursor
skillporter harness status
```

### `skillporter self-skill [install|show|path]`

Install or view the official bundled `skillporter` AI agent skill so coding agents can operate Skillporter directly.

```bash
skillporter self-skill install --harness detected
```

## Packaging and catalog

### `skillporter pack [path]`

Build a deterministic `.tar.gz` bundle and a `provenance.json` manifest with the archive hash, tree hash and per-file hashes. `--out <dir>` sets the output directory.

### `skillporter search [query]`

Search the built-in seed catalog, or the index named by `SKILLPORTER_REGISTRY_URL`. `--category` filters results.

### `skillporter publish [path]`

Validate, security-gate and pack a skill for a registry index you configure with `--registry`. `--dry-run` verifies the contract without publishing. Skillporter does not operate a hosted public registry.

## Automation

### `skillporter ci-report [path]`

Generate a Markdown or JSON report of reachability, security and lockfile state for a pull request. `--output <file>` writes it to disk. `--github-repo <owner/repo>` with `--pr <number>` posts it as a comment.

### `skillporter mcp`

Run the Model Context Protocol server over stdio. It is read-only by default.

| Option | Description |
|---|---|
| `--root <dir>` | Workspace boundary. Defaults to the current directory. |
| `--allow-writes` | Enable the mutating tools. |
| `--allow-user-scope` | Permit `scope="user"` reads outside the workspace. |

See [MCP integration](../mcp/README.md).

### `skillporter demo`

Run the self-contained demo in a temporary workspace. It writes nothing to your current directory.
