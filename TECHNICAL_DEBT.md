# Technical Debt & Known Limitations

_Last updated: 2026-11-11_

Skillporter tracks remaining technical debt and deliberate design trade-offs transparently.

## 1. Custom YAML Subset Parser (`skillporter/frontmatter.py`, `skillporter/manifest.py`)
- **Trade-off**: To preserve zero external runtime dependencies (so `skillporter.pyz` is a 52 KB self-contained zipapp and `uvx`/`npx` require no third-party wheels), Skillporter uses a custom YAML subset parser rather than `PyYAML`.
- **Supported**: `key: value`, quoted strings, inline `[a, b]` lists, indented `- item` lists, one-level nested `key: value` maps (`metadata:`), and `|` / `>` / `|-` / `>-` block scalars.
- **Limitation**: Deeply nested multi-level YAML maps (>2 levels), YAML anchors/aliases (`&anchor` / `*alias`), and multi-line flow collections are not parsed. Neither the Agent Skills specification (`SKILL.md`) nor `skillporter.yaml` uses these constructs.

## 2. Static Pattern Scanning vs Runtime Sandboxing (`skillporter/security.py`)
- **Trade-off**: `skillporter scan` performs static heuristic and structural analysis (`STATIC_SECURITY_ASSESSMENT`).
- **Limitation**: No static scanner can prove that natural-language instructions in `SKILL.md` or obfuscated code in `scripts/` are benign at runtime. All CLI, JSON, and MCP outputs explicitly state this limitation.

## 3. Runtime Verification Coverage Across Proprietary IDEs (`skillporter/harnesses.py`)
- **Limitation**: While all 19 harness adapters are verified against official vendor documentation (`DOCUMENTATION_VERIFIED`) and covered by automated filesystem discovery tests (`INTEGRATION_TESTED`), proprietary GUI IDEs (such as Cursor, Windsurf, and JetBrains IDEs) cannot be launched headlessly in standard GitHub Actions runners to confirm live UI ingestion (`RUNTIME_VERIFIED`). Only harnesses with live runtime evidence are marked `RUNTIME_VERIFIED` (`VERIFIED`); all others report `UNVERIFIED` at the runtime layer in `skillporter doctor`.

## 4. Cross-Filesystem Staging Moves
- **Detail**: `_stage_and_copy_skill` stages inside `<root>/.skillporter/tmp/` (or `~/.skillporter/tmp/` for user scope). In the rare case where a user mounts `.claude/skills` on a separate filesystem volume from `<root>/.skillporter`, `shutil.move` falls back to copy+delete across mount points rather than a single-syscall `os.rename`.
