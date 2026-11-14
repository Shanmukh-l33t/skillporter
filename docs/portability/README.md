# Portability and profiles

Skillporter packages a managed skill environment into a single `.skillpack` file so you can move it to another laptop, restore it inside an offline container, compare two setups, or switch between named profiles.

## Exporting an environment

`skillporter export` captures the skills, harness assignments, provenance, lockfile metadata and saved profiles for a project or user environment into a deterministic `.tar.gz` archive:

```bash
skillporter export acme-api.skillpack
skillporter export personal.skillpack --scope user
skillporter export team.skillpack --managed-only
```

By default, a `.skillpack` is a self-contained hybrid bundle:

- `skillpack.json` records the schema version, per-skill SHA-256 `tree_hash` and `file_hashes`, upstream `source` and `resolved_commit`, harness selections, `skillporter.yaml` configuration and named profiles.
- `skills/<name>/` holds one clean, deduplicated copy of each skill directory, so restoration works with no network access and preserves local skills that do not live in a public Git repository.

Pass `--manifest-only` when every skill comes from a remote repository and you want a reference-only archive without bundled skill files.

### What export refuses or excludes

A portable package preserves the skill environment without copying credentials from a developer machine:

- Dotfiles and key material (`.env`, `.env.*`, `.npmrc`, `.pypirc`, `.netrc`, `*.pem`, `*.key`, SSH private keys, `.git/`) are excluded automatically, and any sensitive filename skipped is named in the export summary.
- Every skill is scanned before archiving. If `scan_skill` finds an embedded credential (`sec-private-key`, `sec-aws-key`, `sec-github-token`, `sec-api-key`) or an escaping symlink, `export` fails closed instead of writing secrets into the archive.
- Local audit logs (`.skillporter/audit.jsonl`) and host environment variables are never included.

## Comparing environments

Before importing a `.skillpack` or switching configurations, `skillporter diff` compares the current workspace against a package, another directory, or a saved profile:

```bash
skillporter diff acme-api.skillpack
skillporter diff ../other-service
skillporter diff profile:security-review
```

`diff` reports skills missing locally, skills present only locally, version or commit changes, file-level SHA-256 content differences, and harness assignment differences. It exits `0` when the two environments match and `1` when they differ, so CI jobs can assert parity.

## Importing and restoring an environment

On another machine, preview the restoration plan first and then apply it:

```bash
skillporter import acme-api.skillpack --dry-run
skillporter import acme-api.skillpack
skillporter import acme-api.skillpack --only-detected --on-conflict skip
```

During `import`, Skillporter runs five checks before modifying the destination workspace:

1. **Bounded archive extraction.** Members are unpacked into a staging directory with path-traversal, Windows device-name, symlink, special-file, duplicate-entry and size limits enforced.
2. **Cryptographic integrity.** Every bundled skill's `tree_hash` and per-file `file_hashes` are recomputed and checked against `skillpack.json`. A corrupted or modified archive stops here.
3. **Static security scan.** Every skill is validated against the Agent Skills specification and scanned statically. Bundled scripts are never executed during import.
4. **Harness discovery.** Skillporter checks which harnesses exist on the destination machine, names any missing harnesses in the plan, and lets you skip missing ones with `--only-detected` or override targets with `--harness` and `--exclude-harness`.
5. **Conflict handling.** Existing unmanaged destinations fail closed by default (`--on-conflict fail`). Pass `--on-conflict skip` to keep existing files untouched, or `--force` (`--on-conflict overwrite`) to snapshot backups and replace them.

When restoring into a project directory, `import` also writes `skillporter.yaml`, `skillporter.lock` and any bundled profiles unless `--no-manifest` is passed. If an error occurs mid-import, completed destinations are rolled back cleanly.

## Named environment profiles

Profiles let you keep several named skill configurations in the same workspace or user home without learning a custom configuration language. Each profile is stored as a standard `skillporter.yaml` manifest under `.skillporter/profiles/<name>.yaml`:

```bash
skillporter profile save frontend
skillporter profile save security-review --skill sec-audit --harness claude-code --harness codex
skillporter profile list
skillporter profile show security-review
skillporter profile use security-review --dry-run
skillporter profile use security-review --prune
```

- `profile save <name>` (`create` is an alias) captures the current skills and harnesses, caching local harness-resident skills under `.skillporter/store/` so switching profiles never loses local-only skills.
- `profile use <name>` activates the profile and synchronizes its skills. Adding `--prune` removes managed skills that belong to the previous profile but not the new one.
- `profile delete <name>` removes the saved profile definition.
