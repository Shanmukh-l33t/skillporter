# Quick start

This page runs the whole lifecycle once: install a skill, inspect it, pin it, detect a change, and recover. Every command is run from your project root.

## 1. Add a skill to every harness

```bash
skillporter add anthropics/skills --skill pdf --harness all
```

The output lists the resolved commit, the security assessment and one line per harness. Harnesses that read the shared `.agents/skills` directory are reported as sharing one copy.

## 2. Confirm every harness can see it

```bash
skillporter diagnose .
```

A healthy workspace ends with `no findings` and exit code `0`.

## 3. Scan it

```bash
skillporter scan .
```

The scan is static. It reads files and never runs them. For CI systems that ingest SARIF:

```bash
skillporter scan . --format sarif > skillporter.sarif
```

## 4. Write the manifest and lockfile

```bash
skillporter init
skillporter sync
```

`skillporter.yaml` declares which skills and harnesses the project uses. `skillporter.lock` records exactly what was installed: the resolved commit, a tree hash and a SHA-256 for every file. Commit both.

## 5. Verify the lockfile in CI

```bash
skillporter lock --check
```

Exit code `0` means the files on disk match the lockfile. Exit code `1` means something changed.

## 6. See drift get caught

Edit one copy of the skill by hand:

```bash
echo "local change" >> .claude/skills/pdf/SKILL.md
skillporter diagnose .
```

`diagnose` now reports `DRIFT` and lists each copy with its hash. `skillporter lock --check` fails too, and a plain `skillporter sync` refuses to overwrite anything.

## 7. Reconcile

Tell Skillporter which copy is authoritative:

```bash
skillporter sync --force --prefer .agents/skills/pdf
```

The copies that are about to be replaced are snapshotted to `.skillporter/backups/` first.

## 8. Roll back if you need to

```bash
skillporter rollback pdf --dry-run
skillporter rollback pdf
```

The dry run prints which snapshot would be restored.

## 9. Review what happened

```bash
skillporter status
skillporter audit .
```

`status` summarizes the manifest, lockfile and per-harness state. `audit` reports each installed skill's origin and security posture, lockfile integrity, and the events recorded in `.skillporter/audit.jsonl`.

## Where to go next

- [Skill management](../skill-management/README.md) for sources, strategies and scopes.
- [Synchronization](../synchronization/README.md) for how drift is resolved.
- [Lockfiles](../lockfiles/README.md) for the lockfile format.
