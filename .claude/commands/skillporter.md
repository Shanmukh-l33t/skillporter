---
description: Diagnose, validate, security-scan, and synchronize Agent Skills across all installed AI harnesses.
---

Run `skillporter` to inspect and synchronize skills in this workspace:

1. Run `skillporter diagnose .` to check reachability, broken symlinks, and SHA-256 content drift.
2. Run `skillporter scan .` to check all `SKILL.md` and `scripts/` files for security issues.
3. If the user passed arguments (`$ARGUMENTS`), run `skillporter $ARGUMENTS`.
4. Otherwise, if skills are missing or drifted across active harnesses, run `skillporter sync` and verify with `skillporter diagnose .`.
