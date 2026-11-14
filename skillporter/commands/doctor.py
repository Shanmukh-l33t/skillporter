"""Diagnose, doctor, detect, matrix, status, demo, and ci-report commands."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path

from .. import __version__, harnesses
from ..ci_report import generate_ci_report, post_github_pr_comment
from ..demo import run_demo
from ..diagnose import diagnose as run_diagnose
from ..install import InstallError
from ..install import install as run_install
from ..manifest import LOCKFILE_FILENAME, MANIFEST_FILENAME, LockfileError, load_lockfile, load_manifest
from ..security import compute_tree_hash, scan_skill
from ..state import ManagedSkillRecord, load_state, state_dir
from ..ui import badge, render_table
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode, is_verbose, latest_tree_mtime_ns


def print_matrix(as_json: bool, category: str | None = None, *, verbose: bool = False) -> int:
    rows = []
    for name in harnesses.names():
        h = harnesses.get(name)
        if category and h.category != category:
            continue
        rows.append(
            {
                "harness": h.name,
                "display_name": h.label,
                "category": h.category,
                "support_status": h.support_status,
                "verification_level": h.verification_level,
                "verification_evidence": h.verification_evidence,
                "verified_date": h.verified_date,
                "verified": h.verified,
                "recursive": h.recursive,
                "project_paths": [p.path for p in h.project_paths],
                "user_paths": [p.path for p in h.user_paths],
                "capabilities": {
                    "allowed_tools": h.capabilities.allowed_tools,
                    "context_fork": h.capabilities.context_fork,
                    "hooks": h.capabilities.hooks,
                    "recursive": h.capabilities.recursive_discovery,
                    "adapted_format": h.capabilities.adapted_format,
                },
                "docs": h.docs,
                "notes": list(h.notes),
                "limitations": list(h.limitations),
            }
        )
    if as_json:
        print(json.dumps(rows, indent=2))
        return EXIT_OK

    print(f"skillporter {__version__} — universal harness compatibility matrix ({len(rows)} harnesses)\n")
    width = max(len(r["harness"]) for r in rows)
    print(f"{'HARNESS'.ljust(width)}  {'SUPPORT':10}  {'VERIFICATION':22}  PRIMARY PROJECT PATH")
    print(f"{'-' * width}  {'-' * 10}  {'-' * 22}  {'-' * 36}")
    for r in rows:
        proj = r["project_paths"][0] if r["project_paths"] else "(user-only: " + ", ".join(r["user_paths"]) + ")"
        if len(r["project_paths"]) > 1:
            proj += f" (+{len(r['project_paths']) - 1} compat)"
        print(
            f"{r['harness'].ljust(width)}  "
            f"{r['support_status']:10}  "
            f"{r['verification_level']:22}  "
            f"{proj}"
        )
    if verbose:
        print("\nNotes:")
        for r in rows:
            for n in r["notes"]:
                print(f"  {r['harness']}: {n}")
    else:
        print("\nTip: pass --verbose or run `skillporter harness inspect <id>` for per-harness notes.")
    return EXIT_OK


def cmd_matrix(args: argparse.Namespace) -> int:
    return print_matrix(fmt_mode(args) == "json", getattr(args, "category", None), verbose=is_verbose(args))


def cmd_diagnose(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"error: {root} does not exist (verify the directory path)", file=sys.stderr)
        return EXIT_ERROR

    selected = args.harness or None
    if selected and "all" in selected:
        selected = harnesses.names()

    diag = run_diagnose(root, only=selected, scope=args.scope)
    fmt = fmt_mode(args)

    if fmt == "json":
        payload = {
            "root": str(diag.root),
            "scope": args.scope,
            "skills": diag.skill_names,
            "drifted": diag.drifted,
            "duplicates": diag.duplicates,
            "harnesses": {
                name: {
                    "verified": r.verified,
                    "support_status": r.support_status,
                    "verification_level": r.verification_level,
                    "reachable_skills": sorted(r.reachable_skills),
                    "drifted_skills": sorted(r.drifted_skills),
                    "duplicate_skills": r.duplicate_skills,
                    "locations": [
                        {
                            "path": str(loc.resolved),
                            "status": loc.status,
                            "skills": loc.skill_dirs,
                            "broken_links": loc.broken_links,
                            "skill_hashes": loc.skill_hashes,
                        }
                        for loc in r.locations
                    ],
                }
                for name, r in diag.reports.items()
            },
            "issues": {
                path: [{"level": i.level, "code": i.code, "message": i.message} for i in issues]
                for path, issues in diag.issues.items()
            },
            "findings": diag.findings,
        }
        print(json.dumps(payload, indent=2))
        return EXIT_PROBLEM if diag.findings else EXIT_OK

    print(f"skillporter {__version__} — diagnosing {diag.root} (scope: {args.scope})\n")
    if not diag.skills:
        print("no SKILL.md found under this path.")
        return EXIT_PROBLEM

    print(f"skills found: {', '.join(diag.skill_names)}\n")

    if selected:
        names = [harnesses.get(h).name for h in selected]
    else:
        active = [
            name
            for name, rep in diag.reports.items()
            if rep.reachable_skills or any(loc.exists for loc in rep.locations)
        ]
        names = sorted(set(harnesses.CORE_HARNESS_NAMES) | set(active))

    width = max(max(len(s) for s in diag.skill_names), 5)
    header = "SKILL".ljust(width) + "  " + "  ".join(n[:14].ljust(14) for n in names)
    print(header)
    print("-" * len(header))
    for skill in diag.skill_names:
        cells = [diag.reports[n].cell_state(skill).ljust(14) for n in names]
        print(skill.ljust(width) + "  " + "  ".join(cells))

    print()
    if diag.findings:
        print("findings:")
        for f in diag.findings:
            print(f"  - {f}")
    else:
        print("no findings — every skill is reachable and synchronized across checked harnesses.")

    return EXIT_PROBLEM if diag.findings else EXIT_OK


def cmd_detect(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    detected = harnesses.detect_harnesses(root, probe_versions=args.versions)
    if fmt_mode(args) == "json":
        print(
            json.dumps(
                [
                    {
                        "harness": d.harness.name,
                        "display_name": d.harness.label,
                        "category": d.harness.category,
                        "support_status": d.harness.support_status,
                        "installed": d.installed,
                        "project_active": d.project_active,
                        "user_present": d.user_present,
                        "binary": d.binary_path,
                        "version": d.version,
                        "reasons": d.reasons,
                    }
                    for d in detected
                ],
                indent=2,
            )
        )
        return EXIT_OK

    print(f"skillporter {__version__} — detected harnesses in {root}\n")
    width = max(len(d.harness.name) for d in detected)
    print(f"{'HARNESS'.ljust(width)}  {'DETECTED':8}  {'WORKSPACE':9}  {'SUPPORT':10}  EVIDENCE")
    print(f"{'-' * width}  {'-' * 8}  {'-' * 9}  {'-' * 10}  {'-' * 30}")
    for d in detected:
        if not args.all and not d.installed:
            continue
        det_str = "yes" if d.installed else "no"
        ws_str = "active" if d.project_active else "-"
        ev = ", ".join(d.reasons) if d.reasons else "-"
        if d.version:
            ev += f" ({d.version})"
        print(f"{d.harness.name.ljust(width)}  {det_str:8}  {ws_str:9}  {d.harness.support_status:10}  {ev}")
    return EXIT_OK


def _collect_unified_drift(
    diag,
    lock,
    records: Mapping[str, ManagedSkillRecord],
    root: Path,
) -> dict[str, dict[str, str]]:
    """Compute unified drift map across copy divergence, lockfile pins, and state records."""
    drift_map: dict[str, dict[str, str]] = {k: dict(v) for k, v in diag.drifted.items()}
    for sname, copies in sorted(diag.skill_copies.items()):
        locked_entry = lock.skills.get(sname)
        rec = records.get(sname)
        expected_hash = ""
        expected_source_label = ""
        if locked_entry and locked_entry.tree_hash:
            expected_hash = locked_entry.tree_hash
            expected_source_label = LOCKFILE_FILENAME
        elif rec is not None and rec.tree_hash:
            expected_hash = rec.tree_hash
            expected_source_label = ".skillporter/state.json"
        if not expected_hash:
            continue
        for cdir in copies:
            chash, _ = compute_tree_hash(cdir)
            if chash and chash != expected_hash:
                rel_c = cdir.relative_to(root).as_posix() if cdir.is_relative_to(root) else str(cdir)
                entry_map = drift_map.setdefault(sname, {})
                entry_map[expected_source_label] = expected_hash
                entry_map[rel_c] = chash
    return drift_map


def _find_verified_snapshot(root: Path, scope: str, sname: str, expected_hash: str) -> Path | None:
    """Locate a clean local store or backup directory matching *expected_hash*."""
    sdir = state_dir(root, scope=scope)
    candidates: list[Path] = []
    store_cand = sdir / "store" / sname / expected_hash[:12] / sname
    if store_cand.is_dir():
        candidates.append(store_cand)
    backups_root = sdir / "backups" / sname
    if backups_root.is_dir():
        for bsub in sorted(backups_root.iterdir(), reverse=True):
            bcand = bsub / sname
            if bcand.is_dir():
                candidates.append(bcand)
    for cand in candidates:
        chash, _ = compute_tree_hash(cand)
        if chash == expected_hash:
            srep = scan_skill(cand, offline=True)
            if srep.passed and not srep.has_structural_escape:
                return cand
    return None


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    manifest = load_manifest(root) if args.scope == "project" else None
    manifest_skill_map = {s.name: s for s in manifest.skills} if (manifest and manifest.skills) else {}
    records = load_state(root, scope=args.scope)

    diag = run_diagnose(root, only=args.harness or None, scope=args.scope)
    detected = [d for d in harnesses.detect_harnesses(root) if d.installed]
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        lock = load_lockfile(root)
    except LockfileError as exc:
        lock = load_lockfile(root / ".nonexistent")
        diag.findings.append(f"lockfile error: {exc}")

    if args.harness:
        default_targets = [harnesses.get(h).name for h in args.harness]
    elif manifest and manifest.harnesses:
        default_targets = [harnesses.get(h).name for h in manifest.harnesses]
    else:
        active_proj = {d.harness.name for d in detected if d.project_active}
        default_targets = sorted({"claude-code", "codex", "cursor"} | active_proj)

    drift_before_fix = _collect_unified_drift(diag, lock, records, root)
    repaired: list[str] = []

    has_broken = any(loc.broken_links for r in diag.reports.values() for loc in r.locations)
    if args.fix and not dry_run and (diag.skills or has_broken):
        for rep in diag.reports.values():
            for loc in rep.locations:
                for blink in loc.broken_links:
                    bp = Path(blink)
                    if bp.is_symlink():
                        bp.unlink(missing_ok=True)
                        repaired.append(f"removed broken symlink {bp}")

        for skill_md in diag.skills:
            sname = skill_md.parent.name
            copies = diag.skill_copies.get(sname, [skill_md.parent])
            locked_entry = lock.skills.get(sname)
            rec = records.get(sname)

            if args.harness:
                skill_targets = default_targets
            elif sname in manifest_skill_map and manifest_skill_map[sname].harnesses:
                skill_targets = [harnesses.get(h).name for h in manifest_skill_map[sname].harnesses]
            elif manifest and manifest.harnesses:
                skill_targets = default_targets
            elif rec and rec.harnesses:
                skill_targets = [harnesses.get(h).name for h in rec.harnesses]
            else:
                skill_targets = default_targets

            expected_hash = (
                locked_entry.tree_hash
                if (locked_entry and locked_entry.tree_hash)
                else (rec.tree_hash if rec and rec.tree_hash else "")
            )

            clean_copies: list[Path] = []
            any_security_passed_on_disk = False
            for cdir in copies:
                srep = scan_skill(cdir)
                if not srep.passed or srep.has_structural_escape:
                    continue
                any_security_passed_on_disk = True
                if expected_hash:
                    chash, _ = compute_tree_hash(cdir)
                    if chash != expected_hash:
                        continue
                clean_copies.append(cdir)

            # Restore single-copy benign drift from verified baseline snapshot,
            # while refusing to auto-mask if ALL on-disk copies failed security scan.
            if not clean_copies and expected_hash and any_security_passed_on_disk:
                snap_dir = _find_verified_snapshot(root, args.scope, sname, expected_hash)
                if snap_dir is not None:
                    clean_copies.append(snap_dir)

            if not clean_copies:
                continue

            needs_repair = (
                sname in drift_before_fix
                or any(t in diag.reports and not diag.reports[t].loads(sname) for t in skill_targets)
            )
            if not needs_repair:
                continue

            best_dir = max(clean_copies, key=latest_tree_mtime_ns)
            with contextlib.suppress(InstallError):
                res = run_install(
                    root,
                    best_dir,
                    skill_targets,
                    strategy="copy",
                    scope=args.scope,
                    force=True,
                    record_state=True,
                    skill_name_override=sname,
                )
                for r in res:
                    if r.action in ("created", "updated"):
                        verified_h, _ = compute_tree_hash(r.dest)
                        rel_dest = r.dest.relative_to(root) if r.dest.is_relative_to(root) else r.dest
                        repaired.append(f"{sname} -> {r.harness} ({rel_dest}, sha256:{verified_h[:12]})")

        records = load_state(root, scope=args.scope)
        diag = run_diagnose(root, only=args.harness or default_targets, scope=args.scope)

    remaining_drift = _collect_unified_drift(diag, lock, records, root)

    for sname, copies in sorted(diag.skill_copies.items()):
        locked_entry = lock.skills.get(sname)
        rec = records.get(sname)
        for cdir in copies:
            rel_c = cdir.relative_to(root).as_posix() if cdir.is_relative_to(root) else str(cdir)
            srep = scan_skill(cdir)
            if not srep.passed or srep.has_structural_escape:
                codes = ", ".join(sorted({f.code for f in srep.findings if f.severity in ("CRITICAL", "HIGH")}))
                msg = f"security: {sname!r} at {rel_c} blocked by static scan ({codes})"
                if msg not in diag.findings:
                    diag.findings.append(msg)
            if locked_entry and locked_entry.tree_hash:
                chash, _ = compute_tree_hash(cdir)
                if chash != locked_entry.tree_hash:
                    lmsg = (
                        f"lockfile drift: {sname!r} at {rel_c} ({chash[:8]}) "
                        f"differs from skillporter.lock ({locked_entry.tree_hash[:8]})"
                    )
                    if lmsg not in diag.findings:
                        diag.findings.append(lmsg)
            elif rec and rec.tree_hash:
                chash, _ = compute_tree_hash(cdir)
                if chash != rec.tree_hash:
                    smsg = (
                        f"state drift: {sname!r} at {rel_c} ({chash[:8]}) "
                        f"differs from installed state ({rec.tree_hash[:8]})"
                    )
                    if smsg not in diag.findings:
                        diag.findings.append(smsg)

    active_names = default_targets

    skill_summaries = []
    for skill_md in diag.skills:
        sname = skill_md.parent.name
        valid = diag.is_skill_valid(sname)
        is_drifted_now = sname in remaining_drift
        thash, _ = compute_tree_hash(skill_md.parent)
        per_harness = {}
        reachable_in_checked = []
        for hname in active_names:
            if hname in diag.reports:
                st_list = diag.reports[hname].explicit_states(sname, is_valid=valid)
                if is_drifted_now and "HASH_VERIFIED" in st_list:
                    st_list = ["DRIFT" if x == "HASH_VERIFIED" else x for x in st_list]
                per_harness[hname] = st_list
                if diag.reports[hname].loads(sname):
                    reachable_in_checked.append(hname)
        summary_state = "DRIFTED" if is_drifted_now else ("VALID" if valid else "INVALID")
        skill_summaries.append(
            {
                "name": sname,
                "path": str(skill_md.parent),
                "state": summary_state,
                "tree_hash": thash[:12] if thash else "",
                "copies": len(diag.skill_copies.get(sname, [])),
                "reachable_harnesses": reachable_in_checked,
                "harnesses": per_harness,
            }
        )

    remediations: list[str] = []
    if any("security:" in f for f in diag.findings):
        remediations.append("skillporter scan .         # inspect and remediate security findings")
    if any("lockfile drift:" in f or "state drift:" in f for f in diag.findings):
        remediations.append(
            "skillporter doctor --fix   # restore verified snapshot (or `skillporter lock` if intentional)"
        )
    if remaining_drift:
        remediations.append("skillporter sync --force   # reconcile drifted copies (snapshots backup first)")
    if any("not visible to:" in f or "broken symlink" in f for f in diag.findings):
        remediations.append("skillporter doctor --fix   # install missing skills and remove broken symlinks")
    if any(not diag.is_skill_valid(s) for s in diag.skill_names):
        remediations.append("skillporter validate .     # inspect and fix SKILL.md specification errors")

    if fmt_mode(args) == "json":
        print(
            json.dumps(
                {
                    "root": str(root),
                    "dry_run": dry_run,
                    "detected_harnesses": [d.harness.name for d in detected],
                    "checked_harnesses": active_names,
                    "skills": diag.skill_names,
                    "skill_states": skill_summaries,
                    "drift_before_fix": drift_before_fix,
                    "repaired": repaired,
                    "drifted": remaining_drift,
                    "duplicates": diag.duplicates,
                    "findings": diag.findings,
                    "remediations": remediations,
                    "healthy": len(diag.findings) == 0,
                },
                indent=2,
            )
        )
        return EXIT_PROBLEM if diag.findings else EXIT_OK

    print(f"skillporter {__version__} — doctor report for {root}\n")
    print(f"Detected harnesses: {', '.join(d.harness.name for d in detected) or '(none)'}")
    print(f"Checked harnesses:  {', '.join(active_names)}")
    print(f"Discovered skills:  {len(diag.skill_names)}")
    if args.fix and not dry_run:
        print(
            f"Content drift:      {len(remaining_drift)} remaining "
            f"(found before repair: {len(drift_before_fix)}, repaired: {len(repaired)})"
        )
    else:
        print(f"Content drift:      {len(remaining_drift)} skill(s)")

    if repaired:
        print("\nRepairs applied:")
        for item in repaired:
            print(f"  ~ {item}")

    if skill_summaries:
        print()
        if is_verbose(args):
            print("Skill Status Matrix (on-disk integrity + adapter verification tier):")
            for s in skill_summaries:
                integrity_tag = "DRIFTED" if s["state"] == "DRIFTED" else "HASH_VERIFIED"
                print(
                    f"  {s['name']} [{s['state']} · {integrity_tag}] "
                    f"(hash: {s['tree_hash']}, copies: {s['copies']})"
                )
                for hname, st_list in s["harnesses"].items():
                    tier = harnesses.get(hname).verification_level
                    display_chain = [
                        f"ADAPTER:{tier}" if tok in ("VERIFIED", "UNVERIFIED") else tok
                        for tok in st_list
                    ]
                    print(f"    - {hname:16} {' -> '.join(display_chain)}")
        else:
            trows = []
            for s in skill_summaries:
                rh = s["reachable_harnesses"]
                h_cell = (
                    ", ".join(rh[:4]) + f" (+{len(rh) - 4})"
                    if len(rh) > 4
                    else (", ".join(rh) if rh else "(none)")
                )
                trows.append([str(s["name"]), str(s["state"]), str(s["tree_hash"]), str(s["copies"]), h_cell])
            print(
                render_table(
                    ["SKILL", "STATE", "SHA-256", "COPIES", "REACHABLE HARNESSES"],
                    trows,
                    max_rows=25,
                    indent="  ",
                    more_hint="pass --verbose for full list and per-harness verification states",
                )
            )

    if diag.findings:
        print("\nIssues found:")
        for f in diag.findings:
            print(f"  - {f}")
        if remediations and (not args.fix or dry_run):
            print("\nRecommended fixes:")
            for cmd in remediations:
                print(f"  $ {cmd}")
        print(f"\nStatus: {badge('UNHEALTHY')} ({len(diag.findings)} issue(s) found).")
        return EXIT_PROBLEM
    print(f"\nStatus: {badge('HEALTHY')} (all checked skills reachable, valid, and hash-verified).")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    manifest = load_manifest(root)
    lock_drift: list[str] = []
    try:
        lock = load_lockfile(root, warn_migration=False)
    except LockfileError as exc:
        lock = load_lockfile(root / ".nonexistent")
        lock_drift.append(str(exc))
    records = load_state(root, scope=args.scope)
    diag = run_diagnose(root, scope=args.scope)
    detected = [d for d in harnesses.detect_harnesses(root) if d.installed]

    for sname, locked in sorted(lock.skills.items()):
        copies = diag.skill_copies.get(sname, [])
        if not copies:
            lock_drift.append(f"{sname}: locked at {locked.tree_hash[:12]} but missing on disk")
            continue
        for cdir in copies:
            actual_hash, _ = compute_tree_hash(cdir)
            if locked.tree_hash and actual_hash != locked.tree_hash:
                lock_drift.append(
                    f"{sname} ({cdir.relative_to(root) if cdir.is_relative_to(root) else cdir}): "
                    f"locked {locked.tree_hash[:12]} != disk {actual_hash[:12]}"
                )

    active_harnesses = sorted(
        set(harnesses.CORE_HARNESS_NAMES)
        | {d.harness.name for d in detected if d.project_active}
        | (set(manifest.harnesses) if manifest and manifest.harnesses else set())
    )
    all_skill_names = sorted(set(diag.skill_names) | set(lock.skills))
    per_harness: dict[str, dict[str, str]] = {}
    for hname in active_harnesses:
        rep = diag.reports.get(hname)
        if not rep:
            continue
        per_harness[hname] = {}
        for sname in all_skill_names:
            installed_here = rep.loads(sname)
            locked_entry = lock.skills.get(sname)
            if not installed_here:
                per_harness[hname][sname] = "MISSING_LOCKED" if locked_entry else "MISSING"
            elif sname in diag.drifted or any(ld.startswith(f"{sname} ") for ld in lock_drift):
                per_harness[hname][sname] = "INSTALLED_DRIFTED"
            elif locked_entry:
                per_harness[hname][sname] = "INSTALLED_LOCKED"
            else:
                per_harness[hname][sname] = "INSTALLED_UNLOCKED"

    healthy = len(diag.findings) == 0 and len(lock_drift) == 0
    payload = {
        "root": str(root),
        "manifest_present": manifest is not None,
        "lockfile_present": (root / LOCKFILE_FILENAME).is_file(),
        "lock_drift": lock_drift,
        "detected_harnesses": [d.harness.name for d in detected],
        "managed_skills": sorted(records),
        "discovered_skills": diag.skill_names,
        "locked_skills": sorted(lock.skills),
        "per_harness": per_harness,
        "drifted_skills": sorted(diag.drifted),
        "findings": diag.findings,
        "healthy": healthy,
    }
    if fmt_mode(args) == "json":
        print(json.dumps(payload, indent=2))
        return EXIT_OK if healthy else EXIT_PROBLEM

    print(f"skillporter {__version__} — workspace status for {root}\n")
    print(f"Manifest ({MANIFEST_FILENAME}): {'present' if manifest else 'not initialized'}")
    print(f"Lockfile ({LOCKFILE_FILENAME}): {'present' if (root / LOCKFILE_FILENAME).is_file() else 'not generated'}")
    print(f"Detected harnesses: {', '.join(d.harness.name for d in detected) or '(none)'}")
    print(f"Skills discovered:  {len(diag.skill_names)} ({len(records)} managed, {len(lock.skills)} locked)")
    print(f"Copy drift:         {len(diag.drifted)} skill(s)")
    print(f"Lockfile drift:     {len(lock_drift)} entry(ies)")
    if per_harness and all_skill_names:
        print("\nPer-Harness Installed vs. Locked State:")
        for hname, smap in sorted(per_harness.items()):
            summary_str = ", ".join(f"{s}={st}" for s, st in sorted(smap.items()))
            print(f"  {hname:16} {summary_str}")
    if lock_drift:
        for ld in lock_drift:
            print(f"  - {ld}")
    if diag.findings:
        print("\nFindings:")
        for f in diag.findings:
            print(f"  - {f}")
    print(f"\nStatus: {badge('HEALTHY' if healthy else 'NEEDS ATTENTION')}")
    return EXIT_OK if healthy else EXIT_PROBLEM


def cmd_demo(args: argparse.Namespace) -> int:
    result = run_demo()
    if fmt_mode(args) == "json":
        print(json.dumps(result, indent=2))
        return EXIT_OK

    print(f"skillporter {__version__} — interactive multi-harness demo (isolated temp workspace)\n")
    print("1. BEFORE (Diagnosing fragmented workspace with broken worktree symlink & SHA-256 drift):")
    before = result["before"]  # type: ignore[index]
    for f in before["findings"]:  # type: ignore[index]
        print(f"   - {f}")
    print("\n2. EXECUTING: skillporter doctor --fix && skillporter sync --force && skillporter lock")
    print("\n3. BEFORE vs. AFTER DIFF:")
    for dline in result["diff"]:  # type: ignore[index]
        print(f"   {dline}")
    print("\n4. AFTER (All harnesses reachable, 0 drift, 0 broken symlinks, skillporter.lock pinned):")
    after = result["after"]  # type: ignore[index]
    for sname, hmap in after["matrix"].items():  # type: ignore[union-attr]
        cells_str = ", ".join(f"{h}={st}" for h, st in hmap.items())
        print(f"   {sname:16} {cells_str}")
    print("\nTemporary workspace cleaned up (0 files written to your current directory).")
    return EXIT_OK


def cmd_ci_report(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    exit_code, md, payload = generate_ci_report(root, scope=args.scope)
    if getattr(args, "output", None):
        out_p = Path(args.output).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")

    if getattr(args, "github_repo", None) and getattr(args, "pr", None):
        try:
            post_github_pr_comment(args.github_repo, int(args.pr), md)
        except Exception as exc:
            print(f"warning: failed to post GitHub PR comment: {exc}", file=sys.stderr)

    if fmt_mode(args) == "json":
        print(json.dumps(payload, indent=2))
    else:
        print(md, end="")
    return exit_code
