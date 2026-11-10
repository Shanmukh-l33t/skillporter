# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.x | Yes |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report privately via GitHub Security Advisories:
https://github.com/Shanmukh-l33t/skillporter/security/advisories/new

Include: affected version, a reproduction, and the impact you believe it has.
You can expect an acknowledgement within 72 hours and a fix or mitigation
timeline within 14 days.

## Threat model

skillporter is a local CLI that reads and writes files in skill directories. It:

- makes **no network requests** — no telemetry, no update checks;
- runs **no shell commands** — no `subprocess`, `os.system`, or `eval` in the
  library;
- never deletes a directory it cannot identify as an install target, and
  refuses to replace a symlink or existing directory without `--force`;
- never writes outside the resolved harness paths.

The realistic attack surface is therefore a malicious **skill** that a user
installs, not skillporter itself. Treat third-party skills as untrusted code:
they contain instructions an agent will follow and may ship scripts.

## What we scan in CI

`gitleaks` (secrets), `ruff` (lint/static checks), and a full test suite on
Python 3.9–3.13. A release is not cut if any of these fail.
