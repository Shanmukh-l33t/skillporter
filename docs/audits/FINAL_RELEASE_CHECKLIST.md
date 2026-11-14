# Release Acceptance Checklist — Skillporter 3.0

Every mandatory condition below must pass with verifiable evidence before tagging or publishing a public release.

## 1. Mandatory Security & Reliability Acceptance Gates

- [x] **MCP workspace boundary enforced**: Caller-supplied absolute paths, `../` traversal, symlinks, UNC paths, and Windows drive paths cannot escape or redefine workspace root (`tests/test_p0_security.py`).
- [x] **MCP boolean & type confusion rejected**: `"false"`, `"0"`, integers, invalid harness IDs, and malformed JSON-RPC messages fail closed (`tests/test_p0_security.py`, `tests/test_mcp_hardening.py`).
- [x] **MCP default-deny write policy**: Mutating MCP tools (`add`, `install`, `sync`, `remove`) are blocked unless `--allow-writes` or `SKILLPORTER_MCP_ALLOW_WRITES=1` is explicitly enabled (`tests/test_mcp_hardening.py`).
- [x] **Conflict force separated from risk override**: `--force` / `force=true` never bypasses static security gates across `add`, `install`, `sync`, or `update`; `--allow-risky` / `accept_risk=true` displays findings, logs to `.skillporter/audit.jsonl`, and never overrides structural escapes (`tests/test_p0_security.py`).
- [x] **Installer supply-chain integrity**: `install.sh` has zero mutable-`main` fallback, validates `SHA256SUMS.txt`, fails closed without independent provenance (`gh attestation verify`, `SKILLPORTER_SHA256`, or OpenSSL signature), and installs atomically (`tests/test_p0_security.py`).
- [x] **Archive & transaction recovery hardened**: Rejects Unicode NFC/NFD collisions, Windows reserved names, special modes, escaping parent symlinks, and rolls back partial multi-target installs on `SIGKILL` (`tests/test_archive_security.py`, `tests/test_archive_txn_hardening.py`, `tests/test_release_gate.py`).
- [x] **Incomplete scans reported honestly**: Oversized (>2 MiB) and unreadable files set `scan_complete: false` and `posture: INCOMPLETE_ASSESSMENT`, never `APPROVE` (`tests/test_security_corpus.py`).
- [x] **Lockfile reproducibility & corruption safety**: Corrupted JSON and unsupported `schema_version` raise `LockfileError`; `sync` honors pinned commits across moved branches and blocks unexpected upstream hash changes (`tests/test_lockfile_reproducibility.py`).
- [x] **Evidence-based 19-harness conformance**: Shared `.agents/skills` directories survive partial harness removal; only runtime-tested harnesses claim `RUNTIME_VERIFIED` (`tests/test_adapter_conformance.py`).

## 2. Pre-Publish Release Commands

```bash
# 1. Lint & SAST
env -u PYTHONPATH .venv/bin/ruff check .
env -u PYTHONPATH .venv/bin/bandit -r skillporter -ll -q

# 2. Full automated test suite
env -u PYTHONPATH .venv/bin/pytest tests/ -v

# 3. Build & validate Python wheel + sdist
env -u PYTHONPATH .venv/bin/pyproject-build --outdir dist-py
env -u PYTHONPATH .venv/bin/twine check dist-py/*

# 4. Build standalone zipapp + SHA256SUMS.txt & verify npm wrapper
env -u PYTHONPATH .venv/bin/python scripts/build_standalone.py
(cd dist && sha256sum -c SHA256SUMS.txt)
./dist/skillporter.pyz --version
node npm/bin/skillporter.js --version
npm pack --dry-run
```

## 3. Cross-Platform CI Gate Prior to Public Release

- [ ] Push release branch to GitHub (requires owner authorization) and confirm green matrix across `ubuntu-22.04` (py3.9), `ubuntu-latest` (py3.10–3.13), `macos-latest` (py3.12), and `windows-latest` (py3.12) in `.github/workflows/ci.yml` before publishing to PyPI/npm.
