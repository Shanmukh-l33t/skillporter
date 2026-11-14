# Security Policy & Architecture

## Supported Versions

| Version | Supported |
|---|---|
| 3.1.x | Yes |
| 3.0.x | Yes |
| 2.4.x | Security fixes only |
| < 2.4 | Unsupported |

## Reporting a Vulnerability

Do **not** open a public GitHub issue for security vulnerabilities. Report privately via GitHub Security Advisories:
https://github.com/Shanmukh-l33t/skillporter/security/advisories/new

You can expect acknowledgement within 72 hours and a remediation timeline within 14 days.

---

## 1. Core Engine Trust Boundaries

### 1.1 Zero Untrusted Code Execution
Skillporter never executes scripts bundled inside a skill (`scripts/*`, hooks, setup scripts) during git cloning, archive extraction, validation, static scanning, or installation. Git clones run with `-c protocol.ext.allow=never -c core.fsmonitor=false -c core.symlinks=false`, validated ref syntax (`_validate_git_ref`), and explicit `--` argument termination.

### 1.2 Archive & Filesystem Hardening (`skillporter/sources.py`, `skillporter/install.py`)
- Rejects `../` and `..\` traversal, absolute paths, Windows drive-qualified paths (`C:\`), Windows reserved device names (`CON`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`), NTFS alternate data streams (`:`), trailing dots/spaces, control/NUL bytes, symlinks, hardlinks, FIFOs, and special device modes.
- Enforces Unicode NFC + case-folded duplicate collision detection (`café.md` NFC vs NFD) and bounded streaming caps (`MAX_ARCHIVE_FILES = 1000`, `MAX_SINGLE_FILE_BYTES = 10 MiB`, `MAX_TOTAL_ARCHIVE_BYTES = 50 MiB`).
- Writes extracted files with `O_CREAT | O_EXCL | O_NOFOLLOW` (where supported by the OS) and strips `setuid`/`setgid`/world-write bits.
- Rejects harness target directories whose parent paths escape workspace/user scope via symlinks.
- Uses write-ahead `journal.json` transactions so `SIGKILL` crashes or mid-batch errors roll back uncommitted targets automatically.

### 1.3 Separation of Conflict Override vs. Security Risk Acceptance
- `--force` (`force=true` in MCP) **only** authorizes overwriting conflicting existing destination directories. It **never** bypasses security blocking.
- `--allow-risky` (`accept_risk=true` in MCP) is an explicit boolean override for non-structural static findings. When used, findings are printed and recorded in `.skillporter/audit.jsonl`.
- Structural escapes (`sec-symlink-escape`, `sec-path-traversal`) can **never** be overridden by `--allow-risky` or `--force`.

### 1.4 Hardened MCP Server (`skillporter/mcp_server.py`)
- **Workspace Containment**: Effective workspace root comes strictly from explicit server config (`--root`), `SKILLPORTER_MCP_ROOT`, or server `cwd`. Caller-supplied paths never redefine the workspace root.
- **User-Scope Isolation**: `scope="user"` is denied by default; enable only with `--allow-user-scope` or `SKILLPORTER_MCP_ALLOW_USER_SCOPE=1`.
- **Read/Write Separation (Default-Deny Writes)**: Read tools (`detect`, `diagnose`, `scan`, `inspect`, `matrix`) work in default read-only mode. Mutating tools (`add`, `install`, `sync`, `remove`) are denied unless `--allow-writes` or `SKILLPORTER_MCP_ALLOW_WRITES=1` is set.
- **Strict Runtime Type Validation**: Booleans must be JSON booleans (`"false"` and `"0"` are rejected with `TypeError`), paths must be strings, and harness lists must contain registered harness IDs.
- **Secret-Scrubbed Audit Log**: Writes structured events to `.skillporter/audit.jsonl` (`0600` on POSIX), scrubbing URL credentials, tokens, and PEM keys.

