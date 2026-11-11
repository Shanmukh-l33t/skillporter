# Security & Supply-Chain Protection

Skills are code and natural-language instructions injected directly into an AI agent's context window. Skillporter treats third-party skills as untrusted supply-chain artifacts.

## What `skillporter scan` Checks

1. **Secrets & Private Keys**:
   - `sec-private-key` (`CRITICAL`): PEM private keys (`BEGIN ... PRIVATE KEY`).
   - `sec-aws-key` (`HIGH`): AWS access key IDs (`AKIA...`, `ASIA...`).
   - `sec-github-token` (`HIGH`): GitHub PATs (`ghp_...`, `github_pat_...`).
   - `sec-api-key` (`HIGH`): OpenAI, Anthropic, and Slack tokens.
2. **Prompt Injection & Covert Instruction Manipulation**:
   - `sec-prompt-override` (`CRITICAL`): Directives instructing the agent to ignore prior/system instructions or hide actions from the user.
   - `sec-hidden-unicode` (`HIGH`): Zero-width spaces or bidirectional override characters used to smuggle invisible instructions.
   - `sec-html-comment-instruction` (`MEDIUM`): HTML comments containing shell or override commands.
3. **Dangerous Script Patterns**:
   - `sec-curl-pipe-sh` (`CRITICAL`): Piping `curl` or `wget` directly into `sh`/`bash`.
   - `sec-reverse-shell` (`CRITICAL`): `/dev/tcp/`, `nc -e`, or `socat exec:` reverse shells.
   - `sec-credential-harvest` (`HIGH`): Reading `~/.ssh/id_*`, `~/.aws/credentials`, `/etc/shadow`, `.npmrc`, or `.pypirc`.
   - `sec-dynamic-eval` (`MEDIUM`): `eval()`, `exec()`, or `subprocess(..., shell=True)` in bundled scripts.
4. **Filesystem & Archive Integrity**:
   - `sec-symlink-escape` (`CRITICAL`): Symlinks resolving outside the skill root.
   - `sec-path-traversal` (`CRITICAL`): `..` traversal or Zip-Slip / Tar-Slip archive entries.
   - `sec-binary-artifact` (`MEDIUM`): Precompiled binaries (`.exe`, `.so`, `.dylib`, `.dll`, `.bin`).

## Assessment Classification

All reports carry `"assessment_type": "STATIC_SECURITY_ASSESSMENT"`. Static scanning does not execute scripts and does not guarantee runtime safety.
