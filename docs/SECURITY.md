# Security Model & Defensive Controls

See the root [SECURITY.md](../SECURITY.md) and [SECURITY_AUDIT.md](../SECURITY_AUDIT.md) for the full threat model and audit report.

## Summary of Defensive Layers

1. **Zero Script Execution**: Skillporter never executes scripts bundled inside a skill (`scripts/*`, hooks, or setup files) during cloning, archive extraction, validation, or installation.
2. **Hardened Git & Archive Ingestion (`skillporter/sources.py`)**:
   - Rejects git refs starting with `-` or containing `..` (`_validate_git_ref`) and passes `--` before the repository URL.
   - Runs `git clone` with `-c protocol.ext.allow=never -c core.fsmonitor=false -c core.symlinks=false`.
   - Normalizes both `/` and `\` in archive member paths, rejecting `..`, absolute paths, drive-qualified paths, NUL bytes, symlinks, hardlinks, and special device files.
   - Streams archive extraction with hard caps: `MAX_ARCHIVE_FILES = 1000`, `MAX_SINGLE_FILE_BYTES = 10 MiB`, and `MAX_TOTAL_ARCHIVE_BYTES = 50 MiB`.
3. **Path Boundary & Transactional Safety (`skillporter/install.py`, `skillporter/atomic.py`)**:
   - Validates every skill name segment (`validate_skill_name_segment`) so `install`, `uninstall`, and `rollback` can never traverse outside the target harness directory.
   - Stages directory replacements in `.skillporter/tmp/` and restores pre-existing installations if any target in a multi-harness transaction fails.
   - Uses atomic `os.replace` + `fsync` (`atomic_write_text`) and advisory file locking (`workspace_lock`).
4. **Static Security Assessment (`skillporter scan`)**:
   - Labels all results `STATIC_SECURITY_ASSESSMENT` and explicitly disclaims runtime guarantees.
   - Detects embedded secrets (`sec-private-key`, `sec-aws-key`, `sec-github-token`, `sec-api-key`), prompt-injection overrides (`sec-prompt-override`), hidden zero-width/bidi Unicode (`sec-hidden-unicode`), HTML comment instructions (`sec-html-comment-instruction`), shell pipe execution (`sec-curl-pipe-sh`, `sec-obfuscated-exec`), reverse shells (`sec-reverse-shell`), credential harvesting (`sec-credential-harvest`), data exfiltration (`sec-data-exfil`), and symlink escapes (`sec-symlink-escape`).
