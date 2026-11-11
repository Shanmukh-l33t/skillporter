# Testing & Quality Assurance Guide

Skillporter is verified by 95 automated tests across 6 test modules in `tests/`, running on Linux, macOS, and Windows across Python 3.9, 3.10, 3.11, 3.12, and 3.13.

## Running the Test Suite

```bash
env -u PYTHONPATH .venv/bin/python -m pytest tests/ -v
env -u PYTHONPATH .venv/bin/ruff check .
```

## Test Modules

1. `tests/test_skillporter.py` (32 tests) — Core frontmatter parsing, specification validation, harness path matrix, reachability diagnosis, copy/symlink installation, uninstallation, and CLI exit-code contracts.
2. `tests/test_regressions.py` (4 tests) — Multi-harness install deduplication and project/user scope isolation.
3. `tests/test_v2_ecosystem.py` (24 tests) — 19-harness registry, aliases, detection, declarative adapter SDK, SHA-256 content drift, Cursor duplicate detection, portable relative symlinks, format adaptation (`.mdc`, `.instructions.md`), static security scanner, transactional rollback, git repository `add`, `init`/`sync`/`lock`/`doctor`, registry `pack` provenance, MCP JSON-RPC stdio server, and NPX launcher execution.
4. `tests/test_archive_security.py` (16 tests) — Adversarial Zip-Slip, Tar-Slip, Windows backslash traversal (`..\..\`), drive-qualified paths (`C:\`), NUL bytes, symlink/hardlink archive entries, and Git option-injection (`--upload-pack=`) prevention.
5. `tests/test_atomic_writes.py` (9 tests) — Crash-safe atomic file writes (`os.replace` + `fsync`), mid-write failure recovery, permission preservation, and temporary file cleanup.
6. `tests/test_hardening_audit.py` (10 tests) — Regression tests for path traversal in `uninstall`/`install`/`rollback`, pre-existing directory restoration on partial multi-harness install failure, zip/tar decompression bombs, inline `---` and tab indentation in YAML frontmatter, stop-at-skill-root discovery, symlink loop protection, secondary-copy validation, `sync` drift protection, custom adapter traversal rejection, and `doctor` explicit lifecycle states.
