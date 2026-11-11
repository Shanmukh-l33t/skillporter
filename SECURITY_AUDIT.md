# AGENT 3 — DEFENSIVE SECURITY AUDIT

**Project**: Skillporter (`https://github.com/Shanmukh-l33t/skillporter`)
**Role**: Lead Defensive Security Engineer

---

## 1. Threat Model & Attack Surface

Skillporter handles untrusted external inputs across four vectors:
1. **Untrusted Skill Repositories & Archives** (`skillporter add`, `inspect`, `scan`, `sync`).
2. **Untrusted `SKILL.md` & Script Content** (prompt-injection payloads, trojan Unicode, shell/Python scripts).
3. **CLI Arguments & Manifests** (`skill_name`, `source`, `ref`, `SKILLPORTER_REGISTRY_URL`).
4. **Custom Adapter Files** (`load_adapter_file`).

---

## 2. Confirmed Security Vulnerabilities & Gaps

### [SEC-01] Critical Path Traversal in `uninstall()` / `remove` via `skill_name` (CRITICAL / P0)
- **Location**: `skillporter/install.py:366` (`dest = base / skill_name`)
- **Proof of Concept**: `skillporter remove ../../important-folder --harness codex` resolves `dest` to `<repo>/important-folder` and calls `shutil.rmtree(dest)`.
- **Remediation**: Enforce strict path-segment validation (`_validate_skill_name`) rejecting any `skill_name` containing `/`, `\`, `..`, `.`, or NUL bytes, and verify `dest.resolve().parent == base.resolve()` before any deletion or write.

### [SEC-02] Archive Decompression Bomb (Zip-Bomb / Tar-Bomb) & File-Count Exhaustion (HIGH / P0)
- **Location**: `skillporter/sources.py:138-183` (`safe_extract_zip`, `safe_extract_tar`)
- **Analysis**: While Zip-Slip (`../` and `..\`), absolute paths, drive-letter paths, and archive symlinks/hardlinks/FIFOs are already blocked, `shutil.copyfileobj(src, out)` streams unbounded bytes per entry and allows unlimited archive entries. A 40 KB zip bomb expanding to 20 GB can exhaust disk space.
- **Remediation**: Enforce hard limits during streaming extraction: max 1,000 entries, max 10 MiB per file, and max 50 MiB total extracted size across the archive.

### [SEC-03] Git Clone Hook / Protocol Execution Hardening (MEDIUM / P0)
- **Location**: `skillporter/sources.py:191-208` (`_git_clone`)
- **Analysis**: `_validate_git_ref` and `"--"` already prevent git argument injection via `ref` and `url`. However, passing `-c protocol.ext.allow=never -c core.fsmonitor=false -c core.symlinks=false` to `git clone` provides defense-in-depth against malicious `.gitmodules` or repository config options.

### [SEC-04] Custom Adapter Path Traversal in `load_adapter_file` (MEDIUM / P1)
- **Location**: `skillporter/harnesses.py:663-695`
- **Analysis**: `load_adapter_file` parses declarative JSON (never executing code), but does not reject `..` segments in a custom adapter's `project`-scoped `SkillPath.path`. A malicious custom adapter JSON with `{"path": "../../outside", "scope": "project"}` could direct project installs outside the repo root.
- **Remediation**: Validate that project-scoped and user-scoped adapter paths are relative and contain no `..` traversal components.

### [SEC-05] Static Scanner Evasion & False-Confidence Evaluation (`skillporter/security.py`) (MEDIUM / P1)
- **Analysis**:
  1. Regex-based static scanning (`scan_skill`) can be bypassed via base64 encoding (`echo ... | base64 -d | sh`), hex/rot13 decoding, or multi-line command splitting.
  2. Data exfiltration flags (`curl -d @`, `curl --data-binary`, `wget --post-file`) were not covered in `_SCRIPT_PATTERNS`.
  3. Leading UTF-8 BOM (`\ufeff` at character index 0 of a file) was matched by `_PROMPT_PATTERNS` (`sec-hidden-unicode`), causing a false-positive `HIGH` finding on legitimate Windows-saved Markdown files, whereas `\ufeff` *after* index 0 or zero-width/bidi characters (`\u200b`–`\u200f`, `\u202a`–`\u202e`, `\u2066`–`\u2069`) are genuine obfuscation indicators.
- **Remediation**:
  1. Add detection for base64/decode pipe execution (`sec-obfuscated-exec`) and HTTP POST file exfiltration (`sec-data-exfil`).
  2. Ignore a single leading UTF-8 BOM at byte/char offset 0 while flagging any zero-width/bidi characters or mid-file `\ufeff`.
  3. Cap per-file text scan reads at 2 MiB to prevent ReDoS / memory spikes on large asset files.
  4. Maintain explicit `STATIC_SECURITY_ASSESSMENT` disclaimers in all CLI, JSON, and MCP outputs so users never mistake pattern scanning for a sandbox guarantee.
