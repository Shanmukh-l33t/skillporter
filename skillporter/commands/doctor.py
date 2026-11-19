"""Diagnose, doctor, detect, matrix, status, demo, and ci-report commands."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from .. import __version__, harnesses
from ..ci_report import generate_ci_report, post_github_pr_comment
from ..demo import run_demo
from ..diagnose import diagnose as run_diagnose
from ..install import InstallError
from ..install import install as run_install
from ..manifest import LOCKFILE_FILENAME, MANIFEST_FILENAME, LockfileError, load_lockfile, load_manifest
from ..policy import load_policy, split_by_allowed_harnesses
from ..security import compute_tree_hash, scan_skill
from ..state import ManagedSkillRecord, load_state, state_dir
from ..ui import badge, render_table
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode, get_harness, is_verbose

STALE_TMP_AGE_SECONDS = 600


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


def _check_evidence(scope: str, hermes_checked: bool) -> dict[str, str]:
    evidence = {"evidence_scope": "filesystem", "runtime_discovery": "not_checked"}
    if scope == "project" and hermes_checked:
        evidence["runtime_note"] = "Hermes project skill discovery requires project trust; trust was not checked."
    return evidence


def _print_check_evidence(evidence: Mapping[str, str]) -> None:
    print("Filesystem checks only; runtime discovery was not checked.")
    if "runtime_note" in evidence:
        print(evidence["runtime_note"])


def cmd_diagnose(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"error: {root} does not exist (verify the directory path)", file=sys.stderr)
        return EXIT_ERROR

    selected = args.harness or None
    if selected and "all" in selected:
        selected = harnesses.names()
    try:
        for hn in selected or []:
            get_harness(hn)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    diag = run_diagnose(root, only=selected, scope=args.scope)
    fmt = fmt_mode(args)
    hermes = diag.reports.get("hermes")
    evidence = _check_evidence(
        args.scope, hermes is not None and (bool(selected) or any(loc.exists for loc in hermes.locations))
    )

    if fmt == "json":
        payload = {
            "root": str(diag.root),
            "scope": args.scope,
            **evidence,
            "skills": diag.skill_names,
            "drifted": diag.drifted,
            "duplicates": diag.duplicates,
            "harnesses": {
                name: {
                    "verified": r.verified,
                    "support_status": r.support_status,
                    "verification_level": r.verification_level,
                    "on_disk_skills": sorted(r.reachable_skills),
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

    verbose = is_verbose(args)
    print(f"skillporter {__version__} — diagnose ({args.scope}): {diag.root}")
    _print_check_evidence(evidence)
    if not diag.skills:
        print("No SKILL.md files found in this scope.")
    if diag.skills or diag.findings:
        findings_label = f"{len(diag.findings)} finding(s)" if diag.findings else "no findings"
        print(f"{len(diag.skills)} skill(s) found · {findings_label}")

    if verbose and diag.skills:
        active = {
            name for name, rep in diag.reports.items()
            if rep.reachable_skills or any(loc.exists for loc in rep.locations)
        }
        names = list(diag.reports) if selected else sorted(set(harnesses.CORE_HARNESS_NAMES) | active)
        rows = [[skill, *(diag.reports[n].cell_state(skill) for n in names)] for skill in diag.skill_names]
        print("\n" + render_table(["SKILL", *names], rows))

    findings = diag.findings if verbose else diag.findings[:5]
    for finding in findings:
        print(f"  - {finding}")
    if len(findings) < len(diag.findings):
        print(f"  ... and {len(diag.findings) - len(findings)} more finding(s)")
    if not verbose and (diag.skills or diag.findings):
        print("Pass --verbose for the reachability table and all findings; use --harness <id> to focus the check.")
    return EXIT_PROBLEM if diag.findings or not diag.skills else EXIT_OK


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
            chash, _ = diag.tree_hash(cdir)
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
    from ..atomic import workspace_lock
    from ..diagnose import Diagnosis
    from ..install import (
        _verify_harness_base_within_scope,
        _verify_no_escaping_symlinks,
        plan_install,
        validate_skill_name_segment,
    )
    from ..manifest import Lockfile
    from ..policy import POLICY_FILENAME, PolicyError, evaluate_policy

    root = Path(args.path).expanduser().resolve()
    scope = args.scope
    dry_run = bool(getattr(args, "dry_run", False))
    manifest = load_manifest(root) if scope == "project" else None
    sdir = state_dir(root, scope=scope)
    repair_plan: list[dict[str, str]] = []

    def step(action: str, path: Path, impact: str, **details: str) -> None:
        repair_plan.append({"action": action, "path": str(path), "impact": impact, **details})

    try:
        # Validate every harness name up front so a typo is a clean error, not a traceback.
        if args.harness:
            for hn in args.harness:
                get_harness(hn)
        if manifest:
            for hn in [*manifest.harnesses, *(h for s in manifest.skills for h in (s.harnesses or []))]:
                get_harness(hn)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    manifest_skill_map = {s.name: s for s in manifest.skills} if (manifest and manifest.skills) else {}
    records = load_state(root, scope=scope)
    blocked = []
    if args.fix or dry_run:
        for base in dict.fromkeys((sdir, state_dir(root))):
            if base.resolve() != base.parent.resolve() / base.name:
                blocked.append((base, "state directory redirects through a link"))
        # diagnose() can recover transactions as a side effect. Don't do that inside a repair preview.
        txn_dir = sdir / "tmp"
        if any(p.is_dir() and not p.is_symlink() for p in txn_dir.glob("txn-*")):
            blocked.append((txn_dir, "pending install transaction; run plain `skillporter doctor` to recover first"))
    try:
        lock = load_lockfile(root)
    except LockfileError as exc:
        lock = Lockfile()
        blocked.append((root / LOCKFILE_FILENAME, f"lockfile error: {exc}"))
    if args.fix and not blocked:
        try:
            policy = load_policy(root)
        except PolicyError as exc:
            blocked.append((root / POLICY_FILENAME, f"policy error: {exc}"))
    if blocked and (args.fix or dry_run):
        diag = Diagnosis(root=root)
    else:
        # A preview must not mutate: crash recovery takes the workspace lock and clears .skillporter/tmp.
        diag = run_diagnose(root, only=args.harness or None, scope=scope, recover=not dry_run)
    detected = [d for d in harnesses.detect_harnesses(root) if d.installed]
    for path, reason in blocked:
        diag.findings.append(f"{path}: {reason}")
        if args.fix:
            step("refuse", path, reason)
    lock.skills = {name: entry for name, entry in lock.skills.items() if entry.scope == scope}

    if args.harness:
        default_targets = [get_harness(h).name for h in args.harness]
    elif manifest and manifest.harnesses:
        default_targets = [get_harness(h).name for h in manifest.harnesses]
    else:
        # Same source of truth as diagnose(): the harness set it judged the skills against.
        default_targets = sorted(diag.default_harnesses)

    drift_before_fix = _collect_unified_drift(diag, lock, records, root)
    repaired: list[str] = []
    stale_tmp_removed = 0
    if args.fix and not blocked:
        cutoff = time.time() - STALE_TMP_AGE_SECONDS

        def is_stale(path: Path) -> bool:
            return not path.is_symlink() and path.is_file() and path.stat().st_mtime <= cutoff

        stale_paths = []
        for path in sorted(sdir.glob(".state.json.*.tmp")):
            with contextlib.suppress(OSError):
                if is_stale(path):
                    stale_paths.append(path)
                    step("remove-stale-temp", path, "abandoned write from a killed process; state.json is untouched")

        manifest_targets = []
        if manifest and manifest.harnesses:
            # The manifest parser supplies core defaults even when no harnesses were declared.
            raw_manifest = (root / MANIFEST_FILENAME).read_text(encoding="utf-8").lstrip()
            if raw_manifest.startswith("{"):
                declared = bool(json.loads(raw_manifest).get("harnesses"))
            else:
                declared = any(
                    line.partition(":")[0].rstrip() == "harnesses" and line.partition(":")[2].strip() != "[]"
                    for line in (line.split("#", 1)[0] for line in raw_manifest.splitlines())
                )
            if declared:
                manifest_targets = manifest.harnesses

        installs: list[tuple[str, Path, str, list[str], dict[Path, bool]]] = []
        replacement_paths: set[Path] = set()
        dangling_roots: set[Path] = set()
        for sname in sorted(set(diag.skill_copies) | set(records) | set(lock.skills)):
            copies = diag.skill_copies.get(sname, [])
            try:
                validate_skill_name_segment(sname)
            except InstallError as exc:
                step("refuse", copies[0] if copies else sdir, str(exc), skill=sname)
                continue
            locked_entry = lock.skills.get(sname)
            rec = records.get(sname)
            spec = manifest_skill_map.get(sname)
            raw_targets = (args.harness or (spec and spec.harnesses) or (rec and rec.harnesses)
                           or (locked_entry and locked_entry.installed_targets) or manifest_targets)
            targets = []
            for name in raw_targets:
                with contextlib.suppress(KeyError):
                    targets.append(get_harness(name).name)
            targets = list(dict.fromkeys(targets))
            missing = {t for t in targets if t in diag.reports and not diag.reports[t].loads(sname)}
            drifted = sname in drift_before_fix
            if not drifted and not missing and (targets or not copies or scope == "user"):
                continue
            expected_hash = (
                locked_entry.tree_hash
                if (locked_entry and locked_entry.tree_hash)
                else (rec.tree_hash if rec and rec.tree_hash else "")
            )
            if drifted and not expected_hash:
                for path in copies:
                    step("refuse", path, "conflicting copies; choose the authoritative copy explicitly")
                continue
            if not targets:
                for path in copies:
                    if drifted or any(t in diag.reports and not diag.reports[t].loads(sname) for t in default_targets):
                        step("refuse", path, "no explicit repair targets; use --harness or configure the manifest")
                continue

            clean = {}
            for path in sorted(copies):
                try:
                    _verify_harness_base_within_scope(path, scope, root)
                    _verify_no_escaping_symlinks(path)
                except (InstallError, OSError, RuntimeError):
                    continue
                report = scan_skill(path, offline=True)
                if report.passed and report.scan_complete and not report.has_structural_escape:
                    clean[path] = compute_tree_hash(path)[0]
            source = next((p for p, h in clean.items() if h and (not expected_hash or h == expected_hash)), None)
            if source is None and expected_hash and (clean or not copies):
                source = _find_verified_snapshot(root, scope, sname, expected_hash)
            source_error = ""
            if source is None:
                source_error = (
                    "no safe local source matching the lock/state pin" if expected_hash else "no safe local source"
                )
            else:
                try:
                    _verify_harness_base_within_scope(source, scope, root)
                    _verify_no_escaping_symlinks(source)
                    report = scan_skill(source, offline=True)
                    violations = evaluate_policy(
                        policy, skill_dirs=[source], require_source=True,
                        source_candidates=[
                            (locked_entry and locked_entry.source) or (rec and rec.source)
                            or (spec and spec.source) or "",
                        ],
                        resolved_commit=(locked_entry and locked_entry.resolved_commit)
                        or (rec and rec.resolved_commit) or "",
                        ref=spec.ref if spec else "", sec_reports={source.name: report},
                    )
                    if not report.passed or not report.scan_complete or report.has_structural_escape:
                        violations.append("source failed the static security scan")
                    if manifest and report.fails_policy(manifest.security_policy, manifest.max_risk_score):
                        violations.append("source failed manifest security thresholds")
                    source_error = "; ".join(violations)
                except (InstallError, OSError, RuntimeError) as exc:
                    source_error = str(exc)

            # A placeholder supplies the name for destination resolution even when no source is safe.
            plan_source = source or (root / sname)
            try:
                destinations = plan_install(root, [plan_source], targets, scope=scope, allow_managed_update=True)
            except (InstallError, OSError, RuntimeError) as exc:
                step("refuse", copies[0] if copies else sdir, str(exc), skill=sname)
                continue
            source_hash = compute_tree_hash(source)[0] if source else ""
            repair_targets = []
            writes = {}
            planned_harnesses = set()
            for dest in destinations.destinations:
                path = dest.resolved_dest
                target_names = [dest.harness, *dest.shared_with]
                planned_harnesses.update(target_names)
                if path.is_dir() and source_hash and compute_tree_hash(path)[0] == source_hash:
                    continue
                if not missing.intersection(target_names) and (not drifted or not dest.exists):
                    continue
                _, denied = split_by_allowed_harnesses(policy, target_names)
                reason = source_error
                if denied:
                    reason = f"policy allowed_harnesses excludes {', '.join(denied)}"
                elif dest.conflict or (dest.exists and not (path.is_dir() or path.is_symlink())):
                    reason = "existing unmanaged copy or non-directory would be overwritten"
                elif ".git" in path.parts or path == root or (source and source.resolve().is_relative_to(path)):
                    reason = "destination overlaps protected files or the repair source"
                details = {"skill": sname, "harnesses": ", ".join(target_names)}
                if source:
                    details["source"] = str(source)
                if reason:
                    step("refuse", path, reason, **details)
                    continue
                impact = f"copy sha256:{source_hash[:12]}; update {sdir / 'state.json'}"
                if dest.exists:
                    if path.is_symlink():
                        impact += "; replace the link itself, leaving its target untouched"
                    else:
                        impact += f"; back up current content under {sdir / 'backups' / sname}"
                    replacement_paths.add(path)
                step("replace" if dest.exists else "create", path, impact, **details)
                writes[path] = dest.exists
                repair_targets.extend(target_names)
            for name in sorted(missing - planned_harnesses):
                step("refuse", copies[0] if copies else sdir, f"{name} has no {scope} install path", skill=sname)
            if writes and source is not None:
                installs.append((sname, source, source_hash, list(dict.fromkeys(repair_targets)), writes))

        harness_roots = {loc.resolved for r in diag.reports.values() for loc in r.locations}
        broken_links = {Path(p) for r in diag.reports.values() for loc in r.locations for p in loc.broken_links}
        for path in sorted(broken_links - replacement_paths):
            if any(item["path"] == str(path) for item in repair_plan):
                continue
            if path in harness_roots:
                # A dangling harness root is the install path itself: removing the link is what lets a
                # later install recreate the directory. Links nested inside a working directory are not ours.
                step("remove", path, "dangling harness root; the directory it points to is gone")
                dangling_roots.add(path)
            else:
                step("refuse", path, "broken link left in place; no authorized replacement was planned")

        failures = []
        if not dry_run and (stale_paths or installs or dangling_roots):
            for path in sorted(dangling_roots):
                with contextlib.suppress(OSError):
                    path.unlink()
            with workspace_lock(root):
                for path in stale_paths:
                    try:
                        if is_stale(path):
                            path.unlink()
                            stale_tmp_removed += 1
                    except OSError as exc:
                        failures.append(f"repair failed at {path}: {exc}")
                for sname, source, source_hash, targets, writes in installs:
                    try:
                        live = plan_install(root, [source], targets, scope=scope, allow_managed_update=True)
                        if (
                            any(d.conflict for d in live.destinations if d.resolved_dest in writes)
                            or {d.resolved_dest: d.exists for d in live.destinations if d.resolved_dest in writes}
                            != writes
                            or compute_tree_hash(source)[0] != source_hash
                        ):
                            raise InstallError("source or destination changed since planning; rerun doctor")
                        res = run_install(
                            root, source, targets, scope=scope, force=any(writes.values()), record_state=True
                        )
                        for r in res:
                            if r.action in ("created", "updated"):
                                verified_h, _ = compute_tree_hash(r.dest)
                                rel_dest = r.dest.relative_to(root) if r.dest.is_relative_to(root) else r.dest
                                repaired.append(f"{sname} -> {r.harness} ({rel_dest}, sha256:{verified_h[:12]})")
                    except (InstallError, OSError) as exc:
                        failures.append(f"repair failed at {', '.join(map(str, writes))}: {exc}")
            records = load_state(root, scope=scope)
            diag = run_diagnose(root, only=args.harness or None, scope=scope)
            diag.findings.extend(failures)

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
                chash, _ = diag.tree_hash(cdir)
                if chash != locked_entry.tree_hash:
                    lmsg = (
                        f"lockfile drift: {sname!r} at {rel_c} ({chash[:8]}) "
                        f"differs from skillporter.lock ({locked_entry.tree_hash[:8]})"
                    )
                    if lmsg not in diag.findings:
                        diag.findings.append(lmsg)
            elif rec and rec.tree_hash:
                chash, _ = diag.tree_hash(cdir)
                if chash != rec.tree_hash:
                    smsg = (
                        f"state drift: {sname!r} at {rel_c} ({chash[:8]}) "
                        f"differs from installed state ({rec.tree_hash[:8]})"
                    )
                    if smsg not in diag.findings:
                        diag.findings.append(smsg)

    active_names = default_targets
    evidence = _check_evidence(args.scope, "hermes" in active_names)
    adapter_tiers = {name: harnesses.get(name).verification_level for name in active_names}

    skill_summaries = []
    for skill_md in diag.skills:
        sname = skill_md.parent.name
        valid = diag.is_skill_valid(sname)
        is_drifted_now = sname in remaining_drift
        thash, _ = diag.tree_hash(skill_md.parent)
        per_harness = {}
        on_disk = []
        for hname in active_names:
            if hname in diag.reports:
                report = diag.reports[hname]
                per_harness[hname] = report.explicit_states(sname, is_valid=valid)
                if report.loads(sname):
                    on_disk.append(hname)
        summary_state = "DRIFTED" if is_drifted_now else ("VALID" if valid else "INVALID")
        skill_summaries.append(
            {
                "name": sname,
                "path": str(skill_md.parent),
                "state": summary_state,
                "tree_hash": thash[:12] if thash else "",
                "copies": len(diag.skill_copies.get(sname, [])),
                "on_disk_harnesses": on_disk,
                "reachable_harnesses": on_disk,
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
        remediations.append("skillporter sync --prefer <path>   # choose the authoritative copy before reconciling")
    if any("missing from expected paths for:" in f or "broken symlink" in f for f in diag.findings):
        remediations.append("skillporter doctor --fix --dry-run   # inspect authorized repairs and blocked paths")
    if any(not diag.is_skill_valid(s) for s in diag.skill_names):
        remediations.append("skillporter validate .     # inspect and fix SKILL.md specification errors")

    if fmt_mode(args) == "json":
        print(
            json.dumps(
                {
                    "root": str(root),
                    "scope": args.scope,
                    **evidence,
                    "dry_run": dry_run,
                    "detected_harnesses": [d.harness.name for d in detected],
                    "checked_harnesses": active_names,
                    "adapter_verification_levels": adapter_tiers,
                    "skills": diag.skill_names,
                    "skill_states": skill_summaries,
                    "drift_before_fix": drift_before_fix,
                    **({"repair_plan": repair_plan} if args.fix else {}),
                    "repaired": repaired,
                    "stale_tmp_removed": stale_tmp_removed,
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

    print(f"skillporter {__version__} — doctor report for {root}")
    _print_check_evidence(evidence)
    print()
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
    if args.fix:
        print("\nRepair preview (nothing written):" if dry_run else "\nRepair plan:")
        labels = {"create": "create", "replace": "replace", "remove-stale-temp": "delete"}
        for item in repair_plan:
            action = item["action"]
            source = f" from {item['source']}" if "source" in item else ""
            targets = f" [{item['harnesses']}]" if "harnesses" in item else ""
            if action == "refuse":
                print(f"  ! refused {item['path']}: {item['impact']}")
            else:
                prefix = "Would" if dry_run else "Planned"
                print(f"  - {prefix} {labels.get(action, action)} {item['path']}{source}{targets}: {item['impact']}")
        if not repair_plan:
            print("  No changes planned.")
    if stale_tmp_removed:
        print(f"\nCleanup: removed {stale_tmp_removed} stale temp file(s) from {state_dir(root, scope=args.scope)}")

    if skill_summaries:
        print()
        if is_verbose(args):
            print("Skill Status Matrix (on-disk states; historical adapter tier shown separately):")
            for s in skill_summaries:
                print(
                    f"  {s['name']} [{s['state']}] "
                    f"(hash: {s['tree_hash']}, copies: {s['copies']})"
                )
                for hname, st_list in s["harnesses"].items():
                    print(f"    - {hname:16} {' -> '.join(st_list)} (adapter: {adapter_tiers[hname]})")
        else:
            trows = []
            for s in skill_summaries:
                rh = s["on_disk_harnesses"]
                h_cell = (
                    ", ".join(rh[:4]) + f" (+{len(rh) - 4})"
                    if len(rh) > 4
                    else (", ".join(rh) if rh else "(none)")
                )
                trows.append([str(s["name"]), str(s["state"]), str(s["tree_hash"]), str(s["copies"]), h_cell])
            print(
                render_table(
                    ["SKILL", "STATE", "SHA-256", "COPIES", "HARNESSES (ON DISK)"],
                    trows,
                    max_rows=25,
                    indent="  ",
                    more_hint="pass --verbose for full list and per-harness states",
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
    print(f"\nStatus: {badge('HEALTHY')} (no issues found by filesystem checks).")
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
