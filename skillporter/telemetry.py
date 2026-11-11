"""Opt-In, Privacy-Preserving Usage Telemetry Hooks.

Design principles:
  * Strictly OPT-IN (default OFF). Only active when ``SKILLPORTER_TELEMETRY=1``
    or ``telemetry.enabled: true`` in ``skillporter.yaml``, and ``DO_NOT_TRACK``
    is not set to ``1``.
  * Local-first & zero-PII: Never transmits data over the network unless an
    explicit ``SKILLPORTER_TELEMETRY_ENDPOINT`` is configured by an enterprise
    team. Never records file paths, git URLs, usernames, or environment secrets.
  * Hashes workspace paths with a one-way SHA-256 digest (12 hex chars).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .manifest import load_manifest
from .state import state_dir


def is_telemetry_enabled(root: Path | None = None) -> bool:
    """Return True only when the user has explicitly opted in and DO_NOT_TRACK is not set."""
    if os.environ.get("DO_NOT_TRACK", "").strip() in ("1", "true", "yes"):
        return False
    env_flag = os.environ.get("SKILLPORTER_TELEMETRY", "").strip().lower()
    if env_flag in ("1", "true", "yes", "on"):
        return True
    if env_flag in ("0", "false", "no", "off"):
        return False
    if root is not None:
        manifest = load_manifest(root)
        if manifest and getattr(manifest, "telemetry", None) and manifest.telemetry.enabled:
            return True
    return False


def record_telemetry_event(
    root: Path,
    command: str,
    exit_code: int,
    *,
    harnesses: list[str] | None = None,
    skills_count: int = 0,
) -> Path | None:
    """Record a privacy-preserving local analytics event when telemetry is opted in."""
    resolved = Path(root).resolve()
    if not is_telemetry_enabled(resolved):
        return None

    anon_ws_id = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    event = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": __version__,
        "workspace_id": anon_ws_id,
        "command": command,
        "exit_code": int(exit_code),
        "harnesses": sorted(set(harnesses or [])),
        "skills_count": int(skills_count),
    }

    sdir = state_dir(resolved)
    sdir.mkdir(parents=True, exist_ok=True)
    log_path = sdir / "telemetry.jsonl"
    with contextlib.suppress(OSError), open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    return log_path
