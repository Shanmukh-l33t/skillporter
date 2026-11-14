# Contributing to Skillporter

Thanks for helping build the universal package manager for AI-agent skills. Skillporter optimizes for **verified correctness, zero runtime dependencies, and supply-chain safety**.

## Before You Start

- Open an issue describing the bug or feature before starting a large architectural change.
- For a new or updated harness adapter, you **must** link its official vendor documentation proving the exact skill discovery path and precedence.
- Never mark an unverified path as `DOCUMENTATION_VERIFIED`, `INTEGRATION_TESTED`, or `RUNTIME_VERIFIED`; use `UNVERIFIED` until confirmed against upstream docs or runtime tests.

## Development Setup

```bash
git clone https://github.com/Shanmukh-l33t/skillporter
cd skillporter
env -u PYTHONPATH python3 -m venv .venv
env -u PYTHONPATH .venv/bin/pip install -e ".[dev]"
```

## Required Quality Gates Before Opening a PR

```bash
env -u PYTHONPATH .venv/bin/python -m pytest tests/ -v   # all 240+ tests must pass
env -u PYTHONPATH .venv/bin/ruff check .                 # zero lint errors
env -u PYTHONPATH .venv/bin/python -m skillporter validate .
env -u PYTHONPATH .venv/bin/python -m skillporter scan .
```

## Adding a New Harness Adapter

1. Add the `Harness` entry to `HARNESSES` in `skillporter/harnesses.py` with:
   - `support_status` (`NATIVE`, `COMPATIBLE`, `ADAPTED`, `PARTIAL`, `UNSUPPORTED`, `UNVERIFIED`)
   - `verification_level` and `verified_date`
   - `docs` pointing to the official vendor documentation page
   - `paths` (listing the primary install path first, and marking secondary compatibility reads with `is_compatibility=True`)
   - `detection` rules (`binaries`, `user_dirs`, `project_markers`, `env_vars`)
2. Add path assertions in `tests/test_v2_ecosystem.py` so path drift is caught in CI.
3. Update the compatibility table in `README.md` and `docs/harnesses/README.md`.

## Engineering Rules

- **Zero runtime dependencies**: The core library (`skillporter/`) must use the Python 3.9+ standard library only.
- **Never execute untrusted code**: Source resolution, archive extraction, and custom adapter loading must never run `eval`, `exec`, or downloaded scripts.
- **Conventional Commits**: Use `feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`.
