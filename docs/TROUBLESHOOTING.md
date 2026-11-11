# Troubleshooting

## Running `skillporter doctor`
Start every troubleshooting session with:

```bash
skillporter doctor .
```

`doctor` reports five explicit lifecycle states per skill and harness:
- `FOUND` -> `VALID` / `INVALID` -> `COMPATIBLE` / `ADAPTED` -> `INSTALLED` / `MISSING` (plus `DRIFT` or `DUPLICATE`) -> `VERIFIED` / `UNVERIFIED`.

## A skill shows `DRIFT`
Copies of the same skill across two harness directories (for example `.claude/skills/<name>` and `.agents/skills/<name>`) have different SHA-256 content hashes.
- Running `skillporter sync` without `--force` refuses to overwrite drifted copies so manual edits are never lost silently.
- Run `skillporter sync --force` (or `skillporter doctor --fix`) to snapshot existing copies to `.skillporter/backups/` and synchronize from the most recently modified copy.

## A skill shows `DUPLICATE` in Cursor
The skill exists in two directories that Cursor scans simultaneously (such as `.agents/skills/<name>` and `.cursor/skills/<name>`). Remove `.cursor/skills/<name>` and keep `.agents/skills/<name>`, which satisfies both Codex and Cursor with a single folder.

## A skill shows `INVALID` (`frontmatter-tab-indentation` or `name-directory-mismatch`)
- `frontmatter-tab-indentation`: Replace tab characters with spaces in the YAML frontmatter block at the top of `SKILL.md`.
- `name-directory-mismatch`: The `name:` field in `SKILL.md` must match the parent directory name.

## Restoring a previous version after an update
Run:

```bash
skillporter rollback <skill-name>
```

Skillporter restores the most recent snapshot from `.skillporter/backups/<skill-name>/`.
