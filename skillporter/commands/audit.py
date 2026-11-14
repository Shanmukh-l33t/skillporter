"""Installed skill supply-chain & audit trail inspection command (`skillporter audit`)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import __version__
from ..audit import load_audit_events
from ..ci_report import check_lockfile_staleness
from ..diagnose import diagnose as run_diagnose
from ..manifest import LOCKFILE_FILENAME, load_manifest
from ..security import scan_skill
from ..state import load_state
from ..ui import badge
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode


def cmd_audit(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return EXIT_ERROR

    scope = getattr(args, "scope", "project")
    limit = int(getattr(args, "limit", 50))
    diag = run_diagnose(root, scope=scope)
    records = load_state(root, scope=scope)
    manifest = load_manifest(root)
    max_risk = manifest.max_risk_score if manifest else None

    lock_issues: list[str] = []
    if (root / LOCKFILE_FILENAME).is_file():
        lock_issues = check_lockfile_staleness(root, scope=scope)

    skill_audits: dict[str, dict[str, object]] = {}
    blocked = False
    for sname, copies in sorted(diag.skill_copies.items()):
        rep = scan_skill(copies[0])
        exceeds = rep.exceeds_risk_threshold(max_risk)
        if not rep.passed or rep.has_structural_escape or exceeds:
            blocked = True
        rec = records.get(sname)
        skill_audits[sname] = {
            "managed": rec is not None,
            "source": rec.source if rec else "untracked",
            "resolved_commit": rec.resolved_commit if rec else "",
            "version": rec.version if rec else "untracked",
            "posture": rep.posture,
            "scan_complete": rep.scan_complete,
            "risk_score": rep.risk_score,
            "recommendation": rep.recommendation,
            "tree_hash": rep.tree_hash,
            "findings_count": len(rep.findings),
        }

    events = load_audit_events(root, scope=scope, limit=limit)
    risk_overrides = [ev for ev in events if ev.get("risk_accepted") is True]
    healthy = not blocked and not diag.drifted and not lock_issues

    payload = {
        "root": str(root),
        "healthy": healthy,
        "skills": skill_audits,
        "drifted": diag.drifted,
        "lockfile_issues": lock_issues,
        "risk_overrides_count": len(risk_overrides),
        "audit_events": events,
    }
    if fmt_mode(args) == "json":
        print(json.dumps(payload, indent=2))
        return EXIT_OK if healthy else EXIT_PROBLEM

    print(f"skillporter {__version__} — supply-chain security audit for {root}\n")
    print(f"Installed/discovered skills: {len(skill_audits)}")
    print(f"Recorded audit log events:   {len(events)} ({len(risk_overrides)} explicit risk override(s))")
    print(f"Lockfile integrity issues:   {len(lock_issues)}")
    for sname, info in skill_audits.items():
        origin = f"{info['source']}" + (f"@{str(info['resolved_commit'])[:12]}" if info["resolved_commit"] else "")
        print(
            f"  - {sname:18} {info['posture']:22} "
            f"(risk: {info['risk_score']}/100 · origin: {origin})"
        )
    for li in lock_issues:
        print(f"  [lockfile] {li}")
    print(f"\nVerdict: {badge('HEALTHY' if healthy else 'ACTION REQUIRED')}")
    return EXIT_OK if healthy else EXIT_PROBLEM
