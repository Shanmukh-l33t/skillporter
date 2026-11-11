# AGENT 7 — INDEPENDENT RED-TEAM REVIEW

**Project**: Skillporter (`https://github.com/Shanmukh-l33t/skillporter`)
**Role**: Independent Red-Team Reviewer

---

## 1. Challenge of Other Agents' Findings & Proposals

As the independent red-team reviewer, I audited both the repository code and the findings from Agents 1–6 to filter out false positives, prevent over-engineering, and uncover missed failure modes.

### Challenge 1: "Should we add `PyYAML` as a runtime dependency for frontmatter parsing?" (Requirement 4.C evaluation)
- **Evaluation**: Adding `PyYAML` would break Skillporter's strongest operational guarantee: **zero external runtime dependencies** (which enables the 52 KB standalone `skillporter.pyz` zipapp, instant `npx` execution without `pip install`, and PEP-668-free `install.sh`).
- **Verdict**: **Reject adding `PyYAML` as a required dependency.** The Agent Skills specification (`https://agentskills.io/specification`) restricts `SKILL.md` frontmatter to 6 top-level keys (`name`, `description`, `license`, `compatibility`, `metadata` string->string map, and `allowed-tools`). Instead, fix the 3 concrete bugs in `frontmatter.py` (line-anchored `^---[ \t]*$` splitting, UTF-8 BOM handling, tab-indentation error reporting, and list/colon value handling) and optionally use `yaml.safe_load` only if neither fallback nor dependency bloat is needed—actually, keeping a single deterministic parser ensures identical behavior whether `PyYAML` happens to be installed in the environment or not!

### Challenge 2: What happens if `staging_dir` or `.old_dir` is left behind after a `SIGKILL` (`kill -9`) inside `.claude/skills/`?
- **Red-Team Finding [RT-01]**:
  In Agent 1's proposal to stage directory swaps inside `dest.parent` (e.g., `.claude/skills/.my-skill.staging-1234`), what happens if the process is killed with `SIGKILL` while `.claude/skills/.my-skill.staging-1234/SKILL.md` exists on disk?
  Because `.my-skill.staging-1234` contains a `SKILL.md` file inside `.claude/skills/`, `discover()` and `scan_location()` would discover `.my-skill.staging-1234` as a skill directory!
- **Resolution**:
  1. Stage temporary directories inside `.skillporter/tmp/` (which is already excluded from `discover()` and all harness scan paths!) on the same filesystem (`root / ".skillporter" / "tmp"`), NOT inside `.claude/skills/`!
  2. In `scan_location()` and `discover()`, ignore hidden directories starting with `.skillporter-tmp-` or `.` inside a `skills/` leaf directory.

### Challenge 3: Symlink Loop DoS in `compute_tree_hash` and `scan_skill`
- **Red-Team Finding [RT-02]**:
  Agent 2 noticed symlink loops in `discover()`, but what about `compute_tree_hash(skill_dir)` in `security.py:203` (`for path in sorted(skill_dir.rglob("*")):`)?
  In Python's `Path.rglob("*")`, directory symlinks are not followed on some Python versions, or if an attacker creates a deeply nested tree or internal symlink loop, `compute_tree_hash` should use `os.walk(skill_dir, followlinks=False)` so it never follows directory symlinks when hashing a skill tree!
- **Resolution**: Switch `compute_tree_hash` from `skill_dir.rglob("*")` to `os.walk(skill_dir, followlinks=False)`.

### Challenge 4: Over-claiming `VERIFIED` Compatibility
- **Red-Team Finding [RT-03]**:
  `README.md` badge previously said `Harnesses: 19 Verified`, which blurs `DOCUMENTATION_VERIFIED` with `RUNTIME_VERIFIED`.
- **Resolution**: Be 100% transparent in `HARNESS_COMPATIBILITY.md`, `README.md`, and `skillporter doctor`: distinguish `RUNTIME_VERIFIED` (1 harness: Hermes), `INTEGRATION_TESTED` (3 harnesses: Claude Code, Codex, Cursor), and `DOCUMENTATION_VERIFIED` (15 harnesses). Only report `VERIFIED` state in `doctor` when `verification_level == "RUNTIME_VERIFIED"`; report `DOC_VERIFIED` / `UNVERIFIED` otherwise.
