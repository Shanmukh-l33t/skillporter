---
title: "Scanning agent skills before you install them"
heading: "Scanning agent skills before you install them"
description: "What a static security scan reads in a skill, how the 0 to 100 risk score becomes APPROVE, CAUTION or REJECT, and where the scan stops."
date: "2026-11-14"
---

## A skill is executable supply chain

A skill directory looks like documentation: a `SKILL.md`, sometimes `scripts/`, sometimes a reference. It is not. The instructions enter the model's context and steer what the agent does next; any script in the package runs on your machine, with your permissions.

Instructions can send an agent to read a credential file; a script beside them can do it with no model involved. Skillporter therefore treats every third-party skill as untrusted input and gates `add`, `install`, `update` and `sync` on one static assessment. The format itself is covered in [what is an agent skill](/blog/what-is-an-agent-skill).

## What the static scan reads

`skillporter scan` reads files as text and matches patterns. It never runs a skill's scripts, hooks or setup files, which is why every report is labelled `STATIC_SECURITY_ASSESSMENT`.

| Layer | What it inspects |
|---|---|
| Python and JavaScript | Python AST checks `subprocess` with `shell=True`, `os.system`, `eval` and `exec`, `pickle` and `marshal` loading, dynamic imports, reverse-shell sockets and credential reads, with aliases resolved. JS checks `new Function`, `vm`, `child_process` and remote `import()`. |
| Markdown instructions | Instruction-override phrasing, hidden HTML comments, exfiltration directives, unsafe delegation, hidden Unicode, path traversal in links. |
| Secrets | PEM private keys, AWS access keys, GitHub tokens, common API key formats. |
| Shell patterns | Downloads piped into a shell, reverse shells, credential harvesting, environment exfiltration. |
| Encoded content | Bounded decoding of Base64 (standard, URL-safe, zlib), hex and PowerShell `-EncodedCommand` payloads, including payloads staged across files. |
| Filesystem | Symlinks leaving the skill root, path traversal, broken symlinks, precompiled binaries, scripts outside `scripts/`. |

Findings carry a code, severity, file, line and fix; they fall into six categories: secrets, prompt injection, code execution, data exfiltration, filesystem escape and supply chain.

Text files above 2 MiB are not fully scanned, and unreadable files are reported rather than skipped; either sets `scan_complete` to `false`, and an incomplete scan never returns `APPROVE`. There is no manifest or postinstall analysis: a skill is a directory, not an npm package, so a skill that downloads someone else's installer shows up as a download, not a dependency tree.

Archives are handled at ingestion, before scoring: members with `..` traversal, absolute or drive paths, reserved device names, alternate data streams, trailing dots or spaces, control bytes, symlinks, hardlinks or special files are rejected, as are names that collide after Unicode normalization. Extraction is bounded at 1,000 files, 10 MiB each and 50 MiB total.

## The 0 to 100 risk score

The score is deterministic: the same files always score the same.

1. Findings are deduplicated by code, file and line, keeping the highest severity.
2. Each finding adds a weight to its category.
3. Each category is capped at 100, and the score is the sum of the six, capped at 100.

| Finding | Weight |
|---|---|
| Structural escape (`sec-symlink-escape`, `sec-path-traversal`) | 90 |
| `CRITICAL` | 55 |
| `HIGH` | 35 |
| `MEDIUM` | 15 |
| `LOW` | 5 |
| `INFO` | 2 |

## How the score becomes a verdict

| Verdict | When it is returned |
|---|---|
| `APPROVE` | Complete scan, no critical or high finding, score 20 or below. |
| `CAUTION` | Any high finding, a score above 20, or an incomplete scan. |
| `REJECT` | Any critical finding, a structural filesystem escape, or a score above 50. |

Abridged output for a deliberately unsafe test skill:

