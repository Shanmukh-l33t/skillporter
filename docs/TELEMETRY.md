# Privacy-Preserving Opt-In Telemetry (`skillporter/telemetry.py`)

## Principles

1. **Strictly Opt-In (Default OFF)**: Skillporter records **zero** usage analytics by default.
2. **Honors `DO_NOT_TRACK=1`**: Setting `DO_NOT_TRACK=1` (or `true`) unconditionally disables telemetry regardless of any other setting.
3. **Local-First & Zero PII**: When opted in via `SKILLPORTER_TELEMETRY=1` or `telemetry.enabled: true` in `skillporter.yaml`, events are appended to `.skillporter/telemetry.jsonl` inside the workspace. No file paths, repository URLs, usernames, environment variables, or skill contents are ever recorded. The workspace path is hashed with a one-way SHA-256 digest truncated to 12 hex characters (`workspace_id`).

## Opting In or Out

Enable in `skillporter.yaml`:

```yaml
schema_version: 2
project: my-project
telemetry:
  enabled: true
```

Or via environment variable:

```bash
export SKILLPORTER_TELEMETRY=1
```

## Recorded Event Schema (`.skillporter/telemetry.jsonl`)

```json
{
  "command": "diagnose",
  "exit_code": 0,
  "harnesses": ["claude-code", "codex", "cursor"],
  "schema_version": 1,
  "skills_count": 3,
  "timestamp": "2026-11-11T12:00:00Z",
  "version": "2.4.0",
  "workspace_id": "a1b2c3d4e5f6"
}
```
