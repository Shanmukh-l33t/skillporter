# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 2.x | Yes |
| 1.x | Security fixes only |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report vulnerabilities privately via GitHub Security Advisories:
https://github.com/Shanmukh-l33t/skillporter/security/advisories/new

Include the affected version, a minimal reproduction, and the potential impact. You can expect an acknowledgement within 72 hours and a remediation timeline within 14 days.

## Threat Model & Security Architecture

Skillporter operates across two distinct trust boundaries:

### 1. Skillporter Core Engine Safety
- **Zero telemetry**: Skillporter makes no background network calls. Network access occurs only when the user explicitly runs `skillporter add`, `skillporter inspect`, `skillporter update`, or `skillporter search` against a remote source.
- **No script execution during installation**: Skillporter never executes scripts bundled inside a skill (`scripts/*`, hooks, or setup scripts) during cloning, extraction, validation, or installation.
- **Archive & symlink hardening**: `safe_extract_zip` and `safe_extract_tar` reject path traversal (`..` / absolute paths / Zip-Slip), symlink entries, and special device files before a single byte is extracted.
- **Ownership protection**: Existing directories and symlinks are never overwritten unless tracked in `.skillporter/state.json` during an explicit sync/update or overridden with `--force`.
- **Declarative third-party adapters**: Custom adapter definitions (`load_adapter_file`) parse declarative JSON data only and never import or execute arbitrary Python code.

### 2. Untrusted Third-Party Skill Assessment (`skillporter scan`)
Third-party skills are untrusted code and instructions: an AI agent will read `SKILL.md` into its prompt context and may execute bundled scripts.

`skillporter scan` (and `skillporter add` prior to installation) performs a **Static Security Assessment (`STATIC_SECURITY_ASSESSMENT`)** checking for:
- Hardcoded secrets and private keys (`sec-private-key`, `sec-aws-key`, `sec-github-token`, `sec-api-key`)
- Prompt injection and covert instruction overrides (`sec-prompt-override`, `sec-hidden-unicode`, `sec-html-comment-instruction`)
- Remote code execution and reverse shell patterns (`sec-curl-pipe-sh`, `sec-reverse-shell`, `sec-dynamic-eval`)
- Host credential harvesting (`sec-credential-harvest` targeting `~/.ssh`, `~/.aws`, `/etc/shadow`, `.npmrc`, `.pypirc`)
- Symlink escapes pointing outside the skill root (`sec-symlink-escape`)

**Important limitation**: Static pattern and structural scanning catches known supply-chain and prompt-injection patterns, but **cannot guarantee that a natural-language prompt or script is safe at runtime**. Always review unfamiliar skills with `skillporter inspect <source>` before granting an autonomous agent execution permissions.
