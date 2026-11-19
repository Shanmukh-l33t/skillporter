"""Uninstall / remove and rollback command implementations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import harnesses
from ..atomic import workspace_lock
from ..audit import record_audit_event
from ..diagnose import load_custom_harness_paths, resolve_path, scan_location
from ..install import InstallError, rollback_skill, uninstall_paths, validate_skill_name_segment
from ..install import uninstall as run_uninstall
from ..manifest import LockfileError, load_lockfile, load_manifest, save_lockfile, save_manifest
from ..state import load_state
from ..ui import action_symbol
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode, is_quiet, resolve_target_harnesses


def _planned_rows(root: Path, skill_name: str, targets: list[str], scope: str) -> list[dict[str, str]]:
    labels = {"removed": "would-remove", "skipped": "not-installed"}
    return [
        {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": labels.get(r.action, r.action)}
        for r in run_uninstall(root, skill_name, targets, scope=scope, dry_run=True)
    ]


def _distinct_by_destination(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Collapse rows that share one destination (e.g. several harnesses on ``.agents/skills``) into one row."""
    merged: dict[str, dict[str, str]] = {}
    for row in rows:
        cur = merged.get(row["dest"])
        if cur is None:
            merged[row["dest"]] = dict(row)
            continue
        names = cur["harness"].split(",")
        if row["harness"] not in names:
            cur["harness"] = ",".join([*names, row["harness"]])
        if row["action"] == "would-remove":
            cur["action"] = "would-remove"
    return list(merged.values())


def _confirm_removal(
    args: argparse.Namespace, skill_name: str, rows: list[dict[str, str]], is_json: bool
) -> int | None:
    """Preview a no-``--harness`` removal and ask for consent. Returns an exit code to stop, or None to proceed."""
    distinct = _distinct_by_destination(rows)
    out = sys.stderr if is_json else sys.stdout
    for row in distinct:
        print(f"{row['action']:14} {row['harness']:14} {row['dest']}", file=out)
    if getattr(args, "yes", False) or getattr(args, "force", False):
        return None
    stdin = sys.stdin
    if stdin is not None and stdin.isatty():
        print(f"Remove {skill_name!r} from {len(distinct)} destination(s)? [y/N] ", end="", file=out, flush=True)
        try:
            answer = input()
        except EOFError:
            answer = ""
        if answer.strip().lower() in ("y", "yes"):
            return None
        print("aborted: nothing was removed", file=sys.stderr)
        return EXIT_PROBLEM
    print(
        f"error: refusing to remove {skill_name!r} from {len(distinct)} destination(s) without confirmation; "
        "pass -y/--yes to confirm, use --harness to target specific harnesses, or --dry-run to preview",
        file=sys.stderr,
    )
    return EXIT_ERROR


def _remaining_install_destinations(root: Path, skill_name: str, scope: str) -> set[Path]:
    """Resolved harness install destinations that still hold *skill_name* (the source dir is never counted)."""
    custom = load_custom_harness_paths(root, scope=scope)
    found: set[Path] = set()
    for hname in harnesses.names():
        h = harnesses.get(hname)
        raws = [sp.path for sp in (h.project_paths if scope == "project" else h.user_paths)]
        if hname in custom:
            raws.append(custom[hname])
        for raw in raws:
            dest = resolve_path(raw, scope, root) / skill_name
            if dest.exists() or dest.is_symlink():
                found.add(dest.resolve())
    return found


def _update_manifest_and_lock(
    root: Path, skill_name: str, targets: list[str], remaining: list[str], *, keep_manifest: bool
) -> None:
    """Drop a fully removed skill from skillporter.yaml / skillporter.lock; trim harnesses on partial removal."""
    if keep_manifest:
        return
    try:
        manifest = load_manifest(root)
        if manifest is not None:
            changed = False
            if not remaining:
                kept = [s for s in manifest.skills if s.name != skill_name]
                changed = len(kept) != len(manifest.skills)
                manifest.skills = kept
            else:
                gone = {harnesses.get(t).name for t in targets}
                for spec in manifest.skills:
                    if spec.name == skill_name:
                        effective = spec.harnesses or manifest.harnesses
                        left = [h for h in effective if harnesses.get(h).name not in gone] or remaining
                        if left != spec.harnesses:
                            spec.harnesses = left
                            changed = True
            if changed:
                save_manifest(root, manifest)
        lock = load_lockfile(root, warn_migration=False)
        if skill_name in lock.skills:
            if not remaining:
                del lock.skills[skill_name]
                save_lockfile(root, lock)
            elif lock.skills[skill_name].installed_targets != remaining:
                lock.skills[skill_name].installed_targets = remaining
                save_lockfile(root, lock)
    except (KeyError, LockfileError, OSError, ValueError) as exc:
        print(f"warning: could not update skillporter manifest/lock for {skill_name!r}: {exc}", file=sys.stderr)


