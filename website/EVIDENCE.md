# Evidence ledger

Every product claim on skillporter.dev, where it comes from, and how it is kept true. If a claim cannot be traced to a row here, it should not be on the site.

"Automated" means a check in `tests/site.test.mjs` or a build-time assertion fails when the claim stops being true.

## Product facts

| Claim on the site | Source | Kept true by |
|---|---|---|
| Latest release is v3.0.0 | `skillporter/__init__.py`, `pyproject.toml`, `package.json` | Automated: version test compares all three with the site |
| MIT licensed | `LICENSE`, `package.json` | Automated: read from `package.json` |
| Python 3.9+, no runtime dependencies | `pyproject.toml` (`requires-python`, empty `dependencies`) | Manual review at release |
| Runs locally, no account | The CLI has no login or hosted service | Manual review |
| Available on PyPI as `skillporter` | `https://pypi.org/pypi/skillporter/3.0.0/json` returned 200 on 2026-11-14 | Manual check at release |
| Available on npm as `@shanmukhdheekonda/skillporter` | `npm view @shanmukhdheekonda/skillporter version` returned `3.0.0` on 2026-11-14 | Manual check at release |
| Installer URL `releases/download/v3.0.0/install.sh` | Release asset, HTTP 200 on 2026-11-14 | Automated: URL is derived from the version |

## Harnesses

| Claim on the site | Source | Kept true by |
|---|---|---|
| 19 adapters | `skillporter.harnesses.HARNESSES` | Automated: `generate_site_data.py --check`, row-count test |
| 1 runtime verified, 3 integration tested, 15 fixture tested | `verification_level` of each adapter | Automated: counts test |
| Each harness's support type, tier, paths and vendor link | The adapter record | Automated: per-row test against `harnesses.json` |
| 8 harnesses use `.agents/skills` as primary path, 6 read it as a compatibility path | Computed from adapter paths | Automated: generated count |
| 12 directories for 19 harnesses | Distinct primary project paths in the registry; matches the recorded `add` output | Automated: computed at build time |
| Tier definitions | `HARNESS_COMPATIBILITY_AUDIT.md` | Manual review |
| Claude Code reads only `.claude/skills`; Cline limits the skill body; core Aider needs a conventions file | `notes` and `limitations` in the adapter records | Manual review |

## CLI and output

| Claim on the site | Source | Kept true by |
|---|---|---|
| Every command and flag shown | `skillporter.cli.build_parser()` | Automated: every `skillporter ...` line in code blocks is checked against `cli.json`; the home page asserts at build time |
| Terminal panels | Recorded by `scripts/record_cli_output.py` from skillporter 3.0.0 | Automated: transcripts must carry the recorder header; labelled "Recorded output" |
| The unsafe scan sample | A fixture the recorder writes, scanned by the real CLI | Labelled on the page as a test fixture |
| Lockfile example | `skillporter.lock` written by the CLI during recording | Rendered from the recorded file; shortening is stated |
| Exit codes 0, 1, 2 | `README.md`, `skillporter/commands/common.py` | Manual review |

## Security

| Claim on the site | Source | Kept true by |
|---|---|---|
| What the scanner analyzes | `skillporter/security.py`, `skillporter/scanner_analyzers.py`, `SECURITY.md` | Manual review; finding codes on the scanning page were extracted from the source |
| Risk weights 90, 55, 35, 15, 5, 2 and posture thresholds 50 and 80 | `SECURITY.md` section 2 | Manual review |
| 2 MiB scan cap; 1,000 files, 10 MiB, 50 MiB archive limits | Constants in `security.py` and `sources.py` | Manual review |
| `--force` never bypasses a security block; `--allow-risky` is recorded | `SECURITY.md` 1.3, CLI help text | Manual review |
| MCP is read-only by default; refuses paths outside the workspace | Exercised against the real server on 2026-11-14 | Manual check at release |
| MCP protocol version `2024-11-05`, nine tools | `skillporter/mcp_server.py`, `tools/list` response | Manual check at release |
| "A clean scan does not prove a skill is safe at runtime" and the four limitations | `SECURITY.md` 2.3 | Automated: the sentence and the four limitation headings must be present |
| Pinned digest `8bd7125b...f127179c` for `skillporter.pyz` | `SHA256SUMS.txt` of the v3.0.1 release; downloaded and hashed locally on 2026-11-14 | Automated for 3.0.1: the docs digest must equal the release asset hash |
| Pinned digest `5468ffad...a53c3` for the v3.0.0 asset | `SHA256SUMS.txt` of the v3.0.0 release, confirmed with `gh attestation verify` | Historic, superseded by 3.0.1 |
| The v3.0.0 release has no `SHA256SUMS.txt.sig` | Release asset list on 2026-11-14 | Manual check at release |

## Deliberately absent

The site does not show GitHub stars, download counts, user counts, customer logos, testimonials, certifications, benchmark numbers, a competitor comparison or a roadmap. The tests fail if wording of that kind appears.
