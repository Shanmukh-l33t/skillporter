"""Structured Security & Lifecycle Audit Logging for Skillporter.

Records security-relevant operations (installations, updates, synchronizations,
removals, rollbacks, MCP calls, blocked scans, and explicit risk-acceptance
overrides) to ``<state_dir>/audit.jsonl``.

Security invariants:
  * Never logs tokens, credentials, private keys, environment variables, or
    complete file contents.
  * Automatically scrubs embedded URL credentials and known token formats from
    source strings and error messages before writing to disk.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from .state import state_dir

AUDIT_SCHEMA_VERSION = 1

_URL_CRED_RE = re.compile(r"(https?://)([^/@\s]+)@")
_TOKEN_SCRUB_RE = re.compile(
    r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
    r"sk-(?:proj|ant)-[A-Za-z0-9_-]{16,}|"
    r"xox[baprs]-[A-Za-z0-9-]{12,}|"
    r"Bearer\s+[A-Za-z0-9._-]+)"
)


def redact_sensitive_text(text: str) -> str:
    """Scrub URL userinfo credentials and recognizable API tokens from *text*."""
    if not text:
        return ""
    scrubbed = _URL_CRED_RE.sub(r"\1[REDACTED]@", str(text))
    scrubbed = _TOKEN_SCRUB_RE.sub("[REDACTED]", scrubbed)
    if "PRIVATE KEY-----" in scrubbed:
        return "[REDACTED_PRIVATE_KEY]"
    return scrubbed


def audit_file(root: Path, *, scope: str = "project", home: Path | None = None) -> Path:
    return state_dir(Path(root).resolve(), scope=scope, home=home) / "audit.jsonl"


def record_audit_event(
    root: Path,
    *,
    interface: str,
    operation: str,
    status: str,
    source: str = "",
    resolved_commit: str = "",
    destinations: list[str] | None = None,
    harnesses: list[str] | None = None,
    scan_results: Mapping[str, object] | None = None,
    overwrite: bool = False,
    force: bool = False,
    risk_accepted: bool = False,
    detail: str = "",
    scope: str = "project",
    home: Path | None = None,
) -> Path | None:
    """Append one structured JSONL audit event to ``.skillporter/audit.jsonl``."""
    resolved_root = Path(root).resolve()
    apath = audit_file(resolved_root, scope=scope, home=home)
    try:
        apath.parent.mkdir(parents=True, exist_ok=True)
        is_new = not apath.exists()
        event: dict[str, object] = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "interface": interface,
            "operation": operation,
            "status": status,
            "source": redact_sensitive_text(source),
            "resolved_commit": resolved_commit,
            "destinations": [redact_sensitive_text(str(d)) for d in (destinations or [])],
            "harnesses": list(harnesses or []),
            "scan_results": scan_results or {},
            "overwrite": bool(overwrite),
            "force": bool(force),
            "risk_accepted": bool(risk_accepted),
            "detail": redact_sensitive_text(detail)[:500],
        }
        line = json.dumps(event, sort_keys=True) + "\n"
        with open(apath, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        if is_new and os.name != "nt":
            with contextlib.suppress(OSError):
                os.chmod(apath, 0o600)
        return apath
    except OSError:
        return None


def load_audit_events(
    root: Path,
    *,
    scope: str = "project",
    home: Path | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Read up to *limit* most recent structured audit events."""
    apath = audit_file(root, scope=scope, home=home)
    if not apath.is_file():
        return []
    events: list[dict[str, object]] = []
    try:
        for line in apath.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                obj = json.loads(s)
                if isinstance(obj, dict):
                    events.append(obj)
    except OSError:
        return []
    return events[-limit:] if limit > 0 else events
