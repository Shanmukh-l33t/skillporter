# AGENT 2 — PYTHON BACKEND SPECIALIST REVIEW

**Project**: Skillporter (`https://github.com/Shanmukh-l33t/skillporter`)
**Role**: Senior Python Backend Specialist

---

## Module-by-Module Code Audit

### 1. `skillporter/install.py`
- **[BUG-PY-01] Unvalidated `skill_name` allows path traversal in `uninstall()` and `install()` (CRITICAL / P0)**:
  In `uninstall()` (line 366):
  ```python
  base = resolve_path(paths[0].path, scope, root, home)
  dest = base / skill_name
  ```
  `skill_name` comes directly from CLI `args.skill` (`skillporter uninstall ../../my-dir --harness codex`). Because `Path("/repo/.agents/skills") / "../../my-dir"` resolves to `/repo/my-dir`, `shutil.rmtree(dest)` will delete arbitrary directories outside `.agents/skills`! The same applies to `skill_name_override` in `install()`.
  *Fix*: Add `validate_skill_name(skill_name)` rejecting `/`, `\`, `..`, `.`, and verifying `dest.resolve().parent == base.resolve()`.
- **[BUG-PY-02] Partial failure during `force=True` install leaves overwritten targets un-restored (HIGH / P0)**:
  `created_in_txn` only records destinations that did not exist before the call. If destination 1 existed and was replaced (`force=True`) and destination 2 fails (`InstallError`), destination 1 is not restored.
  *Fix*: Stage new content to a sibling temp directory, move existing `dest` to a backup sibling directory during the transaction, and restore it on error.
- **[BUG-PY-03] `shutil.copytree(src, dest, symlinks=False)` fails on internal relative symlinks**:
  If a legitimate skill contains an internal relative symlink or a broken symlink, `symlinks=False` attempts to dereference it and raises `shutil.Error` mid-copy. Using `symlinks=True` (after `scan_skill` / symlink-escape verification confirms no symlink escapes `src`) preserves internal links safely.

### 2. `skillporter/frontmatter.py`
- **[BUG-PY-04] `split_frontmatter` splits on inline `---` inside YAML values (HIGH / P1)**:
  Line 134: `parts = text.split("---", 2)`.
  If a `SKILL.md` frontmatter contains `description: " Bridges A --- and B "` or a comment `# ---`, `text.split("---", 2)` splits in the middle of the frontmatter instead of matching a line-anchored closing `^---[ \t]*$` delimiter!
  *Fix*: Use a line-aware parser that requires the opening `---` on line 1 (after optional UTF-8 BOM `\ufeff`) and matches the closing `---` or `...` on its own line.
- **[BUG-PY-05] Tab indentation in YAML frontmatter is silently ignored instead of flagged (MEDIUM / P1)**:
  Line 87: `if raw.startswith((" ", "\t")):`. YAML 1.2 forbids tab characters for indentation, and harnesses using strict YAML parsers (Claude Code, Junie, Codex) reject `SKILL.md` files with tab indentation.
  *Fix*: Detect leading tabs in frontmatter lines and emit a spec error (`frontmatter-tab-indentation`).
- **[BUG-PY-06] `discover()` recurses into skill subdirectories and symlink loops (HIGH / P0)**:
  `root.rglob("SKILL.md")` continues walking inside a skill directory (`my-skill/references/example/SKILL.md`) and does not skip `build`, `dist`, or `.egg-info`.
  *Fix*: Walk top-down with `os.walk`, prune directories once `SKILL.md` is found in that directory, track visited realpaths to prevent symlink infinite loops, and skip build/artifact directories.

### 3. `skillporter/diagnose.py`
- **[BUG-PY-07] Secondary copies of a skill are skipped during validation (HIGH / P1)**:
  Lines 200-204: `if name in seen: continue` happens *before* `diag.issues[str(skill_dir)] = validate(parse_skill(skill_md))`. If `.agents/skills/foo/SKILL.md` is valid, but `.claude/skills/foo/SKILL.md` has corrupted frontmatter, `diagnose` never validates the `.claude` copy!
  *Fix*: Validate every discovered `SKILL.md` and aggregate issues across all copies.
- **[BUG-PY-08] `scan_location` recursive scan does not stop at skill boundaries (MEDIUM / P1)**:
  Lines 156-163: `for nested in sorted(entry.rglob(_SKILL_FILE)):` will also pick up any `SKILL.md` nested inside `references/` of a categorized skill.
  *Fix*: Reuse the top-down skill discovery helper that stops recursing once a directory contains `SKILL.md`.

### 4. `skillporter/sources.py`
- **[BUG-PY-09] Unbounded decompression in `safe_extract_zip` and `safe_extract_tar` (HIGH / P0)**:
  `shutil.copyfileobj(src, out)` copies arbitrarily large streams without checking actual decompressed byte counts or total file counts.
  *Fix*: Stream in 64 KiB chunks with hard caps on per-file size (10 MiB), total extracted bytes (50 MiB), and member count (1,000 files).

### 5. `skillporter/cli.py`
- **[BUG-PY-10] `skillporter sync` overwrites drifted copies without warning or `--force` check (HIGH / P0)**:
  In `_cmd_sync` (line 786), when no `skillporter.yaml` exists, `sync` picks the first discovered copy in sorted path order and overwrites all other copies with `force=True`. If a developer edited `.claude/skills/foo/SKILL.md` (which sorts after `.agents/skills/foo/SKILL.md`), running `skillporter sync` overwrites their new edit in `.claude` with the old copy in `.agents`!
  *Fix*: When copies have drifted and no manifest specifies the canonical source, `sync` must refuse to overwrite drifted copies unless `--force` is given (or pick the newest mtime only when `--force` is passed, while snapshotting the replaced copy to `.skillporter/backups/`).
