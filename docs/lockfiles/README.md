# Lockfiles

`skillporter.lock` records exactly what is installed. With it, a teammate or a CI job can reproduce the same skill content and detect any change to it.

## Create and check

```bash
skillporter lock
skillporter lock --check
```

`skillporter sync` also writes the lockfile. `lock --check` writes nothing. It exits `1` when the lockfile is stale or the files on disk no longer match.

```text
$ skillporter lock --check
skillporter.lock check FAILED (1 issue(s)):
  - lockfile drift on 'pdf' (.claude/skills/pdf): locked 6b86f0c798b5 != disk e08dcf6fa1c6
```

Commit `skillporter.lock` next to `skillporter.yaml`.

## Format

This entry was produced by `skillporter add anthropics/skills --skill pdf --harness all` followed by `skillporter lock`. The file list and harness list are shortened here.

```json
{
  "generated_at": "2026-11-14T11:40:33Z",
  "manifest_schema_version": 2,
  "reproducible": true,
  "schema_version": 2,
  "skills": {
    "pdf": {
      "adapt": false,
      "adapter_version": "3.0.0",
      "dependencies": {},
      "direct": true,
      "file_hashes": {
        "SKILL.md": "d1c7caf5f35eb7d37877dd7fc33a095037be2b34fb5d2f7f4d43bde3165bb4ee",
        "forms.md": "9530b3f57034792e0242a3abfe8b3c296466329551916f2ff6c5a70db78f7e44",
        "scripts/fill_fillable_fields.py": "d140872c2e92e41b1e05370ae8d270c5b7f5ebdf55d9905f03bc974a9c708ff5"
      },
      "installed_targets": ["claude-code", "codex", "cursor"],
      "locked_at": "2026-11-14T11:40:33Z",
      "manifest_schema_version": 2,
      "name": "pdf",
      "pin_state": "PINNED_COMMIT",
      "resolved_commit": "2c5958ecac7cee2b583967a2c4981d0f4a75c579",
      "risk_score": 0,
      "scope": "project",
      "source": "https://github.com/anthropics/skills.git",
      "strategy": "copy",
      "tree_hash": "6b86f0c798b5a47987bdd48a97964c0d349ea8ecbc4b886f10dcc38ab0580c32",
      "version": "1.0.0"
    }
  }
}
```

## Fields

| Field | Purpose |
|---|---|
| `resolved_commit` | The full Git commit the source resolved to. `sync` installs this commit even if the branch has moved since. |
| `tree_hash` | One SHA-256 over the whole skill directory. Any change to any file changes it. |
| `file_hashes` | A SHA-256 per file, so a mismatch can be traced to the file that changed. |
| `pin_state` | Whether the entry is immutable. See below. |
| `dependencies` | Other skills this one depends on, with resolved versions. |
| `adapter_version` | The Skillporter version whose adapters produced the install. |
| `installed_targets` | The harnesses the skill was installed for. |
| `source`, `strategy`, `scope`, `adapt` | How and where it was installed. |
| `risk_score` | The static risk score at lock time. |
| `reproducible` | Top level. `true` only when every entry is pinned. |

## Pin states

| `pin_state` | Meaning |
|---|---|
| `PINNED_COMMIT` | The entry has a content hash and a resolved Git commit. |
| `PINNED_CONTENT` | The entry has a content hash but no commit, for example a local directory. The content is pinned. Its origin is not. |
| `UNPINNED_MUTABLE` | A remote source without a resolved commit, or an entry without a content hash. |

`reproducible` is `false` as soon as one entry is `UNPINNED_MUTABLE`.

## What reproducible means here

Given the same `skillporter.lock`, `skillporter sync` installs the same file contents, verified by hash, for the same harnesses.

It does not promise more than that:

- A local source is only as stable as the directory it points to.
- If the pinned commit can no longer be fetched from the source, the install cannot be reproduced from that lockfile.
- A different Skillporter version may place files differently. `adapter_version` records which version wrote the lockfile.
- The lockfile pins skill content. It does not pin what a skill's scripts download when an agent runs them.

## Changed sources are refused, not absorbed

- If the content fetched for a pinned commit does not match `tree_hash`, the sync stops.
- If the files on disk differ from the lockfile, `skillporter sync` refuses to re-lock without `--force`.
- If `skillporter.yaml` now points a skill at a different source than the lockfile recorded, `lock --check` reports it.

## Validation

A lockfile that is not valid JSON, or that declares an unsupported `schema_version`, raises an error. It is never silently treated as empty. Schema version 1 lockfiles are migrated to version 2 automatically.

## Dependencies

Skills can declare dependencies on other skills with semantic version constraints in `skillporter.yaml`. `sync` resolves the graph, detects cycles and conflicts, and installs in topological order.

```bash
skillporter graph
skillporter graph --json
```

## In CI

```yaml
- run: uvx skillporter lock --check
```

See [CI and GitHub Actions](../ci/README.md).
