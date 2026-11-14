# Testing & Quality Assurance Guide

Skillporter 3.0 is verified by **198 automated tests** across **16 test modules** in `tests/`, exercising real temporary workspaces, real Git repositories, real ZIP/TAR archives, real subprocess `SIGKILL` crashes, real `flock` contention, and real local HTTP installer servers without substituting mocks for integration paths.

## Running the Test Suite & Linting

```bash
env -u PYTHONPATH .venv/bin/python -m pytest tests/ -v
env -u PYTHONPATH .venv/bin/ruff check .
env -u PYTHONPATH .venv/bin/bandit -r skillporter -ll -q
```

## Test Suite Breakdown

1. `tests/test_p0_security.py` — P0 regression tests: MCP workspace boundary escape prevention, `scope='user'` isolation, boolean type confusion rejection, `--force` vs `--allow-risky` / `accept_risk` separation across CLI and MCP, and `install.sh` supply-chain trust model (mutable ref rejection, pinned SHA-256, OpenSSL signature tamper detection, `gh attestation verify`, atomic upgrade preservation).
2. `tests/test_security_corpus.py` — Adversarial & benign security corpus: Python AST rules (aliased `shell=True`, `pickle`, dynamic imports, hex `exec`, `socket`+`dup2` reverse shell, credential reads), JS/TS rules, Markdown comment smuggling/exfiltration/unsafe delegation, bounded Base64/Hex/PowerShell `-EncodedCommand` decoding, cross-file staged execution chains, oversized/unreadable `INCOMPLETE_ASSESSMENT`, and benign developer false-positive checks.
3. `tests/test_mcp_hardening.py` — MCP read/write permission separation (default-deny writes), prompt-injected tool arguments, failed multi-skill batch rollback, secret-scrubbed `.skillporter/audit.jsonl`, and malformed JSON-RPC (`-32700` / `-32600`) handling.
4. `tests/test_archive_txn_hardening.py` — Unicode NFC/NFD collisions, Windows reserved device names/ADS/trailing dots, ZIP special modes, TAR setuid stripping, malformed headers, symlinked parent directory escapes, multi-target `SIGKILL` partial-swap rollback, `ENOSPC` rollback, and concurrent multi-process installs.
5. `tests/test_lockfile_reproducibility.py` — Equivalent reproduction across workspaces, moved-branch commit pinning, upstream content-mutation blocking, corrupted JSON & unsupported `schema_version` `LockfileError`, missing dependencies, and concurrent multi-process `sync`.
6. `tests/test_adapter_conformance.py` — Parametrized 19-adapter conformance lifecycle (project & user scopes, structure, metadata, adaptations, conflicts, and shared `.agents/skills` reference-safe removal).
7. `tests/test_cli_dx_and_commands.py` — Modular `skillporter/commands/*` architecture, version parity across Python/npm manifests, `--dry-run` & `--json` contracts, `skillporter audit`, and GitHub Actions workflow injection/gate verification.
8. `tests/test_archive_security.py`, `tests/test_atomic_writes.py`, `tests/test_hardening_audit.py`, `tests/test_infrastructure_orchestration.py`, `tests/test_regressions.py`, `tests/test_release_gate.py`, `tests/test_roadmap_workstreams.py`, `tests/test_skillporter.py`, `tests/test_v2_ecosystem.py` — Core spec validation, atomic writes, crash recovery, SARIF 2.1.0, semver resolution, standalone `.pyz`, and `npx` launcher suites.
