# AGENT 6 — PRODUCT AND DEVELOPER EXPERIENCE AUDIT

**Project**: Skillporter (`https://github.com/Shanmukh-l33t/skillporter`)
**Role**: Product & Developer Experience (DX) Engineer

---

## 1. Product Positioning & CLI Surface Review

Skillporter's core value proposition is:
**"Understand why an AI agent cannot discover or correctly use a skill, and fix the problem safely."**

### Review of Current `skillporter doctor` Output
Currently, `skillporter doctor` prints only a 4-line summary (`Detected harnesses`, `Discovered skills`, `Content drift`, and `Issues found`).
It does **not** answer the 7 questions a developer runs `skillporter doctor` to learn:
1. **Which skills exist** (`FOUND` and where they live on disk).
2. **Which skills are valid vs invalid** (`VALID` vs `INVALID`, separating spec errors from recommendations).
3. **Which harnesses can discover them** (`INSTALLED` vs `MISSING` vs `DRIFT` vs `BROKEN`).
4. **Which skills have harness-specific incompatibilities** (`COMPATIBLE` vs `ADAPTED` vs token-limit warnings).
5. **What is runtime-verified vs doc-verified** (`VERIFIED` vs `UNVERIFIED`).
6. **Why a skill is missing or unhealthy** (exact root cause).
7. **Which exact commands fix each issue** (`skillporter sync`, `skillporter doctor --fix`, `skillporter validate`, etc.).

---

## 2. DX Improvements Required

### DX-01: Upgrade `skillporter doctor` Into the Flagship Diagnostic Experience
Structure `skillporter doctor` output into clear, scannable sections:
1. **Skills Discovered (`FOUND` / `VALID` / `INVALID`)**: Lists each skill, its canonical path, spec validity, approximate token count, and SHA-256 tree hash.
2. **Harness Reachability & Compatibility Matrix**: Shows explicit states (`INSTALLED`, `MISSING`, `DRIFT`, `DUPLICATE`, `BROKEN`) alongside support/verification classification (`NATIVE/VERIFIED`, `NATIVE/DOC_VERIFIED`, `ADAPTED`).
3. **Root-Cause Diagnostics**: Separates Spec Violations (`[spec]`), Harness Compatibility Warnings (`[compat]`), Content Drift (`[drift]`), and Missing Installations (`[missing]`).
4. **Actionable Fix Commands**: Prints the exact copy-pasteable command(s) to resolve every finding.

### DX-02: Protect User Edits During `skillporter sync`
If a developer edits `.claude/skills/my-skill/SKILL.md` and runs `skillporter sync`, `sync` previously picked `.agents/skills/my-skill` (alphabetically first) and overwrote `.claude/skills/my-skill` with `force=True`!
- Fix: If copies have drifted and no `skillporter.yaml` declares the single source of truth, `skillporter sync` must stop, show which copies differ, and require `--force` (which snapshots all replaced copies to `.skillporter/backups/` before syncing from the newest modified copy).