### 1.5 Standalone Installer Trust Model (`install.sh`)
- Downloads immutable versioned release tags only (`^v[0-9]+\.[0-9]+\.[0-9]+...`); mutable `main` fallbacks are forbidden.
- Verifies SHA-256 against `SHA256SUMS.txt` **and** requires an independent root of trust (fail-closed by default) because a checksum fetched from the same origin as the binary detects transport corruption, not origin compromise:
  1. **GitHub Artifact Attestations (preferred)**: `gh attestation verify` validates Sigstore Fulcio OIDC provenance bound to `.github/workflows/publish.yml`.
  2. **Out-of-band pinned SHA-256**: `SKILLPORTER_SHA256=<64-hex>`.
  3. **Detached OpenSSL signature**: `SKILLPORTER_PUBLIC_KEY_FILE=/path/to/pub.pem` verifying `SHA256SUMS.txt.sig`.
- Stages temporary files inside the target binary directory so `mv -f` is an atomic same-filesystem `rename(2)` and failed upgrades leave existing binaries untouched.

---

## 2. Static Security Scanner & Scoring Formula (`skillporter/security.py`)

### 2.1 Deterministic 0–100 Risk Scoring Formula
1. Findings are deduplicated by `(code, file, line)`, retaining the highest severity.
2. Each finding contributes a deterministic weight to one of 6 categories (`secrets`, `prompt_injection`, `code_execution`, `data_exfiltration`, `filesystem_escape`, `supply_chain`):
   - Structural escape (`sec-symlink-escape`, `sec-path-traversal`): `90`
   - `CRITICAL`: `55`
   - `HIGH`: `35`
   - `MEDIUM`: `15`
   - `LOW`: `5`
   - `INFO`: `2`
3. Each category score is capped at `100`: `cat_score = min(100, sum(weights_in_cat))`.
4. Static `risk_score = min(100, sum(category_breakdown.values()))`. If NVIDIA SkillSpector is active and returns `external_score`, `risk_score = min(100, max(static_score, external_score))`.

### 2.2 Posture Classifications & Incomplete Scans
- `CRITICAL_DETECTED_RISK`: Structural escape, `critical_count > 0`, or `risk_score > 80` (`REJECT`).
- `HIGH_DETECTED_RISK`: `high_count > 0` or `risk_score > 50` (`REJECT` / `CAUTION`).
- `INCOMPLETE_ASSESSMENT`: One or more files exceeded `MAX_SCAN_FILE_BYTES` (2 MiB, `sec-oversized-file`) or raised `OSError` (`sec-unreadable-file`). Incomplete assessments set `scan_complete: false` and never return `APPROVE`.
- `LOW_DETECTED_RISK`: Only `MEDIUM`/`LOW`/`INFO` findings on a complete scan.
- `NO_DETECTED_FINDINGS`: Zero detected findings on a complete scan (`scan_complete: true`).
- `external_scanner_status` explicitly reports `not_configured`, `offline_skipped`, `unavailable`, `merged`, or `failed`.

### 2.3 Security Limitations (What Static Analysis Cannot Guarantee)
- **No static scanner can prove a skill is safe.** Novel semantic prompt injections written in ordinary prose without known override phrases can still manipulate an LLM.
- Legitimate-looking HTTPS endpoints may serve benign content during inspection and malicious payloads later at runtime.
- Complex multi-layer obfuscation or logic bombs conditioned on runtime dates/inputs can evade static AST and pattern heuristics.
- **Host isolation**: Host-level isolation depends on the executing agent harness's own sandboxing and tool-approval boundaries. Capability declarations (`capabilities:` in `SKILL.md`) are statically audited against inferred behaviors (`capabilities.py`), and project policies (`skillporter.policy.yaml`) fail closed during install, sync, update, import, and MCP operations, without claiming runtime kernel sandboxing.
- **Optional advisory AI review**: `skillporter scan --ai-review --yes-send` requires explicit transmission consent and user-provided API credentials; its output is advisory only and never overrides deterministic static blocks.
