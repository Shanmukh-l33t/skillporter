"""Uninstall / remove and rollback command implementations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import harnesses
from ..audit import record_audit_event
from ..diagnose import resolve_path
from ..install import InstallError, rollback_skill, validate_skill_name_segment
from ..install import uninstall as run_uninstall
from ..state import load_state
from ..ui import action_symbol
from .common import EXIT_ERROR, EXIT_OK, fmt_mode, is_quiet, resolve_target_harnesses


def cmd_uninstall(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    dry_run = bool(getattr(args, "dry_run", False))
    is_json = fmt_mode(args) == "json"

    try:
        skill_name = validate_skill_name_segment(args.skill)
        targets = resolve_target_harnesses(
            args.harness or ["all"],
            root,
            scope=args.scope,
            default_detected=True,
            exclude_harnesses=getattr(args, "exclude_harness", None),
        )
        if dry_run:
            planned = []
            for t in targets:
                h = harnesses.get(t)
                paths = h.project_paths if args.scope == "project" else h.user_paths
                if not paths:
                    continue
                dest = resolve_path(paths[0].path, args.scope, root) / skill_name
                action = "would-remove" if (dest.exists() or dest.is_symlink()) else "not-installed"
                planned.append({"skill": skill_name, "harness": h.name, "dest": str(dest), "action": action})
            if is_json:
                print(json.dumps({"dry_run": True, "results": planned}, indent=2))
            else:
                for row in planned:
                    print(f"{row['action']:14} {row['harness']:14} {row['dest']}")
            return EXIT_OK

        results = run_uninstall(root, skill_name, targets, scope=args.scope, record_state=True)
    except (InstallError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    record_audit_event(
        root,
        interface="cli",
        operation="remove",
        status="succeeded",
        source=skill_name,
        destinations=[str(r.dest) for r in results if r.action == "removed"],
        harnesses=targets,
        scope=args.scope,
    )
    if is_json:
        print(
            json.dumps(
                {
                    "dry_run": False,
                    "results": [
                        {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": r.action}
                        for r in results
                    ],
                },
                indent=2,
            )
        )
        return EXIT_OK

    if not is_quiet(args):
        rem_cnt = sum(1 for r in results if r.action == "removed")
        pres_cnt = sum(1 for r in results if r.action == "preserved-shared")
        print(f"{action_symbol('removed')} Removed {skill_name!r} from {rem_cnt} destination(s) (source preserved)")
        for r in results:
            if r.action != "skipped":
                print(f"  {action_symbol(r.action)} {r.harness:14} {r.action:16} {r.dest}")
        if pres_cnt:
            print("  Note: shared .agents/skills directory retained for active sibling harness(es)")
    return EXIT_OK


def cmd_rollback(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    dry_run = bool(getattr(args, "dry_run", False))
    is_json = fmt_mode(args) == "json"

    if dry_run:
        records = load_state(root, scope=args.scope)
        sname = args.skill.strip()
        names = sorted(records) if sname in ("all", "--all") else [sname]
        previews = []
        for n in names:
            rec = records.get(n)
            if not rec or not rec.history:
                print(f"error: no backup history available to roll back skill {n!r}", file=sys.stderr)
                return EXIT_ERROR
            chosen = rec.history[-1]
            previews.append(
                {
                    "skill": n,
                    "backup_id": chosen.backup_id,
                    "target_version": chosen.version,
                    "tree_hash": chosen.tree_hash,
                    "harnesses": rec.harnesses,
                }
            )
        if is_json:
            print(json.dumps({"dry_run": True, "rollbacks": previews}, indent=2))
        else:
            for p in previews:
                print(f"would-rollback {p['skill']} -> backup {p['backup_id']} (v{p['target_version']})")
        return EXIT_OK

    try:
        results = rollback_skill(
            root,
            args.skill,
            backup_id=args.backup_id or "",
            scope=args.scope,
        )
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    record_audit_event(
        root,
        interface="cli",
        operation="rollback",
        status="succeeded",
        source=args.skill,
        destinations=[str(r.dest) for r in results],
        harnesses=[r.harness for r in results],
        scope=args.scope,
    )
    if is_json:
        print(
            json.dumps(
                {
                    "dry_run": False,
                    "results": [
                        {
                            "skill": r.skill,
                            "harness": r.harness,
                            "dest": str(r.dest),
                            "action": r.action,
                            "detail": r.detail,
                        }
                        for r in results
                    ],
                },
                indent=2,
            )
        )
        return EXIT_OK

    for r in results:
        print(f"{r.action:12} {r.harness:16} {r.dest}  ({r.detail})")
    return EXIT_OK
