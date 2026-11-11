# Harness Compatibility & Verification Model

_Last verified: 2026-11-11_

Skillporter enforces a strict separation between **filesystem presence**, **specification validity**, **format compatibility**, and **runtime verification**.

## Explicit Lifecycle States (`skillporter doctor`)

| State | Meaning |
|---|---|
| `FOUND` | A directory containing `SKILL.md` was discovered in the workspace. |
| `VALID` / `INVALID` | Whether every copy of `SKILL.md` for this skill passes the Agent Skills specification with zero errors. |
| `COMPATIBLE` / `ADAPTED` | `COMPATIBLE` if the harness natively reads `SKILL.md`; `ADAPTED` if the harness requires controlled rule conversion (e.g. Aider `CONVENTIONS.md` or `--read`). |
| `INSTALLED` / `MISSING` | Whether the skill is present in at least one directory scanned by the harness at the requested scope. |
| `DRIFT` | Multiple copies of the skill exist in the workspace with different SHA-256 tree hashes. |
| `DUPLICATE` | The skill exists in two or more distinct directories scanned simultaneously by the same harness (e.g., `.agents/skills` and `.cursor/skills` in Cursor). |
| `VERIFIED` / `UNVERIFIED` | `VERIFIED` is reported **only** when the harness adapter has `verification_level == "RUNTIME_VERIFIED"` (live runtime ingestion confirmed). Document-verified and unit/integration-tested adapters report `UNVERIFIED` at runtime until probed against a live agent process. |

See [docs/harnesses/README.md](harnesses/README.md) and [HARNESS_COMPATIBILITY_AUDIT.md](../HARNESS_COMPATIBILITY_AUDIT.md) for the complete 19-harness table and upstream documentation URLs.
