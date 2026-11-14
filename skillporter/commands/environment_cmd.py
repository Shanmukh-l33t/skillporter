"""Environment Status, Diff, Portability (Export/Import), Profiles, Move, Adopt, Outdated & Self-Skill Commands."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .. import __version__, harnesses
from ..audit import record_audit_event
from ..environment import capture_environment, diff_environments, load_snapshot_from_target
from ..frontmatter import parse_skill
from ..install import InstallError, adopt_skills, move_skill, uninstall
from ..install import install as run_install
from ..manifest import LOCKFILE_FILENAME, MANIFEST_FILENAME
from ..portability import SkillpackError, export_skillpack, import_skillpack
from ..profiles import (
    ProfileError,
    activate_profile_manifest,
    delete_profile,
    list_profiles,
    load_profile,
    save_profile_from_environment,
)
from ..security import compute_tree_hash, scan_skill
from ..sources import SourceError, resolve_source
from ..state import load_state
from ..ui import BOLD, action_symbol, badge, render_next_steps, render_table, style
from .common import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PROBLEM,
    fmt_mode,
    is_quiet,
    is_verbose,
    parse_custom_path_args,
    resolve_target_harnesses,
)


def cmd_status(args: argparse.Namespace) -> int:
    """Unified workspace and personal environment control-center status."""
    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return EXIT_ERROR

    scope = getattr(args, "scope", "project")
    snap = capture_environment(root, scope=scope)

    # Maintain backward-compatible per_harness dict alongside rich structured fields
    per_harness: dict[str, dict[str, str]] = {}
    for hname in snap.selected_harnesses:
        per_harness[hname] = {}
        for sname, entry in sorted(snap.skills.items()):
            installed_here = hname in entry.installed_harnesses
            if not installed_here:
                per_harness[hname][sname] = "MISSING_LOCKED" if entry.in_lockfile else "MISSING"
            elif entry.drifted or entry.lock_drifted:
                per_harness[hname][sname] = "INSTALLED_DRIFTED"
            elif entry.in_lockfile:
                per_harness[hname][sname] = "INSTALLED_LOCKED"
            else:
                per_harness[hname][sname] = "INSTALLED_UNLOCKED"

    payload = snap.to_dict()
    payload["per_harness"] = per_harness

    if fmt_mode(args) == "json":
        print(json.dumps(payload, indent=2))
        return EXIT_OK if snap.healthy else EXIT_PROBLEM

    if is_quiet(args):
        if not snap.healthy:
            for f in snap.findings:
                print(f, file=sys.stderr)
        return EXIT_OK if snap.healthy else EXIT_PROBLEM

    verdict = badge("HEALTHY" if snap.healthy else "NEEDS ATTENTION")
    print(f"skillporter {__version__} · environment status ({scope})  [{verdict}]")
    print(f"  Location:           {root}")
    if scope == "project":
        m_label = "present" if snap.manifest_present else "not initialized"
        l_label = f"present ({len(snap.lockfile.skills)} pinned)" if snap.lockfile_present else "not generated"
        print(f"  Config:             {MANIFEST_FILENAME} ({m_label}) · {LOCKFILE_FILENAME} ({l_label})")
    if snap.active_profile:
        print(f"  Active profile:     {snap.active_profile}")
    print(f"  Detected harnesses: {', '.join(snap.detected_harnesses) or '(none)'}")
    print(f"  Active targets:     {', '.join(snap.selected_harnesses) or '(none)'}")

    total_skills = len(snap.skills)
    synced_cnt = sum(1 for e in snap.skills.values() if e.status == "SYNCED")
    unmanaged_cnt = len(snap.unmanaged_skills)
    attn_cnt = len(snap.attention_skills)
    print(
        f"  Skills summary:     {total_skills} total "
        f"({synced_cnt} synced, {unmanaged_cnt} unmanaged, {attn_cnt} needing attention)"
    )

    if snap.skills:
        print()
        trows = []
        for sname, entry in sorted(snap.skills.items()):
            h_list = entry.installed_harnesses
            if len(h_list) > 4 and not is_verbose(args):
                h_cell = ", ".join(h_list[:4]) + f" (+{len(h_list) - 4})"
            else:
                h_cell = ", ".join(h_list) if h_list else "(none)"
            if entry.missing_harnesses:
                h_cell += f" [missing: {', '.join(entry.missing_harnesses)}]"
            trows.append(
                [
                    sname,
                    entry.version,
                    entry.status,
                    "yes" if entry.managed else "no",
                    h_cell,
                ]
            )
        max_r = None if is_verbose(args) else 25
        print(
            render_table(
                ["SKILL", "VERSION", "STATE", "MANAGED", "HARNESSES"],
                trows,
                max_rows=max_r,
                indent="  ",
                more_hint="run `skillporter status --verbose` to list all skills",
            )
        )

    if snap.lock_drift or snap.findings:
        print("\nAttention:")
        for ld in snap.lock_drift:
            print(f"  ! lockfile: {ld}")
        for f in snap.findings:
            print(f"  ! {f}")

    if snap.remediations:
        print("\n" + render_next_steps(snap.remediations))

    return EXIT_OK if snap.healthy else EXIT_PROBLEM


def cmd_diff(args: argparse.Namespace) -> int:
    """Compare current environment (or --base) against a .skillpack, project dir, or profile."""
    scope = getattr(args, "scope", "project")
    base_arg = getattr(args, "base", ".") or "."
    target_arg = args.target

    try:
        left = load_snapshot_from_target(base_arg, scope=scope)
        right = load_snapshot_from_target(target_arg, base_dir=Path.cwd(), scope=scope)
    except (FileNotFoundError, SkillpackError, ProfileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    diff = diff_environments(left, right)
    if fmt_mode(args) == "json":
        print(json.dumps(diff.to_dict(), indent=2))
        return EXIT_PROBLEM if diff.has_differences else EXIT_OK

    if is_quiet(args):
        return EXIT_PROBLEM if diff.has_differences else EXIT_OK

    print(f"Comparing {style(diff.left_label, BOLD)}  vs  {style(diff.right_label, BOLD)}\n")
    if not diff.has_differences:
        print(f"{badge('IDENTICAL')} · {len(diff.identical)} skill(s) match across content, version, and harnesses.")
        return EXIT_OK

    if diff.only_in_right:
        print("Missing locally (present in target):")
        for s in diff.only_in_right:
            re = right.skills[s]
            rh = ", ".join(re.installed_harnesses) or "default"
            print(f"  {action_symbol('added')} {s}@{re.version}  (harnesses: {rh})")
    if diff.only_in_left:
        print("Only present locally (absent in target):")
        for s in diff.only_in_left:
            le = left.skills[s]
            lh = ", ".join(le.installed_harnesses) or "local"
            print(f"  {action_symbol('removed')} {s}@{le.version}  (harnesses: {lh})")
    if diff.version_diffs:
        print("Version differences:")
        for vd in diff.version_diffs:
            sym_u = action_symbol("updated")
            print(f"  {sym_u} {vd['skill']}: local {vd['left_version']} != target {vd['right_version']}")
    if diff.content_diffs:
        print("Content SHA-256 differences:")
        for cd in diff.content_diffs:
            files_note = ""
            cfiles = cd.get("changed_files", [])
            if isinstance(cfiles, list) and cfiles:
                files_note = f"  [files: {', '.join(str(x) for x in cfiles[:5])}]"
            sym_w = action_symbol("warning")
            print(f"  {sym_w} {cd['skill']}: local {cd['left_hash']} != target {cd['right_hash']}{files_note}")
    if diff.harness_diffs:
        print("Harness assignment differences:")
        for hd in diff.harness_diffs:
            print(
                f"  {action_symbol('updated')} {hd['skill']}: "
                f"local [{', '.join(hd['left_harnesses'])}] vs target [{', '.join(hd['right_harnesses'])}]"  # type: ignore[arg-type]
            )
    if diff.identical:
        print(f"\nUnchanged: {len(diff.identical)} skill(s) identical.")

    if str(target_arg).endswith(".skillpack"):
        print(
            "\n"
            + render_next_steps(
                [
                    f"skillporter import {target_arg} --dry-run   # preview restoration plan",
                    f"skillporter import {target_arg} --force     # apply target environment",
                ]
            )
        )
    return EXIT_PROBLEM


def cmd_export(args: argparse.Namespace) -> int:
    """Export managed environment into a portable .skillpack bundle."""
    root = Path(args.path).expanduser().resolve()
    scope = getattr(args, "scope", "project")
    raw_out = getattr(args, "output", "") or ""
    if not raw_out:
        stem = "user-environment" if scope == "user" else (root.name or "environment")
        raw_out = f"{stem}.skillpack"
    out_path = Path(raw_out).expanduser()
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()

    skill_filter = None
    if getattr(args, "skill", None):
        skill_filter = [p.strip() for raw in args.skill for p in raw.split(",") if p.strip()]

    try:
        report = export_skillpack(
            root,
            out_path,
            scope=scope,
            skill_filter=skill_filter,
            include_unmanaged=not bool(getattr(args, "managed_only", False)),
            manifest_only=bool(getattr(args, "manifest_only", False)),
        )
    except (SkillpackError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROBLEM

    record_audit_event(
        root,
        interface="cli",
        operation="export",
        status="succeeded",
        source=str(root),
        destinations=[str(report.output_path)],
        harnesses=report.harnesses,
        scope=scope,
    )

    if fmt_mode(args) == "json":
        print(json.dumps(report.to_dict(), indent=2))
        return EXIT_OK

    if is_quiet(args):
        print(report.output_path)
        return EXIT_OK

    mode_str = "manifest-only reference" if report.manifest_only else "self-contained offline hybrid"
    kb = max(1, round(report.size_bytes / 1024, 1)) if report.size_bytes >= 1024 else f"{report.size_bytes} B"
    size_str = f"{kb} KB" if isinstance(kb, float) else str(kb)
    print(f"{action_symbol('exported')} Exported {style(report.output_path.name, BOLD)} ({size_str}, {mode_str})")
    print(f"  Path:      {report.output_path}")
    print(f"  SHA-256:   {report.archive_sha256[:16]}...")
    preview_skills = ", ".join(report.skills_exported[:8])
    if len(report.skills_exported) > 8:
        preview_skills += "..."
    print(f"  Skills:    {len(report.skills_exported)} ({preview_skills})")
    print(f"  Harnesses: {', '.join(report.harnesses) or '(none)'}")
    if report.profiles_exported:
        print(f"  Profiles:  {', '.join(report.profiles_exported)}")
    if report.excluded_sensitive_files:
        sens_list = ", ".join(report.excluded_sensitive_files)
        print(f"  Security:  excluded {len(report.excluded_sensitive_files)} sensitive file(s) ({sens_list})")
    print(
        "\n"
        + render_next_steps(
            [
                f"skillporter diff {report.output_path.name}             # compare any workspace with this package",
                f"skillporter import {report.output_path.name} --dry-run # preview restore on another machine",
            ]
        )
    )
    return EXIT_OK


def cmd_import(args: argparse.Namespace) -> int:
    """Validate and restore an environment from a .skillpack archive."""
    root = Path(args.path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    pack_path = Path(args.pack).expanduser()
    if not pack_path.is_absolute():
        pack_path = (Path.cwd() / pack_path).resolve()

    scope = getattr(args, "scope", None) or None
    dry_run = bool(getattr(args, "dry_run", False) or getattr(args, "preview", False))
    on_conflict = getattr(args, "on_conflict", "fail") or "fail"
    force = bool(getattr(args, "force", False))
    allow_risky = bool(getattr(args, "allow_risky", False))
    only_detected = bool(getattr(args, "only_detected", False))

    explicit_h: list[str] | None = None
    if getattr(args, "harness", None):
        try:
            explicit_h = resolve_target_harnesses(
                args.harness,
                root,
                scope=scope or "project",
                default_detected=False,
                exclude_harnesses=getattr(args, "exclude_harness", None),
            )
        except KeyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR

    try:
        result = import_skillpack(
            root,
            pack_path,
            scope=scope,
            explicit_harnesses=explicit_h,
            exclude_harnesses=getattr(args, "exclude_harness", None),
            only_detected=only_detected,
            on_conflict=on_conflict,
            force=force,
            allow_risky=allow_risky,
            max_risk_score=getattr(args, "max_risk_score", None),
            restore_manifest=not bool(getattr(args, "no_manifest", False)),
            dry_run=dry_run,
        )
    except (SkillpackError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROBLEM

    plan_d = result["plan"]  # type: ignore[index]
    eff_scope = str(plan_d["target_scope"])  # type: ignore[index]
    if not dry_run:
        record_audit_event(
            root,
            interface="cli",
            operation="import",
            status="succeeded",
            source=str(pack_path),
            destinations=[r["dest"] for r in result["installed"]],  # type: ignore[index]
            harnesses=sorted({r["harness"] for r in result["installed"]}),  # type: ignore[index]
            overwrite=(force or on_conflict == "overwrite"),
            force=force,
            risk_accepted=allow_risky,
            scope=eff_scope,
        )

    if fmt_mode(args) == "json":
        print(json.dumps(result, indent=2))
        if dry_run and not plan_d["ready"]:  # type: ignore[index]
            return EXIT_PROBLEM
        return EXIT_OK

    if is_quiet(args):
        return EXIT_PROBLEM if (dry_run and not plan_d["ready"]) else EXIT_OK  # type: ignore[index]

    if dry_run:
        verdict = badge("READY" if plan_d["ready"] else "CONFLICTS / BLOCKED")  # type: ignore[index]
        print(f"Import preview for {style(pack_path.name, BOLD)} -> {root} ({eff_scope})  [{verdict}]")
        for s in plan_d["skills"]:  # type: ignore[index]
            t_str = ", ".join(s["target_harnesses"]) or "(none)"
            print(f"  {action_symbol('would-import')} {s['name']}@{s['version']} ({s['tree_hash']}) -> {t_str}")
        if plan_d["missing_harnesses"]:  # type: ignore[index]
            print(
                f"\nNote: {len(plan_d['missing_harnesses'])} harness(es) in package are not detected on this machine: "  # type: ignore[index]
                f"{', '.join(plan_d['missing_harnesses'])} (pass --only-detected to skip them)"  # type: ignore[index]
            )
        for vc in plan_d["version_conflicts"]:  # type: ignore[index]
            print(f"  ! version diff: {vc}")
        for dc in plan_d["destination_conflicts"]:  # type: ignore[index]
            print(f"  x conflict: {dc}")
        for sb in plan_d["security_blocked"]:  # type: ignore[index]
            print(f"  x security: {sb}")
        for md in plan_d["missing_dependencies"]:  # type: ignore[index]
            print(f"  x dependency: {md}")
        return EXIT_OK if plan_d["ready"] else EXIT_PROBLEM  # type: ignore[index]

    inst_rows: list[dict[str, str]] = result["installed"]  # type: ignore[assignment]
    skip_rows: list[dict[str, str]] = result["skipped"]  # type: ignore[assignment]
    unique_skills = sorted({r["skill"] for r in inst_rows})
    unique_harnesses = sorted({r["harness"] for r in inst_rows})
    print(
        f"{action_symbol('imported')} Restored {len(unique_skills)} skill(s) across "
        f"{len(unique_harnesses)} harness(es) from {style(pack_path.name, BOLD)}"
    )
    for r in inst_rows:
        if r["action"] != "unchanged" or is_verbose(args):
            print(f"  {action_symbol(r['action'])} {r['skill']} -> {r['harness']} ({r['dest']})")
    if skip_rows:
        print(f"  ! Skipped {len(skip_rows)} destination(s) (existing files preserved)")
    if result.get("missing_harnesses"):
        mh: list[str] = result["missing_harnesses"]  # type: ignore[assignment]
        print(f"  Note: harness(es) not detected on this host: {', '.join(mh)}")
    print("\n" + render_next_steps(["skillporter status                # verify restored environment state"]))
    return EXIT_OK


def cmd_profile(args: argparse.Namespace) -> int:
    """Manage named environment profiles (`list`, `save`/`create`, `show`, `use`, `delete`)."""
    sub = getattr(args, "profile_action", None) or "list"
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    scope = getattr(args, "scope", "project")

    try:
        if sub == "list":
            rows = list_profiles(root, scope=scope)
            if fmt_mode(args) == "json":
                print(json.dumps({"root": str(root), "scope": scope, "profiles": rows}, indent=2))
                return EXIT_OK
            if not rows:
                if not is_quiet(args):
                    print(f"No environment profiles saved in {scope} scope.")
                    print(
                        "\n"
                        + render_next_steps(
                            ["skillporter profile save default  # save current setup as a named profile"]
                        )
                    )
                return EXIT_OK
            trows = [
                [
                    ("* " + str(r["name"])) if r["active"] else ("  " + str(r["name"])),
                    str(r["skill_count"]),
                    ", ".join(r["harnesses"]),  # type: ignore[arg-type]
                ]
                for r in rows
            ]
            print(render_table(["PROFILE", "SKILLS", "HARNESSES"], trows))
            return EXIT_OK

        if sub in ("save", "create"):
            pname = args.name
            explicit_h = None
            if getattr(args, "harness", None):
                explicit_h = resolve_target_harnesses(args.harness, root, scope=scope, default_detected=False)
            explicit_s = None
            if getattr(args, "skill", None):
                explicit_s = [p.strip() for raw in args.skill for p in raw.split(",") if p.strip()]
            prof = save_profile_from_environment(
                root,
                pname,
                scope=scope,
                explicit_harnesses=explicit_h,
                explicit_skills=explicit_s,
                overwrite=True,
            )
            if fmt_mode(args) == "json":
                print(
                    json.dumps(
                        {
                            "profile": prof.profile,
                            "scope": scope,
                            "harnesses": prof.harnesses,
                            "skills": [s.name for s in prof.skills],
                        },
                        indent=2,
                    )
                )
                return EXIT_OK
            if not is_quiet(args):
                print(
                    f"{action_symbol('created')} Saved profile {style(prof.profile, BOLD)} "
                    f"({len(prof.skills)} skill(s), harnesses: {', '.join(prof.harnesses)})"
                )
            return EXIT_OK

        if sub == "show":
            prof = load_profile(root, args.name, scope=scope)
            if fmt_mode(args) == "json":
                print(
                    json.dumps(
                        {
                            "profile": prof.profile,
                            "scope": prof.scope,
                            "strategy": prof.strategy,
                            "harnesses": prof.harnesses,
                            "skills": [s.to_dict() for s in prof.skills],
                        },
                        indent=2,
                    )
                )
                return EXIT_OK
            print(prof.to_yaml(), end="")
            return EXIT_OK

        if sub == "delete":
            deleted = delete_profile(root, args.name, scope=scope)
            if fmt_mode(args) == "json":
                print(json.dumps({"deleted": args.name, "path": str(deleted)}, indent=2))
            elif not is_quiet(args):
                print(f"{action_symbol('deleted')} Deleted profile {args.name!r}")
            return EXIT_OK

        if sub == "use":
            pname = args.name
            dry_run = bool(getattr(args, "dry_run", False))
            prune = bool(getattr(args, "prune", False))
            prof = load_profile(root, pname, scope=scope)
            cur_snap = capture_environment(root, scope=scope)
            prof_skill_names = {s.name for s in prof.skills}
            to_prune = sorted(s for s in cur_snap.managed_skills if s not in prof_skill_names) if prune else []

            if dry_run:
                payload = {
                    "dry_run": True,
                    "profile": prof.profile,
                    "harnesses": prof.harnesses,
                    "skills_to_sync": [s.name for s in prof.skills],
                    "skills_to_prune": to_prune,
                }
                if fmt_mode(args) == "json":
                    print(json.dumps(payload, indent=2))
                else:
                    print(f"Preview switching to profile {style(prof.profile, BOLD)}:")
                    print(f"  Harnesses: {', '.join(prof.harnesses)}")
                    print(f"  Skills:    {', '.join(s.name for s in prof.skills) or '(none)'}")
                    if to_prune:
                        print(f"  Prune:     {', '.join(to_prune)}")
                return EXIT_OK

            from ..policy import evaluate_policy, load_policy

            policy_prof = load_policy(root) if scope == "project" else None
            # Validate all profile skills against security and policy BEFORE mutating manifest or disk!
            for spec_chk in prof.skills:
                targets_chk = spec_chk.harnesses or prof.harnesses
                res_chk = resolve_source(spec_chk.source, base_dir=root, ref_override=spec_chk.ref)
                try:
                    matches_chk = [d for d in res_chk.skill_dirs if d.name == spec_chk.name] or res_chk.skill_dirs
                    for sdir_chk in matches_chk:
                        srep_chk = scan_skill(sdir_chk, offline=True)
                        if srep_chk.has_structural_escape or not srep_chk.passed:
                            raise ProfileError(f"skill {sdir_chk.name!r} in profile {pname!r} failed security scan")
                        pol_errs = evaluate_policy(
                            policy_prof,
                            skill_dirs=[sdir_chk],
                            source_candidates=[spec_chk.source, res_chk.canonical_source],
                            resolved_commit=res_chk.resolved_commit,
                            ref=spec_chk.ref,
                            target_harnesses=targets_chk,
                            sec_reports={sdir_chk.name: srep_chk},
                        )
                        if pol_errs:
                            raise ProfileError(
                                f"profile {pname!r} blocked by project security policy: " + "; ".join(pol_errs)
                            )
                finally:
                    res_chk.cleanup()

            activate_profile_manifest(root, pname, scope=scope)
            installed_count = 0
            for spec in prof.skills:
                targets = spec.harnesses or prof.harnesses
                resolved = resolve_source(spec.source, base_dir=root, ref_override=spec.ref)
                try:
                    matches = [d for d in resolved.skill_dirs if d.name == spec.name] or resolved.skill_dirs
                    for sdir in matches:
                        srep = scan_skill(sdir, offline=True)
                        if srep.has_structural_escape or not srep.passed:
                            raise ProfileError(f"skill {sdir.name!r} in profile {pname!r} failed security scan")
                        run_install(
                            root,
                            sdir,
                            targets,
                            strategy=spec.strategy or prof.strategy,
                            scope=scope,
                            force=True,
                            source=spec.source,
                            resolved_commit=resolved.resolved_commit,
                            version=spec.version,
                            record_state=True,
                            skill_name_override=spec.name,
                        )
                        installed_count += 1
                finally:
                    resolved.cleanup()

            pruned_list: list[str] = []
            if to_prune:
                records = load_state(root, scope=scope)
                for ps in to_prune:
                    rec = records.get(ps)
                    targets_rm = rec.harnesses if (rec and rec.harnesses) else harnesses.names()
                    uninstall(root, ps, targets_rm, scope=scope, record_state=True)
                    pruned_list.append(ps)

            if fmt_mode(args) == "json":
                print(
                    json.dumps(
                        {
                            "active_profile": prof.profile,
                            "harnesses": prof.harnesses,
                            "synced_skills": installed_count,
                            "pruned_skills": pruned_list,
                        },
                        indent=2,
                    )
                )
            elif not is_quiet(args):
                print(
                    f"{action_symbol('synced')} Activated profile {style(prof.profile, BOLD)} "
                    f"({installed_count} skill(s) synchronized across {', '.join(prof.harnesses)})"
                )
                if pruned_list:
                    print(f"  {action_symbol('pruned')} Pruned previous profile skill(s): {', '.join(pruned_list)}")
            return EXIT_OK

    except (ProfileError, SourceError, InstallError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    return EXIT_OK


def cmd_move(args: argparse.Namespace) -> int:
    """Move a skill from one or more harnesses to another set of harnesses safely."""
    root = Path(args.path).expanduser().resolve()
    scope = getattr(args, "scope", "project")
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        from_h = resolve_target_harnesses(args.from_harness, root, scope=scope, default_detected=False)
        to_h = resolve_target_harnesses(
            args.to_harness,
            root,
            scope=scope,
            default_detected=False,
            exclude_harnesses=getattr(args, "exclude_harness", None),
        )
        custom_p = parse_custom_path_args(getattr(args, "custom_path", None))
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if dry_run:
        payload = {
            "dry_run": True,
            "skill": args.skill,
            "from_harnesses": from_h,
            "to_harnesses": to_h,
            "scope": scope,
            "isolated": bool(getattr(args, "isolated", False)),
        }
        if fmt_mode(args) == "json":
            print(json.dumps(payload, indent=2))
        elif not is_quiet(args):
            print(f"Preview move {args.skill!r}: {', '.join(from_h)} -> {', '.join(to_h)} ({scope})")
        return EXIT_OK

    try:
        results = move_skill(
            root,
            args.skill,
            from_harnesses=from_h,
            to_harnesses=to_h,
            scope=scope,
            strategy=getattr(args, "strategy", "copy"),
            force=bool(getattr(args, "force", False)),
            on_conflict=getattr(args, "on_conflict", "fail") or "fail",
            isolated=bool(getattr(args, "isolated", False)),
            custom_paths=custom_p,
        )
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    record_audit_event(
        root,
        interface="cli",
        operation="move",
        status="succeeded",
        source=args.skill,
        destinations=[str(r.dest) for r in results],
        harnesses=to_h,
        scope=scope,
    )

    if fmt_mode(args) == "json":
        print(
            json.dumps(
                {
                    "dry_run": False,
                    "skill": args.skill,
                    "from_harnesses": from_h,
                    "to_harnesses": to_h,
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

    if not is_quiet(args):
        print(f"{action_symbol('moved')} Moved {style(args.skill, BOLD)}: {', '.join(from_h)} -> {', '.join(to_h)}")
        for r in results:
            print(f"  {action_symbol(r.action)} {r.harness:14} {r.action:16} ({r.dest})")
    return EXIT_OK


def cmd_adopt(args: argparse.Namespace) -> int:
    """Adopt existing unmanaged on-disk skills into Skillporter state & manifest."""
    root = Path(args.path).expanduser().resolve()
    scope = getattr(args, "scope", "project")
    skills_arg: list[str] | None = list(args.skills) if getattr(args, "skills", None) else None
    if not skills_arg and not getattr(args, "all", False):
        skills_arg = None  # default to adopting all unmanaged skills in scope

    try:
        adopted = adopt_skills(
            root,
            skills_arg,
            scope=scope,
            allow_risky=bool(getattr(args, "allow_risky", False)),
        )
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROBLEM

    if fmt_mode(args) == "json":
        print(json.dumps({"scope": scope, "adopted": adopted}, indent=2))
        return EXIT_OK

    if not is_quiet(args):
        if not adopted:
            print("No unmanaged skills found to adopt.")
        else:
            print(f"{action_symbol('adopted')} Adopted {len(adopted)} skill(s) into Skillporter management:")
            for item in adopted:
                h_str = ", ".join(item["harnesses"]) if item["harnesses"] else "(none)"  # type: ignore[arg-type]
                print(f"  + {item['name']}@{item['version']} ({str(item['tree_hash'])[:12]})  [{h_str}]")
    return EXIT_OK


def cmd_outdated(args: argparse.Namespace) -> int:
    """Check managed skills against their upstream sources without modifying files."""
    root = Path(args.path).expanduser().resolve()
    scope = getattr(args, "scope", "project")
    records = load_state(root, scope=scope)
    target_skill = (getattr(args, "skill", "") or "").strip()

    if not records:
        if fmt_mode(args) == "json":
            print(json.dumps({"scope": scope, "skills": [], "outdated_count": 0}, indent=2))
        elif not is_quiet(args):
            print("No managed skills recorded yet (run `skillporter adopt --all` or `skillporter add`).")
        return EXIT_OK

    names = [target_skill] if target_skill else sorted(records)
    rows: list[dict[str, object]] = []
    outdated_cnt = 0

    for sname in names:
        rec = records.get(sname)
        if not rec:
            print(f"error: skill {sname!r} is not managed by skillporter", file=sys.stderr)
            return EXIT_ERROR
        try:
            resolved = resolve_source(rec.source, base_dir=root)
        except (SourceError, KeyError) as exc:
            rows.append(
                {
                    "skill": sname,
                    "installed_version": rec.version,
                    "upstream_version": "unreachable",
                    "installed_hash": rec.tree_hash[:12],
                    "upstream_hash": "",
                    "status": "ERROR",
                    "source": rec.source,
                    "detail": str(exc),
                }
            )
            continue

        try:
            matching = [d for d in resolved.skill_dirs if d.name == sname] or resolved.skill_dirs
            sdir = matching[0]
            up_hash, _ = compute_tree_hash(sdir)
            doc = parse_skill(sdir / "SKILL.md")
            meta = doc.frontmatter.get("metadata")
            up_ver = str(meta.get("version", rec.version)) if isinstance(meta, dict) else rec.version
            is_diff = bool(rec.tree_hash and up_hash and rec.tree_hash != up_hash)
            if is_diff:
                outdated_cnt += 1
            rows.append(
                {
                    "skill": sname,
                    "installed_version": rec.version,
                    "upstream_version": up_ver,
                    "installed_hash": rec.tree_hash[:12],
                    "upstream_hash": up_hash[:12],
                    "upstream_commit": resolved.resolved_commit[:12] if resolved.resolved_commit else "",
                    "status": "OUTDATED" if is_diff else "UP-TO-DATE",
                    "source": rec.source,
                }
            )
        finally:
            resolved.cleanup()

    if fmt_mode(args) == "json":
        print(json.dumps({"scope": scope, "outdated_count": outdated_cnt, "skills": rows}, indent=2))
        return EXIT_OK

    if is_quiet(args):
        for r in rows:
            if r["status"] == "OUTDATED":
                print(r["skill"])
        return EXIT_OK

    trows = [
        [
            str(r["skill"]),
            str(r["installed_version"]),
            str(r["upstream_version"]),
            f"{r['installed_hash']} -> {r['upstream_hash']}" if r["status"] == "OUTDATED" else str(r["installed_hash"]),
            str(r["status"]),
            str(r["source"]),
        ]
        for r in rows
    ]
    print(render_table(["SKILL", "CURRENT", "UPSTREAM", "CONTENT HASH", "STATUS", "SOURCE"], trows))
    if outdated_cnt:
        print(
            "\n"
            + render_next_steps(
                [
                    "skillporter update --dry-run      # preview security scan and update plan",
                    "skillporter update                # update outdated skills (snapshots backup first)",
                ]
            )
        )
    return EXIT_OK


def _resolve_bundled_self_skill_dir() -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    """Locate the official Skillporter SKILL.md from the repo, wheel, or .pyz zipapp."""
    import importlib.resources

    repo_candidate = Path(__file__).resolve().parents[2] / "skills" / "skillporter"
    if (repo_candidate / "SKILL.md").is_file():
        return repo_candidate, None

    try:
        res_text = (
            importlib.resources.files("skillporter.bundled_skill")
            .joinpath("SKILL_TEMPLATE.md")
            .read_text(encoding="utf-8")
        )
        tmp_ctx = tempfile.TemporaryDirectory(prefix="skillporter-self-skill-")
        stage_dir = Path(tmp_ctx.name) / "skillporter"
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "SKILL.md").write_text(res_text, encoding="utf-8")
        return stage_dir, tmp_ctx
    except Exception as exc:
        raise FileNotFoundError(f"official Skillporter SKILL.md bundle not found in package: {exc}") from exc


def cmd_self_skill(args: argparse.Namespace) -> int:
    """Bootstrap or inspect the official Skillporter AI agent skill across harnesses."""
    action = getattr(args, "self_skill_action", None) or "install"
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    scope = getattr(args, "scope", "project")

    try:
        sdir, tmp_ctx = _resolve_bundled_self_skill_dir()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        if action == "path":
            if fmt_mode(args) == "json":
                print(json.dumps({"path": str(sdir / "SKILL.md")}, indent=2))
            else:
                print(sdir / "SKILL.md")
            return EXIT_OK

        if action == "show":
            text = (sdir / "SKILL.md").read_text(encoding="utf-8")
            if fmt_mode(args) == "json":
                print(json.dumps({"name": "skillporter", "content": text}, indent=2))
            else:
                print(text, end="")
            return EXIT_OK

        try:
            targets = resolve_target_harnesses(
                getattr(args, "harness", None),
                root,
                scope=scope,
                default_detected=True,
                exclude_harnesses=getattr(args, "exclude_harness", None),
            )
        except KeyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR

        dry_run = bool(getattr(args, "dry_run", False))
        if dry_run:
            if fmt_mode(args) == "json":
                print(
                    json.dumps(
                        {"dry_run": True, "skill": "skillporter", "harnesses": targets, "scope": scope}, indent=2
                    )
                )
            elif not is_quiet(args):
                print(f"Would install official 'skillporter' skill into {', '.join(targets)} ({scope} scope)")
            return EXIT_OK

        results = run_install(
            root,
            sdir,
            targets,
            strategy="copy",
            scope=scope,
            force=bool(getattr(args, "force", True)),
            source="https://github.com/Shanmukh-l33t/skillporter/tree/main/skills/skillporter",
            version=__version__,
            record_state=True,
            skill_name_override="skillporter",
        )
        if fmt_mode(args) == "json":
            print(
                json.dumps(
                    {
                        "skill": "skillporter",
                        "version": __version__,
                        "scope": scope,
                        "installed": [{"harness": r.harness, "dest": str(r.dest), "action": r.action} for r in results],
                    },
                    indent=2,
                )
            )
            return EXIT_OK

        if not is_quiet(args):
            print(
                f"{action_symbol('installed')} Installed official {style('skillporter', BOLD)} AI skill "
                f"across {len(targets)} harness(es) ({scope} scope):"
            )
            for r in results:
                print(f"  {action_symbol(r.action)} {r.harness:14} {r.dest}")
        return EXIT_OK
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()
