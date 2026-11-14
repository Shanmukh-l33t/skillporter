"""Init, sync, lock, and dependency graph command implementations."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from .. import __version__, harnesses
from ..atomic import workspace_lock
from ..audit import record_audit_event
from ..ci_report import check_lockfile_staleness
from ..diagnose import diagnose as run_diagnose
from ..frontmatter import discover
from ..install import install as run_install
from ..install import plan_install
from ..manifest import (
    LOCKFILE_FILENAME,
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    LockedSkill,
    LockfileError,
    ManifestSkillSpec,
    ProjectManifest,
    load_lockfile,
    load_manifest,
    save_lockfile,
    save_manifest,
)
from ..policy import evaluate_policy, load_policy
from ..resolver import DependencyConflictError, DependencyCycleError, DependencyError, resolve_dependency_graph
from ..security import compute_tree_hash, scan_skill
from ..sources import resolve_source
from ..state import load_state
from ..ui import action_symbol
from .common import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_PROBLEM,
    fmt_mode,
    is_quiet,
    is_verbose,
    latest_tree_mtime_ns,
    resolve_target_harnesses,
)


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    mpath = root / MANIFEST_FILENAME
    if mpath.exists() and not args.force:
        print(f"error: {mpath} already exists (use --force to overwrite)", file=sys.stderr)
        return EXIT_ERROR

    detected = [d.harness.name for d in harnesses.detect_harnesses(root) if d.project_active]
    default_harnesses = detected if detected else ["claude-code", "codex", "cursor"]

    existing_skills: list[ManifestSkillSpec] = []
    seen: set[str] = set()
    for skill_md in discover(root):
        sname = skill_md.parent.name
        if sname in seen:
            continue
        seen.add(sname)
        try:
            rel = skill_md.parent.resolve().relative_to(root).as_posix()
        except ValueError:
            rel = str(skill_md.parent)
        existing_skills.append(ManifestSkillSpec(name=sname, source=f"./{rel}"))

    manifest = ProjectManifest(
        project=root.name or "my-project",
        scope="project",
        strategy="copy",
        harnesses=default_harnesses,
        skills=existing_skills,
    )
    save_manifest(root, manifest)
    if fmt_mode(args) == "json":
        print(
            json.dumps(
                {
                    "manifest": str(mpath),
                    "skills": [s.name for s in existing_skills],
                    "harnesses": default_harnesses,
                },
                indent=2,
            )
        )
    else:
        print(f"initialized {mpath} ({len(existing_skills)} skill(s), harnesses: {', '.join(default_harnesses)})")
    return EXIT_OK


def cmd_lock(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    fmt = fmt_mode(args)
    if getattr(args, "check", False):
        issues = check_lockfile_staleness(root)
        manifest = load_manifest(root)
        if (
            manifest
            and manifest.skills
            and not any(
                "corrupted" in i or "unsupported" in i or "source mismatch" in i for i in issues
            )
        ):
            graph_chk = None
            try:
                lock_now = load_lockfile(root, warn_migration=False)
                graph_chk = resolve_dependency_graph(root, manifest, lockfile=lock_now)
                for sname in graph_chk.install_order:
                    if sname not in lock_now.skills:
                        issues.append(f"unpinned dependency in graph: {sname!r} is missing from {LOCKFILE_FILENAME}")
            except (DependencyError, LockfileError) as exc:
                issues.append(f"dependency/lockfile error: {exc}")
            finally:
                if graph_chk is not None:
                    graph_chk.cleanup()

        if fmt == "json":
            print(json.dumps({"clean": len(issues) == 0, "issues": issues}, indent=2))
            return EXIT_PROBLEM if issues else EXIT_OK
        if issues:
            print(f"{LOCKFILE_FILENAME} check FAILED ({len(issues)} issue(s)):", file=sys.stderr)
            for iss in issues:
                print(f"  - {iss}", file=sys.stderr)
            return EXIT_PROBLEM
        print(f"{LOCKFILE_FILENAME} is up to date and verified (0 drift).")
        return EXIT_OK

    with workspace_lock(root):
        records = load_state(root)
        manifest = load_manifest(root)
        try:
            lock = load_lockfile(root, warn_migration=False)
        except LockfileError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_PROBLEM

        m_schema = manifest.schema_version if manifest else MANIFEST_SCHEMA_VERSION
        m_scope = manifest.scope if manifest else "project"
        lock.manifest_schema_version = m_schema

        graph = None
        with contextlib.suppress(Exception):
            graph = resolve_dependency_graph(root, manifest, lockfile=lock if lock.skills else None)

        try:
            if records:
                for sname, rec in sorted(records.items()):
                    gnode = graph.nodes.get(sname) if graph else None
                    fhashes: dict[str, str] = dict(gnode.file_hashes) if (gnode and gnode.file_hashes) else {}
                    if not fhashes and rec.destinations:
                        first_d = Path(rec.destinations[0])
                        if first_d.is_dir():
                            _, fhashes = compute_tree_hash(first_d)
                    lock.skills[sname] = LockedSkill(
                        name=sname,
                        source=rec.source,
                        resolved_commit=rec.resolved_commit or (gnode.resolved_commit if gnode else ""),
                        version=gnode.version if gnode else rec.version,
                        tree_hash=rec.tree_hash,
                        strategy=rec.strategy,
                        installed_targets=rec.harnesses,
                        locked_at=rec.updated_at,
                        dependencies=dict(gnode.dependencies) if gnode else {},
                        risk_score=gnode.risk_score if gnode else 0,
                        direct=gnode.direct if gnode else True,
                        file_hashes=fhashes,
                        adapter_version=__version__,
                        scope=rec.scope or m_scope,
                        manifest_schema_version=m_schema,
                    )
            if graph:
                for sname, gnode in sorted(graph.nodes.items()):
                    if sname in lock.skills:
                        lock.skills[sname].dependencies = dict(gnode.dependencies)
                        lock.skills[sname].risk_score = gnode.risk_score
                        lock.skills[sname].direct = gnode.direct
                        if gnode.file_hashes and not lock.skills[sname].file_hashes:
                            lock.skills[sname].file_hashes = dict(gnode.file_hashes)
                        lock.skills[sname].adapter_version = __version__
                        lock.skills[sname].manifest_schema_version = m_schema
                        if gnode.version and lock.skills[sname].version == "1.0.0":
                            lock.skills[sname].version = gnode.version
                    else:
                        lock.skills[sname] = LockedSkill(
                            name=sname,
                            source=gnode.source,
                            resolved_commit=gnode.resolved_commit,
                            version=gnode.version,
                            tree_hash=gnode.tree_hash,
                            strategy="copy",
                            installed_targets=manifest.harnesses if manifest else [],
                            dependencies=dict(gnode.dependencies),
                            risk_score=gnode.risk_score,
                            direct=gnode.direct,
                            file_hashes=dict(gnode.file_hashes),
                            adapter_version=__version__,
                            scope=m_scope,
                            manifest_schema_version=m_schema,
                        )
            elif not records:
                for skill_md in discover(root):
                    sname = skill_md.parent.name
                    if sname in lock.skills:
                        continue
                    thash, fhashes = compute_tree_hash(skill_md.parent)
                    srep = scan_skill(skill_md.parent, offline=True)
                    lock.skills[sname] = LockedSkill(
                        name=sname,
                        source=f"./{skill_md.parent.relative_to(root).as_posix()}",
                        resolved_commit="",
                        version="1.0.0",
                        tree_hash=thash,
                        strategy="copy",
                        installed_targets=[],
                        risk_score=srep.risk_score,
                        direct=True,
                        file_hashes=fhashes,
                        adapter_version=__version__,
                        scope=m_scope,
                        manifest_schema_version=m_schema,
                    )
        finally:
            if graph is not None:
                graph.cleanup()

        lpath = save_lockfile(root, lock)
    if fmt == "json":
        print(json.dumps(lock.to_dict(), indent=2, sort_keys=True))
    else:
        if getattr(args, "quiet", False):
            return EXIT_OK
        print(f"wrote {lpath} ({len(lock.skills)} locked skill(s))")
    return EXIT_OK


def cmd_sync(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    dry_run = bool(getattr(args, "dry_run", False))
    is_json = fmt_mode(args) == "json"

    with workspace_lock(root):
        manifest = load_manifest(root)
        try:
            lock = load_lockfile(root)
        except LockfileError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_PROBLEM
        has_existing_lock = (root / LOCKFILE_FILENAME).is_file()
        try:
            targets = resolve_target_harnesses(
                args.harness,
                root,
                scope=args.scope,
                default_detected=True,
                exclude_harnesses=getattr(args, "exclude_harness", None),
            )
        except KeyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR
        force_flag = getattr(args, "force", False)
        prefer_path = getattr(args, "prefer", None)
        allow_risky = getattr(args, "allow_risky", False)
        max_risk_score = getattr(args, "max_risk_score", None)
        if max_risk_score is None and manifest is not None:
            max_risk_score = manifest.max_risk_score

        diag = run_diagnose(root, scope=args.scope)

        policy = load_policy(root) if args.scope == "project" else None
        for sname, copies in sorted(diag.skill_copies.items()):
            for cdir in copies:
                srep = scan_skill(cdir)
                pol_v = evaluate_policy(
                    policy,
                    skill_dirs=[cdir],
                    target_harnesses=targets,
                    sec_reports={cdir.name: srep},
                )
                if pol_v:
                    print("error: sync blocked by project security policy: " + "; ".join(pol_v), file=sys.stderr)
                    return EXIT_PROBLEM
                if srep.has_structural_escape or ((not srep.passed or not srep.scan_complete) and not allow_risky):
                    print(
                        f"error: sync blocked by static security policy on {sname!r} ({cdir}); "
                        "run `skillporter scan` to inspect findings.",
                        file=sys.stderr,
                    )
                    return EXIT_PROBLEM
                if srep.exceeds_risk_threshold(max_risk_score) and not allow_risky:
                    print(
                        f"error: sync blocked by configured security.max_risk_score ({max_risk_score}) on {sname!r} "
                        f"(risk_score {srep.risk_score}/100 > {max_risk_score})",
                        file=sys.stderr,
                    )
                    return EXIT_PROBLEM

        if has_existing_lock and not force_flag and not prefer_path:
            lock_mismatches: list[str] = []
            for sname, locked in sorted(lock.skills.items()):
                for cdir in diag.skill_copies.get(sname, []):
                    actual_hash, _ = compute_tree_hash(cdir)
                    if locked.tree_hash and actual_hash != locked.tree_hash:
                        lock_mismatches.append(
                            f"{sname} ({cdir}): locked {locked.tree_hash[:8]} != disk {actual_hash[:8]}"
                        )
            if lock_mismatches:
                print(
                    "error: on-disk skill content differs from skillporter.lock; refusing to re-lock without --force:",
                    file=sys.stderr,
                )
                for lm in lock_mismatches:
                    print(f"  - {lm}", file=sys.stderr)
                return EXIT_PROBLEM

        if diag.drifted and not force_flag and not prefer_path:
            print(
                "error: content drift detected across existing skill copies; refusing to overwrite without --force:",
                file=sys.stderr,
            )
            for sname, phashes in sorted(diag.drifted.items()):
                locs = ", ".join(f"{p} ({h[:8]})" for p, h in sorted(phashes.items()))
                print(f"  - {sname}: {locs}", file=sys.stderr)
            print(
                "Re-run `skillporter sync --force` (or `--prefer <path>`) to synchronize "
                "(existing copies are snapshotted to .skillporter/backups/ first).",
                file=sys.stderr,
            )
            return EXIT_PROBLEM

        synced_results = []
        if manifest and manifest.skills and not prefer_path and not diag.drifted:
            try:
                graph = resolve_dependency_graph(
                    root,
                    manifest,
                    lockfile=(lock if has_existing_lock and not force_flag else None),
                )
            except (DependencyCycleError, DependencyConflictError, DependencyError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return EXIT_PROBLEM

            try:
                if has_existing_lock and not force_flag:
                    for sname in graph.install_order:
                        node = graph.nodes[sname]
                        locked_node = lock.skills.get(sname)
                        if locked_node and locked_node.tree_hash and node.skill_dir and node.skill_dir.exists():
                            resolved_hash, _ = compute_tree_hash(node.skill_dir)
                            if resolved_hash != locked_node.tree_hash:
                                print(
                                    f"error: upstream source integrity mismatch for {sname!r}: "
                                    f"resolved tree_hash {resolved_hash[:12]} differs from skillporter.lock "
                                    f"({locked_node.tree_hash[:12]}); pass --force if intentional.",
                                    file=sys.stderr,
                                )
                                return EXIT_PROBLEM

                if dry_run:
                    planned_dirs: list[Path] = []
                    for s in graph.install_order:
                        s_dir = graph.nodes[s].skill_dir
                        if s_dir is not None:
                            planned_dirs.append(s_dir)
                    plan = plan_install(
                        root, planned_dirs, targets, strategy=args.strategy, scope=args.scope, force=True
                    )
                    if is_json:
                        print(
                            json.dumps(
                                {
                                    "dry_run": True,
                                    "skills": graph.install_order,
                                    "harnesses": targets,
                                    "destinations": [str(d.resolved_dest) for d in plan.destinations],
                                },
                                indent=2,
                            )
                        )
                    else:
                        print(f"dry-run: would synchronize {len(graph.install_order)} skill(s) across {targets}")
                    return EXIT_OK

                spec_by_name = {s.name: s for s in manifest.skills}
                for sname in graph.install_order:
                    node = graph.nodes[sname]
                    spec = spec_by_name.get(sname)
                    spec_h = spec.harnesses if spec and spec.harnesses else None
                    skill_targets = spec_h or manifest.harnesses or targets
                    strategy = (spec.strategy if spec and spec.strategy else None) or manifest.strategy or args.strategy

                    if node.skill_dir and node.skill_dir.exists():
                        sdir = node.skill_dir
                        srep = scan_skill(sdir)
                        pol_v_node = evaluate_policy(
                            policy,
                            skill_dirs=[sdir],
                            source_candidates=[spec.source if spec else node.source, node.source],
                            resolved_commit=node.resolved_commit,
                            ref=spec.ref if spec else "",
                            target_harnesses=skill_targets,
                            sec_reports={sdir.name: srep},
                        )
                        if pol_v_node:
                            print(
                                "error: sync blocked by project security policy: " + "; ".join(pol_v_node),
                                file=sys.stderr,
                            )
                            return EXIT_PROBLEM
                        if srep.has_structural_escape or (not srep.passed and not allow_risky):
                            print(f"error: sync blocked by static security policy on {sdir.name!r}", file=sys.stderr)
                            return EXIT_PROBLEM
                        if srep.exceeds_risk_threshold(max_risk_score) and not allow_risky:
                            print(
                                f"error: sync blocked by configured security.max_risk_score ({max_risk_score}) "
                                f"on {sdir.name!r} (risk_score {srep.risk_score}/100 > {max_risk_score})",
                                file=sys.stderr,
                            )
                            return EXIT_PROBLEM
                        res = run_install(
                            root,
                            sdir,
                            skill_targets,
                            strategy=strategy,
                            scope=args.scope,
                            force=True,
                            source=node.source,
                            resolved_commit=node.resolved_commit,
                            version=node.version,
                            record_state=True,
                            skill_name_override=sname,
                        )
                        synced_results.extend(res)
                    elif spec:
                        use_lock = has_existing_lock and not force_flag and sname in lock.skills
                        pinned_ref = (
                            lock.skills[sname].resolved_commit
                            if (use_lock and lock.skills[sname].resolved_commit)
                            else spec.ref
                        )
                        resolved = resolve_source(spec.source, base_dir=root, ref_override=pinned_ref)
                        try:
                            for sdir in resolved.skill_dirs:
                                if sdir.name != spec.name and len(resolved.skill_dirs) > 1:
                                    continue
                                if use_lock and lock.skills[sname].tree_hash:
                                    rhash, _ = compute_tree_hash(sdir)
                                    if rhash != lock.skills[sname].tree_hash:
                                        print(
                                            f"error: upstream source integrity mismatch for {sname!r}: "
                                            f"resolved tree_hash {rhash[:12]} differs from skillporter.lock "
                                            f"({lock.skills[sname].tree_hash[:12]})",
                                            file=sys.stderr,
                                        )
                                        return EXIT_PROBLEM
                                srep = scan_skill(sdir)
                                pol_v_spec = evaluate_policy(
                                    policy,
                                    skill_dirs=[sdir],
                                    source_candidates=[spec.source, resolved.canonical_source],
                                    resolved_commit=resolved.resolved_commit,
                                    ref=pinned_ref,
                                    target_harnesses=skill_targets,
                                    sec_reports={sdir.name: srep},
                                )
                                if pol_v_spec:
                                    print(
                                        "error: sync blocked by project security policy: " + "; ".join(pol_v_spec),
                                        file=sys.stderr,
                                    )
                                    return EXIT_PROBLEM
                                if srep.has_structural_escape or (not srep.passed and not allow_risky):
                                    print(
                                        f"error: sync blocked by static security policy on {sdir.name!r}",
                                        file=sys.stderr,
                                    )
                                    return EXIT_PROBLEM
                                if srep.exceeds_risk_threshold(max_risk_score) and not allow_risky:
                                    print(
                                        f"error: sync blocked by configured security.max_risk_score ({max_risk_score}) "
                                        f"on {sdir.name!r} (risk_score {srep.risk_score}/100 > {max_risk_score})",
                                        file=sys.stderr,
                                    )
                                    return EXIT_PROBLEM
                                res = run_install(
                                    root,
                                    sdir,
                                    skill_targets,
                                    strategy=strategy,
                                    scope=args.scope,
                                    force=True,
                                    source=resolved.canonical_source,
                                    resolved_commit=resolved.resolved_commit,
                                    record_state=True,
                                )
                                synced_results.extend(res)
                        finally:
                            resolved.cleanup()
            finally:
                graph.cleanup()
        else:
            canonical_by_name: dict[str, Path] = {}
            if prefer_path:
                pref = Path(prefer_path).expanduser()
                if not pref.is_absolute():
                    pref = (root / pref).resolve()
                if (pref / "SKILL.md").is_file():
                    canonical_by_name[pref.name] = pref
                else:
                    for smd in discover(pref):
                        canonical_by_name[smd.parent.name] = smd.parent

            for sname, copies in sorted(diag.skill_copies.items()):
                if sname in canonical_by_name:
                    continue
                if len(copies) == 1 or sname not in diag.drifted:
                    canonical_by_name[sname] = copies[0]
                    continue
                ranked = sorted(copies, key=latest_tree_mtime_ns, reverse=True)
                if latest_tree_mtime_ns(ranked[0]) == latest_tree_mtime_ns(ranked[1]):
                    print(
                        f"error: drifted copies of {sname!r} have identical modification timestamps; "
                        "pass `--prefer <path>` to specify the authoritative copy.",
                        file=sys.stderr,
                    )
                    return EXIT_PROBLEM
                canonical_by_name[sname] = ranked[0]

            if not canonical_by_name:
                print(f"no skills or {MANIFEST_FILENAME} found under {root}")
                return EXIT_PROBLEM

            if dry_run:
                plan = plan_install(
                    root,
                    list(canonical_by_name.values()),
                    targets,
                    strategy=args.strategy,
                    scope=args.scope,
                    force=True,
                )
                if is_json:
                    print(
                        json.dumps(
                            {
                                "dry_run": True,
                                "skills": sorted(canonical_by_name),
                                "harnesses": targets,
                                "destinations": [str(d.resolved_dest) for d in plan.destinations],
                            },
                            indent=2,
                        )
                    )
                else:
                    print(f"dry-run: would synchronize {len(canonical_by_name)} skill(s) across {targets}")
                return EXIT_OK

            spec_by_name_fallback = {s.name: s for s in manifest.skills} if (manifest and manifest.skills) else {}
            records_fallback = load_state(root, scope=args.scope)
            for sname_fb, sdir in sorted(canonical_by_name.items()):
                if args.harness:
                    eff_targets = targets
                elif sname_fb in spec_by_name_fallback and spec_by_name_fallback[sname_fb].harnesses:
                    eff_targets = [harnesses.get(h).name for h in spec_by_name_fallback[sname_fb].harnesses]
                elif manifest and manifest.harnesses:
                    eff_targets = [harnesses.get(h).name for h in manifest.harnesses]
                elif sname_fb in records_fallback and records_fallback[sname_fb].harnesses:
                    eff_targets = [harnesses.get(h).name for h in records_fallback[sname_fb].harnesses]
                else:
                    eff_targets = targets
                res = run_install(
                    root,
                    sdir,
                    eff_targets,
                    strategy=args.strategy,
                    scope=args.scope,
                    force=True,
                    source="",
                    record_state=True,
                )
                synced_results.extend(res)

        if has_existing_lock or manifest is not None:
            cmd_lock(argparse.Namespace(path=str(root), quiet=is_json))

        record_audit_event(
            root,
            interface="cli",
            operation="sync",
            status="succeeded",
            source=str(root),
            destinations=[str(r.dest) for r in synced_results],
            harnesses=targets,
            overwrite=force_flag,
            force=force_flag,
            risk_accepted=allow_risky,
            scope=args.scope,
        )

    if is_json:
        print(
            json.dumps(
                {
                    "dry_run": False,
                    "synchronized": [
                        {"skill": r.skill, "harness": r.harness, "dest": str(r.dest), "action": r.action}
                        for r in synced_results
                    ],
                },
                indent=2,
            )
        )
        return EXIT_OK

    if not is_quiet(args):
        created_c = sum(1 for r in synced_results if r.action == "created")
        updated_c = sum(1 for r in synced_results if r.action == "updated")
        unchanged_c = sum(1 for r in synced_results if r.action == "unchanged")
        print(
            f"{action_symbol('synced')} Synchronized {len({r.skill for r in synced_results})} skill(s) "
            f"across {len(targets)} harness(es) (+{created_c} created, ~{updated_c} updated, ={unchanged_c} unchanged)"
        )
        for r in synced_results:
            if r.action != "unchanged" or is_verbose(args):
                print(f"  {action_symbol(r.action)} {r.action:9} {r.harness:16} {r.dest}")
    return EXIT_OK


def cmd_graph(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    manifest = load_manifest(root)
    graph = None
    try:
        graph = resolve_dependency_graph(root, manifest)
        if fmt_mode(args) == "json":
            payload = graph.to_dict()
            payload["valid"] = True
            print(json.dumps(payload, indent=2))
            return EXIT_OK

        print(f"skillporter {__version__} — resolved dependency graph ({len(graph.nodes)} node(s))\n")
        print(graph.render_tree())
        if graph.install_order:
            print(f"\nTopological install order: {' -> '.join(graph.install_order)}")
        return EXIT_OK
    except (DependencyCycleError, DependencyConflictError, DependencyError) as exc:
        if fmt_mode(args) == "json":
            print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROBLEM
    finally:
        if graph is not None:
            graph.cleanup()