```text
quick-setup: BLOCKED  (risk: 100/100 · REJECT · posture: CRITICAL_DETECTED_RISK · engine: skillporter-static v3.0.0 · sha256: 2906cfd035f7)
  Categories: prompt_injection=70, code_execution=100, data_exfiltration=35, supply_chain=2
  [CRITICAL] sec-prompt-override (SKILL.md:10): Prompt-injection directive attempting to override system/user instructions
  [CRITICAL] sec-curl-pipe-sh (SKILL.md:12): Remote code execution pattern (curl/wget piped directly into shell)
  [INFO] sec-external-download (SKILL.md:12): External network download command referenced
  [MEDIUM] sec-html-comment-instruction (SKILL.md): HTML comment containing imperative execution or override keywords
  [HIGH] sec-credential-harvest (scripts/bootstrap.py:4): Access to sensitive host credential stores (~/.ssh, ~/.aws, /etc/shadow)
  [HIGH] sec-dynamic-eval (scripts/bootstrap.py:5): Dynamic or inline shell/code execution (os.system / eval / exec / shell=True / python -c)
  [HIGH] sec-py-unsafe-subprocess (scripts/bootstrap.py:5): Unsafe subprocess invocation `subprocess.run(..., shell=True)` risks shell injection
```

The arithmetic is in line two: prompt injection adds 55 and 15 for 70; code execution adds 55, 35 and 35, past the category cap to 100; data exfiltration adds 35, supply chain 2. The 207 total is capped at 100.

## SARIF for code scanning

```bash
skillporter scan . --format sarif > skillporter.sarif
```

The output is SARIF 2.1.0, which GitHub code scanning and most review tools accept. Critical and high map to `error`, medium to `warning`, low and informational to `note`. Each code becomes a rule carrying its remediation, and each result points at `<skill-name>/<path>` with a line number, so a review comment lands on the offending line.

To fail a build on risk, add the threshold:

```bash
skillporter scan . --max-risk-score 30
```

It exits 1 when any skill scores above the limit, and the same limit can live in `skillporter.yaml`.

## The sandbox dry run

The sandbox traces what the files appear to touch, without executing anything.

```bash
skillporter sandbox run ./skills/release-notes
```

It is experimental and opt-in. `--runtime auto` probes for `wasmtime` (WASI) and `runsc` (gVisor rootless), then falls back to the built-in tracer. That tracer lists proposed writes, sensitive reads, network calls, tool invocations and environment accesses, and compares a SHA-256 tree hash before and after to show nothing changed. Outbound sockets stay disabled.

```text
Runtime:            dry-run-tracer (requested: auto)
Filesystem mutated: NO (verified by SHA-256 tree hash)
Network mutated:    NO (outbound sockets disabled)
```

The verdict reuses the names: `REJECT` when the static report failed or the score is above 50, `CAUTION` above 20 or when writes or network calls were proposed, `APPROVE` otherwise. It narrows what you must reason about without running the skill.

## Limits

These come from the product's own [security model](/docs/security).

- **Novel prompt injection.** Ordinary prose without known override phrasing can still steer a model. No pattern set catches all of them.
- **Runtime-fetched content.** A URL can serve harmless content at inspection and something else when the agent fetches it later.
- **Obfuscation.** Encoded-payload inspection is bounded; multi-layer encoding, encryption, or logic that only triggers on certain dates or inputs can evade it.
- **Host isolation.** Which tools an agent may call, and what they can reach, is decided by the harness and host. Skillporter does not sandbox the agent.

A clean scan does not prove a skill is safe at runtime.

`--force` overwrites destinations but never skips a security block; `--allow-risky` accepts non-structural findings and logs them, but cannot override a structural escape.

## A pre install routine

```bash
skillporter inspect anthropics/skills --skill pdf
skillporter scan ./skills/release-notes --max-risk-score 30
skillporter add ./skills/release-notes --harness claude-code --dry-run
skillporter sandbox run ./skills/release-notes --runtime dry-run
```

`inspect` resolves a path, archive or repository without installing, then prints the description, formats, script counts, validation issues and security assessment. `scan` re-runs the assessment alone, with `--max-risk-score` turning a threshold into an exit code.

`add --dry-run` validates, scans and prints the install plan and conflicts, then stops; the gate runs first, so a failing skill is blocked here, not at the write. `sandbox run` traces the proposed reach of the package, and `--runtime dry-run` picks the built-in tracer rather than whatever the machine has.

Only then install and pin:

```bash
skillporter add ./skills/release-notes --harness claude-code
skillporter lock --check
```

The lockfile closes a gap the scan cannot: per-file SHA-256 hashes mean content changed after review fails `lock --check` instead of reaching an agent.

The scan removes known hazards and speeds up review, but it does not decide trust. That needs someone reading the instructions and scripts, which the [security scanning reference](/docs/security-scanning) covers.
