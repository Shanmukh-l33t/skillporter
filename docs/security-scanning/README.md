# Security scanning

`skillporter scan` runs a static security assessment over every skill it discovers. The same assessment gates `add`, `install`, `update` and `sync`.

```bash
skillporter scan .
```

Every report is labeled `STATIC_SECURITY_ASSESSMENT`. The scanner reads files and never executes them. Read the [security model](../security/README.md) for what that does and does not establish.

## Output formats

```bash
skillporter scan . --format json
skillporter scan . --format sarif > skillporter.sarif
```

`sarif` produces SARIF 2.1.0, which GitHub code scanning and other tools accept. `json` includes the full report: findings, category scores, per-file hashes and scan completeness.

## Failing a build on risk

```bash
skillporter scan . --max-risk-score 30
```

The command exits `1` when a skill's risk score is above the threshold. The same limit can live in `skillporter.yaml`:

```yaml
security:
  max_risk_score: 30
```

## What is analyzed

| Layer | Examples of what it looks for |
|---|---|
| Python AST | `subprocess` with `shell=True`, `os.system`, `eval` and `exec`, `pickle` and `marshal` loading, dynamic imports, encoded execution, reverse-shell socket patterns, reads of credential files. Import aliases are resolved. |
| JavaScript and TypeScript | `new Function`, `vm` usage, `child_process` execution, remote `import()`. |
| Markdown instructions | Instruction-override phrasing, hidden HTML comments, exfiltration directives, unsafe delegation, hidden Unicode, path traversal in links. |
| Secrets | PEM private keys, AWS access keys, GitHub tokens, common API key formats. |
| Shell patterns | Downloads piped into a shell, reverse shells, credential harvesting, environment exfiltration. |
| Encoded content | Bounded decoding of Base64 (standard and URL-safe, including zlib-compressed), hex, and PowerShell `-EncodedCommand` payloads. |
| Cross-file chains | A payload in one file that is decoded in a second and executed from a third. |
| Filesystem | Symlinks that leave the skill root, path traversal, broken symlinks, precompiled binaries, scripts outside `scripts/`. |

## Finding codes

Each finding has a code, a severity, a category, a confidence level, a file, a line where one applies, and a suggested fix. `skillporter explain <code>` describes any of them.

| Category | Codes |
|---|---|
| Secrets | `sec-private-key`, `sec-aws-key`, `sec-github-token`, `sec-api-key` |
| Prompt injection | `sec-prompt-override`, `sec-hidden-unicode`, `sec-html-comment-instruction`, `sec-md-hidden-comment`, `sec-css-hidden-instruction`, `sec-md-unsafe-delegation` |
| Code execution | `sec-curl-pipe-sh`, `sec-reverse-shell`, `sec-dynamic-eval`, `sec-obfuscated-exec`, `sec-base64-decode`, `sec-encoded-payload`, `sec-powershell-encoded`, `sec-cross-file-staged-exec`, `sec-py-unsafe-subprocess`, `sec-py-unsafe-deserialization`, `sec-py-dynamic-import`, `sec-py-encoded-exec`, `sec-js-dynamic-eval`, `sec-js-child-process` |
| Data exfiltration | `sec-credential-harvest`, `sec-data-exfil`, `sec-env-exfil`, `sec-md-secret-exfil` |
| Filesystem escape | `sec-symlink-escape`, `sec-path-traversal`, `sec-markdown-path-traversal` |
| Supply chain | `sec-external-download`, `sec-binary-artifact`, `sec-script-outside-scripts-dir`, `sec-js-remote-code`, `sec-cross-file-remote-stage`, `sec-oversized-file`, `sec-unreadable-file` |

## Risk score

The score is deterministic. The same files always produce the same number.

1. Findings are deduplicated by code, file and line. The highest severity is kept.
2. Each finding adds a weight to its category:

   | Finding | Weight |
   |---|---|
   | Structural escape (`sec-symlink-escape`, `sec-path-traversal`) | 90 |
   | `CRITICAL` | 55 |
   | `HIGH` | 35 |
   | `MEDIUM` | 15 |
   | `LOW` | 5 |
   | `INFO` | 2 |

3. Each category is capped at 100.
4. The risk score is the sum of the category scores, capped at 100.

## Posture

| Posture | When |
|---|---|
| `NO_DETECTED_FINDINGS` | A complete scan found nothing. |
| `LOW_DETECTED_RISK` | A complete scan found only medium, low or informational findings. |
| `HIGH_DETECTED_RISK` | A high-severity finding, or a risk score above 50. |
| `CRITICAL_DETECTED_RISK` | A structural escape, a critical finding, or a risk score above 80. |
| `INCOMPLETE_ASSESSMENT` | At least one file could not be fully inspected. |

The names say "detected" deliberately. `NO_DETECTED_FINDINGS` means the scanner found nothing. It does not mean the skill is safe.

## Incomplete scans

Text files larger than 2 MiB are not fully pattern-scanned (`sec-oversized-file`), and files that cannot be read are reported (`sec-unreadable-file`). Either sets `scan_complete` to `false`.

An incomplete assessment never returns `APPROVE` and blocks installation by default. This closes the obvious trick of hiding a payload behind megabytes of padding.

## Optional external engine

The built-in engine is `skillporter-static`. If NVIDIA SkillSpector is installed, `--engine auto` merges its score, and the report takes the higher of the two. `--offline` or `SKILLPORTER_OFFLINE=1` uses the built-in engine only. The report's `external_scanner_status` field states what happened: `not_configured`, `offline_skipped`, `unavailable`, `merged` or `failed`.

## Example

The report below comes from scanning a deliberately unsafe test skill. Its `SKILL.md` hides an instruction in an HTML comment and pipes a download into a shell, and its script reads an SSH key and executes a Base64 payload.

```text
quick-setup: BLOCKED  (risk: 100/100 · REJECT · posture: CRITICAL_DETECTED_RISK · engine: skillporter-static v3.1.0 · sha256: 7245f2bd2432)
  Categories: prompt_injection=70, code_execution=100, data_exfiltration=35, supply_chain=2
  [CRITICAL] sec-prompt-override (SKILL.md:12): Prompt-injection directive attempting to override system/user instructions
  [CRITICAL] sec-curl-pipe-sh (SKILL.md:15): Remote code execution pattern (curl/wget piped directly into shell)
  [HIGH] sec-credential-harvest (scripts/bootstrap.py:6): Python AST accesses sensitive host credential path (.ssh/id_ed25519)
  [HIGH] sec-py-unsafe-subprocess (scripts/bootstrap.py:8): Unsafe subprocess invocation `subprocess.run(..., shell=True)` risks shell injection
  [CRITICAL] sec-encoded-payload (scripts/bootstrap.py:7): Base64-encoded (or zlib-compressed) malicious command or prompt-injection payload detected
  [HIGH] sec-cross-file-staged-exec (SKILL.md:1): Multi-file staged payload decode-and-execute chain detected (payload=scripts/bootstrap.py -> decode=scripts/bootstrap.py -> exec=SKILL.md)
```

The output is abridged. Four further findings and the per-finding fix lines are omitted.

A worked review of a scan before you act on it is in [Scanning agent skills before you install them](https://www.skillporter.dev/blog/scanning-agent-skills-before-install).
