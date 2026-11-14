# Roadmap

See [audits/ROADMAP.md](audits/ROADMAP.md) for the three-generation product roadmap.

## Prioritized Engineering Roadmap Status

- **P0 (Completed)**:
  - Path traversal prevention in `install`, `uninstall`, and `rollback_skill`.
  - Staged directory replacement and restoration of pre-existing installations on partial transaction failure.
  - Archive decompression bomb (Zip-Bomb / Tar-Bomb) byte and entry-count limits.
  - Stop-at-skill-root discovery and symlink cycle protection.
  - Drift-overwrite protection in `skillporter sync`.
- **P1 (Completed)**:
  - Line-anchored `---` YAML frontmatter splitting, UTF-8 BOM handling, and tab-indentation validation.
  - Validation of all copies of a skill in `diagnose()`.
  - Explicit lifecycle states (`FOUND`, `VALID`, `COMPATIBLE`, `INSTALLED`, `VERIFIED`, `UNVERIFIED`, `MISSING`) in `skillporter doctor`.
  - Obfuscated shell execution (`base64 -d | sh`) and HTTP data exfiltration detection in `skillporter scan`.
- **P2 (Completed)**:
  - Comprehensive audit documentation (`docs/ENGINEERING_AUDIT.md`, `docs/audits/TECHNICAL_DEBT.md`, `docs/TESTING.md`, `docs/HARNESS_COMPATIBILITY.md`).
  - Cross-platform CI across Ubuntu (Python 3.9–3.13), macOS, and Windows.
- **P3 (Future)**:
  - Live headless runtime discovery probes (`skillporter verify-runtime`) for harnesses when their CLI binaries are present on the host.
  - Hosted public FastAPI registry index with OIDC package provenance attestations.