def cmd_uninstall(args: argparse.Namespace) -> int:
    import shutil

    root = Path(args.path).expanduser().resolve()
    dry_run = bool(getattr(args, "dry_run", False))
    purge_source = bool(getattr(args, "purge_source", False))
    is_json = fmt_mode(args) == "json"

    try:
        skill_name = validate_skill_name_segment(args.skill)
        records = load_state(root, scope=args.scope)
        rec = records.get(skill_name)

        if args.harness:
            targets = resolve_target_harnesses(
                args.harness,
                root,
                scope=args.scope,
                default_detected=True,
                exclude_harnesses=getattr(args, "exclude_harness", None),
            )
        else:
            managed_owners = list(rec.harnesses) if rec and rec.harnesses else []
            combined_owners = list(managed_owners)
            custom = load_custom_harness_paths(root, scope=args.scope)
            for name in harnesses.names():
                if name in managed_owners:
                    continue
                h = harnesses.get(name)
                paths = uninstall_paths(h, args.scope, custom, include_compatibility=not managed_owners)
                if any(
                    skill_name in scan_location(name, raw, args.scope, root, recursive=h.recursive).skill_dirs
                    for raw in paths
                ):
                    combined_owners.append(name)
            if not combined_owners:
                print(
                    f"error: skill {skill_name!r} is not installed in {args.scope} scope (run `skillporter list`)",
                    file=sys.stderr,
                )
                return EXIT_PROBLEM
            targets = resolve_target_harnesses(
                combined_owners,
                root,
                scope=args.scope,
                default_detected=False,
                exclude_harnesses=getattr(args, "exclude_harness", None),
            )

        if dry_run:
            planned = _planned_rows(root, skill_name, targets, args.scope)
            if is_json:
                print(json.dumps({"dry_run": True, "results": planned}, indent=2))
            else:
                # One line per destination: the harnesses after the first read the same directory.
                for row in _distinct_by_destination(planned):
                    print(f"{row['action']:14} {row['harness']:40} {row['dest']}")
            return EXIT_OK

        if not args.harness:
            stop = _confirm_removal(args, skill_name, _planned_rows(root, skill_name, targets, args.scope), is_json)
            if stop is not None:
                return stop

        with workspace_lock(root):
            results = run_uninstall(root, skill_name, targets, scope=args.scope, record_state=True)
            if args.scope == "project" and (rec is not None or any(r.action == "removed" for r in results)):
                remaining = load_state(root).get(skill_name)
                _update_manifest_and_lock(
                    root,
                    skill_name,
                    targets,
                    remaining.harnesses if remaining else [],
                    keep_manifest=bool(getattr(args, "keep_manifest", False)),
                )
    except (InstallError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    purged_source_path = ""
    if purge_source and rec and rec.source:
        post_records = load_state(root, scope=args.scope)
        remaining_copies = _remaining_install_destinations(root, skill_name, args.scope)
        raw_cand = Path(rec.source).expanduser()
        cand_src = (root / raw_cand).resolve() if not raw_cand.is_absolute() else raw_cand.resolve()
        is_safe_to_purge = (
            skill_name not in post_records
            and cand_src not in remaining_copies
            and cand_src.is_dir()
            and cand_src.is_relative_to(root)
            and cand_src != root
            and (cand_src / "SKILL.md").is_file()
        )
        if is_safe_to_purge:
            shutil.rmtree(cand_src, ignore_errors=True)
            purged_source_path = str(cand_src)

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
        payload: dict[str, object] = {
            "dry_run": False,
            "results": [
                {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": r.action}
                for r in results
            ],
        }
        if purged_source_path:
            payload["purged_source"] = purged_source_path
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    if not is_quiet(args):
        rem_cnt = sum(1 for r in results if r.action == "removed")
        pres_cnt = sum(1 for r in results if r.action == "preserved-shared")
        src_note = "local source purged" if purged_source_path else "source preserved"
        print(f"{action_symbol('removed')} Removed {skill_name!r} from {rem_cnt} destination(s) ({src_note})")
        for r in results:
            if r.action != "skipped":
                print(f"  {action_symbol(r.action)} {r.harness:14} {r.action:16} {r.dest}")
        if pres_cnt:
            print("  Note: shared installation retained for other harnesses")
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
