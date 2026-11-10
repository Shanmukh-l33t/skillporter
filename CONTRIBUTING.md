# Contributing

Thanks for helping. This project optimises for *correct* over *large*.

## Before you start

- Open an issue describing the problem before a large change.
- For a new harness, link its **official documentation** for the skill path.
  Unverified paths must be marked `verified=False` in
  `skillporter/harnesses.py`.

## Development setup

```bash
git clone https://github.com/Shanmukh-l33t/skillporter
cd skillporter
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Required before a PR is accepted

```bash
.venv/bin/python -m pytest tests/ -q   # all tests pass
.venv/bin/ruff check .                 # no lint errors
```

Both must be clean. A PR that skips either will be sent back.

## Adding a harness

1. Add the entry to `HARNESSES` in `skillporter/harnesses.py`, with `docs=`
   pointing at the vendor page you verified the path on.
2. Add the path assertion to `test_matrix_paths_match_published_docs` so drift
   is caught.
3. Update the compatibility table in `README.md`.

## Style

- No new runtime dependencies. The CLI must run on a bare Python install.
- Type hints on public functions.
- Every bug you fix gets a regression test that fails before the fix.
- Keep `SKILL.md` under ~5k tokens; move detail into `references/`.

## Commit messages

Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
