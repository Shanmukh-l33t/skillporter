# Contributing

Skillporter optimizes for verified correctness, zero runtime dependencies and supply-chain safety. Contributions that keep those three properties are welcome.

## Before you start

- Open an issue before a large architectural change.
- A new or changed harness adapter must link the vendor documentation that proves the discovery path and precedence.
- Never raise an adapter's verification tier without the evidence that tier requires. Use `UNVERIFIED` until it is confirmed.

## Development setup

```bash
git clone https://github.com/Shanmukh-l33t/skillporter
cd skillporter
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Quality gates

Run these before opening a pull request. CI runs the same checks on Linux, macOS and Windows.

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check .
.venv/bin/python -m skillporter validate .
.venv/bin/python -m skillporter scan .
```

## Engineering rules

- **Standard library only.** The core package must not gain a runtime dependency.
- **Never execute untrusted content.** Source resolution, extraction and adapter loading must not `eval`, `exec` or run downloaded scripts.
- **Every security fix needs a regression test.**
- **No mocks in place of integration tests.** The suite uses real temporary workspaces, Git repositories, archives and subprocesses.
- **Conventional Commits.** `feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`.

## Adding a harness adapter

1. Add a `Harness` entry to `HARNESSES` in `skillporter/harnesses.py` with its paths, support type, verification tier, detection rules and vendor documentation link. List the primary install path first and mark compatibility reads with `is_compatibility=True`.
2. Add it to the conformance suite in `tests/test_adapter_conformance.py`.
3. Regenerate the website data and the documentation table:

   ```bash
   python3 website/scripts/generate_site_data.py
   ```

   CI fails if the committed data does not match the registry.

## Working on the website

```bash
cd website
npm ci
npm run dev
npm run verify
```

`npm run verify` checks the generated data against the Python registry, type-checks, builds the site and runs the content tests. See `website/README.md`.

## Documentation

The pages under `docs/` are the source for both GitHub and [skillporter.dev/docs](https://skillporter.dev/docs). Edit the Markdown there. Do not show a command or flag in the documentation unless it exists in the CLI. The website tests check commands and flags against the real argument parser.

## Security reports

Do not open a public issue for a vulnerability. Use [GitHub Security Advisories](https://github.com/Shanmukh-l33t/skillporter/security/advisories/new).

## License

Contributions are accepted under the project's [MIT license](../../LICENSE). The root [CONTRIBUTING.md](../../CONTRIBUTING.md) and [code of conduct](../../CODE_OF_CONDUCT.md) also apply.
