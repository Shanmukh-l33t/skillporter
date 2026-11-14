"""Add, install, and update command implementations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import harnesses
from ..audit import record_audit_event
from ..frontmatter import parse_skill, validate
from ..install import InstallError, install_many, plan_install
from ..install import install as run_install
from ..manifest import ManifestSkillSpec, load_manifest, save_manifest
from ..security import scan_skill
from ..sources import SourceError, resolve_source
from ..state import load_state
from ..ui import BOLD, CYAN, action_symbol, badge, render_next_steps, style
from .common import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PROBLEM,
    fmt_mode,
    is_quiet,
    is_verbose,
    parse_custom_path_args,
    resolve_target_harnesses,
    shared_path_exclusion_notes,
)


def cmd_add(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    on_conflict = getattr(args, "on_conflict", "fail") or "fail"
    isolated = bool(getattr(args, "isolated", False))
    try:
        custom_paths = parse_custom_path_args(getattr(args, "custom_path", None))
        targets = resolve_target_harnesses(
            args.harness,
            root,
            scope=args.scope,
            default_detected=True,
            exclude_harnesses=getattr(args, "exclude_harness", None),
        )
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        resolved = resolve_source(args.source, base_dir=root, ref_override=args.ref or "")
    except (SourceError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        skill_dirs = resolved.skill_dirs
        if args.skill:
            wanted = {part.strip() for raw in args.skill for part in raw.split(",") if part.strip()}
            found_names = {d.name for d in skill_dirs}
            missing_names = sorted(wanted - found_names)
            if missing_names:
                print(
                    f"error: requested skill(s) {missing_names} not found in {args.source} "
                    f"(available: {sorted(found_names)})",
                    file=sys.stderr,
                )
                return EXIT_ERROR
            skill_dirs = [d for d in skill_dirs if d.name in wanted]

        manifest = load_manifest(root)
        max_risk_score = getattr(args, "max_risk_score", None)
        if max_risk_score is None and manifest is not None:
            max_risk_score = manifest.max_risk_score

        plan = plan_install(
            root,
            skill_dirs,
            targets,
            strategy=args.strategy,
            scope=args.scope,
            force=args.force,
            on_conflict=on_conflict,
            custom_paths=custom_paths,
            isolated=isolated,
        )

        spec_errors: list[str] = []
        sec_critical = 0
        sec_high = 0
        sec_info = 0
        sec_reports = {}
        risk_threshold_exceeded: list[str] = []
        for sdir in skill_dirs:
            issues = validate(parse_skill(sdir / "SKILL.md"))
            for iss in issues:
                if iss.level == "error":
                    spec_errors.append(f"{sdir.name}: {iss}")
            srep = scan_skill(
                sdir,
                engine=getattr(args, "engine", "auto"),
                offline=getattr(args, "offline", False),
            )
            sec_reports[sdir.name] = srep
            sec_critical += srep.critical_count
            sec_high += srep.high_count
            sec_info += srep.medium_count + srep.low_count
            if srep.exceeds_risk_threshold(max_risk_score):
                risk_threshold_exceeded.append(
                    f"{sdir.name} (risk_score {srep.risk_score}/100 > max_risk_score {max_risk_score})"
                )

        is_json = fmt_mode(args) == "json"
        if is_json and args.dry_run:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "source": resolved.canonical_source,
                        "resolved_commit": resolved.resolved_commit,
                        "skills": [d.name for d in skill_dirs],
                        "harnesses": targets,
                        "shared_destinations": plan.shared_count,
                        "spec_errors": spec_errors,
                        "max_risk_score": max_risk_score,
                        "risk_threshold_exceeded": risk_threshold_exceeded,
                        "security": {k: v.to_dict() for k, v in sec_reports.items()},
                    },
                    indent=2,
                )
            )
            return EXIT_PROBLEM if (spec_errors or sec_critical or sec_high or risk_threshold_exceeded) else EXIT_OK

        if (
            not is_json
            and not is_quiet(args)
            and (is_verbose(args) or args.dry_run or sec_critical or sec_high or spec_errors)
        ):
            print(style("SKILLPORTER", BOLD, CYAN))
            print(f"\nSource: {resolved.kind}:{args.source}")
            if resolved.resolved_commit:
                print(f"Commit: {resolved.resolved_commit[:12]}")
            print("\nFound skills:")
            for sdir in skill_dirs:
                srep_i = sec_reports[sdir.name]
                print(f"  {sdir.name}  (risk: {srep_i.risk_score}/100 · {srep_i.recommendation})")
            print("\nTarget harnesses:")
            for t in targets:
                print(f"  {harnesses.get(t).label} ({t})")
            print("\nInstallation plan:")
            print(f"  {len(plan.destinations)} destination(s) across {len(targets)} harness(es)")
            if plan.shared_count:
                print(f"  {plan.shared_count} shared destination(s) deduplicated (.agents/skills)")
            val_label = "PASSED" if not spec_errors else f"FAILED ({len(spec_errors)} error(s))"
            print(f"\nValidation: {badge(val_label)}")
            for err in spec_errors:
                print(f"  - {err}")
            print("\nSecurity assessment:")
            print(f"  {sec_info} informational/medium finding(s)")
            print(f"  {sec_critical + sec_high} critical/high finding(s)")
            for sname, srep_d in sec_reports.items():
                for f in srep_d.findings:
                    loc = f"{f.file}:{f.line}" if f.line else f.file
                    print(f"  [{f.severity}] {f.code} ({sname}/{loc}): {f.message}")

        scan_audit = {
            sname: {
                "passed": r.passed,
                "risk_score": r.risk_score,
                "recommendation": r.recommendation,
                "finding_codes": [f.code for f in r.findings],
            }
            for sname, r in sec_reports.items()
        }

        if any(r.has_structural_escape for r in sec_reports.values()):
            record_audit_event(
                root,
                interface="cli",
                operation="add",
                status="blocked",
                source=resolved.canonical_source,
                resolved_commit=resolved.resolved_commit,
                harnesses=targets,
                scan_results=scan_audit,
                force=args.force,
                risk_accepted=args.allow_risky,
                detail="structural filesystem escape",
                scope=args.scope,
            )
            print(
                "\nerror: installation blocked by structural filesystem escape "
                "(escaping symlinks or path traversal cannot be overridden with --allow-risky or --force)",
                file=sys.stderr,
            )
            return EXIT_PROBLEM

        if risk_threshold_exceeded and not args.allow_risky:
            record_audit_event(
                root,
                interface="cli",
                operation="add",
                status="blocked",
                source=resolved.canonical_source,
                resolved_commit=resolved.resolved_commit,
                harnesses=targets,
                scan_results=scan_audit,
                force=args.force,
                risk_accepted=False,
                detail="exceeded max_risk_score",
                scope=args.scope,
            )
            print(
                f"\nerror: installation blocked by configured security.max_risk_score ({max_risk_score}): "
                + ", ".join(risk_threshold_exceeded),
                file=sys.stderr,
            )
            return EXIT_PROBLEM

        incomplete_skills = [sname for sname, r in sec_reports.items() if not r.scan_complete]
        if (sec_critical > 0 or sec_high > 0 or incomplete_skills) and not args.allow_risky:
            record_audit_event(
                root,
                interface="cli",
                operation="add",
                status="blocked",
                source=resolved.canonical_source,
                resolved_commit=resolved.resolved_commit,
                harnesses=targets,
                scan_results=scan_audit,
                force=args.force,
                risk_accepted=False,
                detail="incomplete scan" if incomplete_skills else "blocked by static security policy",
                scope=args.scope,
            )
            reason = (
                f"incomplete security scan on {incomplete_skills} (truncated or unreadable files)"
                if incomplete_skills
                else "static security policy"
            )
            print(
                f"\nerror: installation blocked by {reason} "
                "(--force only overrides destination conflicts; pass --allow-risky after reviewing `skillporter scan`)",
                file=sys.stderr,
            )
            return EXIT_PROBLEM

        if args.allow_risky and (sec_critical > 0 or sec_high > 0 or risk_threshold_exceeded):
            print(
                "warning: proceeding with explicit --allow-risky security override; findings recorded in audit log.",
                file=sys.stderr,
            )

        if args.dry_run:
            if not is_json and not is_quiet(args):
                print("\nDry run complete (no files modified).")
            return EXIT_OK

        try:
            all_results = install_many(
                root,
                skill_dirs,
                targets,
                strategy=args.strategy,
                scope=args.scope,
                force=args.force,
                on_conflict=on_conflict,
                source=resolved.canonical_source,
                resolved_commit=resolved.resolved_commit,
                record_state=True,
                adapt=args.adapt,
                custom_paths=custom_paths,
                isolated=isolated,
            )
        except InstallError as exc:
            print(f"error: {exc} (pass --force or --on-conflict skip)", file=sys.stderr)
            return EXIT_ERROR

        record_audit_event(
            root,
            interface="cli",
            operation="add",
            status="succeeded",
            source=resolved.canonical_source,
            resolved_commit=resolved.resolved_commit,
            destinations=[str(r.dest) for r in all_results],
            harnesses=targets,
            scan_results=scan_audit,
            overwrite=args.force,
            force=args.force,
            risk_accepted=args.allow_risky,
            scope=args.scope,
        )

        if manifest and args.scope == "project":
            existing_names = {s.name for s in manifest.skills}
            for sdir in skill_dirs:
                if sdir.name not in existing_names:
                    manifest.skills.append(
                        ManifestSkillSpec(
                            name=sdir.name,
                            source=args.source,
                            ref=resolved.resolved_commit[:12] if resolved.resolved_commit else (args.ref or ""),
                            strategy=args.strategy,
                            harnesses=targets,
                        )
                    )
            save_manifest(root, manifest)

        if is_json:
            print(
                json.dumps(
                    {
                        "source": resolved.canonical_source,
                        "resolved_commit": resolved.resolved_commit,
                        "installed": [
                            {
                                "skill": r.skill,
                                "harness": r.harness,
                                "dest": str(r.dest),
                                "action": r.action,
                                "detail": r.detail,
                            }
                            for r in all_results
                        ],
                    },
                    indent=2,
                )
            )
            return EXIT_OK

        if not is_quiet(args):
            created_cnt = sum(1 for r in all_results if r.action == "created")
            updated_cnt = sum(1 for r in all_results if r.action == "updated")
            shared_cnt = sum(1 for r in all_results if r.action == "unchanged")
            skipped_cnt = sum(1 for r in all_results if r.action == "skipped")
            s_names = ", ".join(d.name for d in skill_dirs)
            print(
                f"{action_symbol('installed')} Installed {style(s_names, BOLD)} across {len(targets)} harness(es) "
                f"(+{created_cnt} created, ~{updated_cnt} updated, ={shared_cnt} deduplicated/unchanged"
                + (f", !{skipped_cnt} skipped)" if skipped_cnt else ")")
            )
            for r in all_results:
                if r.action != "unchanged" or is_verbose(args):
                    label = harnesses.get(r.harness).label
                    print(f"  {action_symbol(r.action)} {label:20} {r.action:10} ({r.detail})")
            for note in shared_path_exclusion_notes(
                targets,
                getattr(args, "exclude_harness", None),
                root,
                scope=args.scope,
                isolated=isolated,
                custom_paths=custom_paths,
            ):
                print(f"  Note: {note}")
            print("\nInstallation verified.")
            print(
                render_next_steps(
                    [
                        "skillporter status                # inspect installed state across harnesses",
                    ]
                )
            )
        return EXIT_OK
    finally:
        resolved.cleanup()


def cmd_install(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    skill_dir = Path(args.skill).expanduser()
    if not skill_dir.is_absolute():
        skill_dir = (root / skill_dir).resolve()
    allow_risky = bool(getattr(args, "allow_risky", False))
    dry_run = bool(getattr(args, "dry_run", False))
    is_json = fmt_mode(args) == "json"
    on_conflict = getattr(args, "on_conflict", "fail") or "fail"
    isolated = bool(getattr(args, "isolated", False))
    manifest = load_manifest(root)
    max_risk_score = manifest.max_risk_score if manifest is not None else None

    try:
        custom_paths = parse_custom_path_args(getattr(args, "custom_path", None))
        targets = resolve_target_harnesses(
            args.harness,
            root,
            scope=args.scope,
            default_detected=False,
            exclude_harnesses=getattr(args, "exclude_harness", None),
        )
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if (skill_dir / "SKILL.md").is_file():
        srep = scan_skill(skill_dir)
        scan_audit = {
            skill_dir.name: {
                "passed": srep.passed,
                "risk_score": srep.risk_score,
                "recommendation": srep.recommendation,
                "finding_codes": [f.code for f in srep.findings],
            }
        }
        if srep.has_structural_escape:
            record_audit_event(
                root,
                interface="cli",
                operation="install",
                status="blocked",
                source=str(skill_dir),
                harnesses=targets,
                scan_results=scan_audit,
                force=args.force,
                risk_accepted=allow_risky,
                detail="structural filesystem escape",
                scope=args.scope,
            )
            print(
                "error: installation blocked by structural filesystem escape "
                "(cannot be overridden with --allow-risky or --force)",
                file=sys.stderr,
            )
            return EXIT_PROBLEM
        exceeds = srep.exceeds_risk_threshold(max_risk_score)
        if (not srep.passed or not srep.scan_complete or exceeds) and not allow_risky:
            for f in srep.findings:
                loc = f"{f.file}:{f.line}" if f.line else f.file
                print(f"  [{f.severity}] {f.code} ({loc}): {f.message}", file=sys.stderr)
            record_audit_event(
                root,
                interface="cli",
                operation="install",
                status="blocked",
                source=str(skill_dir),
                harnesses=targets,
                scan_results=scan_audit,
                force=args.force,
                risk_accepted=False,
                detail=f"blocked by security policy (risk {srep.risk_score}/100)",
                scope=args.scope,
            )
            print(
                f"error: installation of {skill_dir.name!r} blocked by static security policy "
                "(--force only overrides destination conflicts; pass --allow-risky to accept risk)",
                file=sys.stderr,
            )
            return EXIT_PROBLEM
        if allow_risky and (not srep.passed or exceeds):
            for f in srep.findings:
                loc = f"{f.file}:{f.line}" if f.line else f.file
                print(f"  [{f.severity}] {f.code} ({loc}): {f.message}", file=sys.stderr)
            print("warning: proceeding with explicit --allow-risky security override.", file=sys.stderr)
    else:
        scan_audit = {}

    if dry_run:
        plan = plan_install(
            root,
            [skill_dir],
            targets,
            strategy=args.strategy,
            scope=args.scope,
            force=args.force,
            on_conflict=on_conflict,
            custom_paths=custom_paths,
            isolated=isolated,
        )
        payload = {
            "dry_run": True,
            "skill": skill_dir.name,
            "harnesses": targets,
            "destinations": [str(d.resolved_dest) for d in plan.destinations],
            "conflicts": plan.conflicts,
        }
        if is_json:
            print(json.dumps(payload, indent=2))
        elif not is_quiet(args):
            print(f"dry-run: would install {skill_dir.name} to {len(plan.destinations)} destination(s)")
        return EXIT_PROBLEM if plan.conflicts else EXIT_OK

    try:
        results = run_install(
            root,
            skill_dir,
            targets,
            strategy=args.strategy,
            scope=args.scope,
            force=args.force,
            on_conflict=on_conflict,
            record_state=True,
            adapt=getattr(args, "adapt", False),
            custom_paths=custom_paths,
            isolated=isolated,
        )
    except (InstallError, KeyError) as exc:
        print(f"error: {exc} (pass --force or --on-conflict skip)", file=sys.stderr)
        return EXIT_ERROR

    record_audit_event(
        root,
        interface="cli",
        operation="install",
        status="succeeded",
        source=str(skill_dir),
        destinations=[str(r.dest) for r in results],
        harnesses=targets,
        scan_results=scan_audit,
        overwrite=args.force,
        force=args.force,
        risk_accepted=allow_risky,
        scope=args.scope,
    )
    if is_json:
        print(
            json.dumps(
                {
                    "dry_run": False,
                    "installed": [
                        {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": r.action}
                        for r in results
                    ],
                },
                indent=2,
            )
        )
        return EXIT_OK

    if not is_quiet(args):
        for r in results:
            print(f"  {action_symbol(r.action)} {r.action:9} {r.harness:14} {r.dest}  ({r.detail})")
        for note in shared_path_exclusion_notes(
            targets,
            getattr(args, "exclude_harness", None),
            root,
            scope=args.scope,
            isolated=isolated,
            custom_paths=custom_paths,
        ):
            print(f"  Note: {note}")
    return EXIT_OK


def cmd_update(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    target_arg = (args.skill or "").strip()
    if target_arg in (".", "./") or (target_arg and Path(target_arg).expanduser().is_dir()):
        if target_arg not in ("", ".", "./"):
            root = Path(target_arg).expanduser().resolve()
        target_arg = ""

    dry_run = bool(getattr(args, "dry_run", False))
    is_json = fmt_mode(args) == "json"
    records = load_state(root, scope=args.scope)
    if not records:
        if is_json:
            print(json.dumps({"dry_run": dry_run, "updated": []}, indent=2))
        else:
            print("no managed skills recorded in .skillporter/state.json to update.")
        return EXIT_OK

    allow_risky = bool(getattr(args, "allow_risky", False))
    manifest = load_manifest(root)
    max_risk_score = manifest.max_risk_score if manifest is not None else None
    names = [target_arg] if target_arg else sorted(records)
    updated_items: list[dict[str, object]] = []

    for sname in names:
        rec = records.get(sname)
        if not rec:
            print(f"error: skill {sname!r} is not tracked by skillporter (run `skillporter list`)", file=sys.stderr)
            return EXIT_ERROR
        resolved = resolve_source(rec.source, base_dir=root)
        try:
            matching = [d for d in resolved.skill_dirs if d.name == sname] or resolved.skill_dirs
            for sdir in matching:
                srep = scan_skill(sdir)
                scan_audit = {
                    sdir.name: {
                        "passed": srep.passed,
                        "risk_score": srep.risk_score,
                        "recommendation": srep.recommendation,
                        "finding_codes": [f.code for f in srep.findings],
                    }
                }
                exceeds = srep.exceeds_risk_threshold(max_risk_score)
                if srep.has_structural_escape or (
                    (not srep.passed or not srep.scan_complete or exceeds) and not allow_risky
                ):
                    for f in srep.findings:
                        loc = f"{f.file}:{f.line}" if f.line else f.file
                        print(f"  [{f.severity}] {f.code} ({loc}): {f.message}", file=sys.stderr)
                    record_audit_event(
                        root,
                        interface="cli",
                        operation="update",
                        status="blocked",
                        source=resolved.canonical_source,
                        resolved_commit=resolved.resolved_commit,
                        harnesses=rec.harnesses,
                        scan_results=scan_audit,
                        overwrite=True,
                        force=False,
                        risk_accepted=False,
                        detail=f"update blocked by security policy on {sdir.name}",
                        scope=rec.scope,
                    )
                    print(
                        f"error: update of {sdir.name!r} blocked by static security policy "
                        f"(risk {srep.risk_score}/100); existing installation preserved.",
                        file=sys.stderr,
                    )
                    return EXIT_PROBLEM

                targets = rec.harnesses or ["claude-code", "codex", "cursor"]
                if dry_run:
                    updated_items.append(
                        {
                            "skill": sdir.name,
                            "source": resolved.canonical_source,
                            "resolved_commit": resolved.resolved_commit,
                            "harnesses": targets,
                            "risk_score": srep.risk_score,
                            "action": "would-update",
                        }
                    )
                    continue

                res = run_install(
                    root,
                    sdir,
                    targets,
                    strategy=rec.strategy,
                    scope=rec.scope,
                    force=True,
                    source=resolved.canonical_source,
                    resolved_commit=resolved.resolved_commit,
                    record_state=True,
                )
                record_audit_event(
                    root,
                    interface="cli",
                    operation="update",
                    status="succeeded",
                    source=resolved.canonical_source,
                    resolved_commit=resolved.resolved_commit,
                    destinations=[str(r.dest) for r in res],
                    harnesses=rec.harnesses,
                    scan_results=scan_audit,
                    overwrite=True,
                    force=False,
                    risk_accepted=allow_risky,
                    scope=rec.scope,
                )
                for r in res:
                    updated_items.append(
                        {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": "updated"}
                    )
                    if not is_json:
                        print(f"updated   {r.harness:16} {r.dest}")
        finally:
            resolved.cleanup()

    if is_json:
        print(json.dumps({"dry_run": dry_run, "updated": updated_items}, indent=2))
    elif dry_run:
        print(f"dry-run: {len(updated_items)} skill(s) ready to update (no files modified).")
    return EXIT_OK
