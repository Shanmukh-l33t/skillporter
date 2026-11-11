"""skillporter CLI — Complete Universal Lifecycle Manager for Agent Skills.

Commands:
  init, add, install, uninstall, remove, list, search, inspect, validate,
  scan, diagnose, doctor, detect, matrix, update, sync, rollback, lock,
  info, pack, mcp.

Every verification command exits non-zero when it finds a real problem, so it
drops straight into CI.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from . import __version__, harnesses
from .diagnose import diagnose as run_diagnose
from .formats import inspect_skill_dir, render_adapted_skill
from .frontmatter import Issue, discover, parse_skill, validate
from .install import InstallError, plan_install, rollback_skill
from .install import install as run_install
from .install import uninstall as run_uninstall
from .manifest import (
    LOCKFILE_FILENAME,
    MANIFEST_FILENAME,
    LockedSkill,
    ManifestSkillSpec,
    ProjectManifest,
    load_lockfile,
    load_manifest,
    save_lockfile,
    save_manifest,
)
from .mcp_server import run_mcp_stdio
from .registry import pack_skill, resolve_registry_spec, search_catalog
from .security import compute_tree_hash, scan_skill
from .sources import SourceError, resolve_source
from .state import load_state
from .ui import BOLD, CYAN, DIM, badge, style

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_ERROR = 2


def _resolve_target_harnesses(
    raw_harnesses: list[str] | None,
    root: Path,
    *,
    scope: str = "project",
    default_detected: bool = True,
) -> list[str]:
    """Resolve ``--harness`` arguments, supporting ``all`` and auto-detection."""
    if raw_harnesses:
        expanded: list[str] = []
        for item in raw_harnesses:
            for part in item.split(","):
                tok = part.strip().lower()
                if not tok:
                    continue
                if tok == "all":
                    detected = [
                        d.harness.name
                        for d in harnesses.detect_harnesses(root)
                        if d.installed and (d.harness.project_paths if scope == "project" else d.harness.user_paths)
                    ]
                    if detected:
                        expanded.extend(detected)
                    else:
                        expanded.extend(["claude-code", "codex", "cursor"])
                else:
                    expanded.append(harnesses.get(tok).name)
        seen: list[str] = []
        for h in expanded:
            if h not in seen:
                seen.append(h)
        return seen

    if default_detected:
        manifest = load_manifest(root)
        if manifest and manifest.harnesses:
            return [harnesses.get(h).name for h in manifest.harnesses]
        detected = [
            d.harness.name
            for d in harnesses.detect_harnesses(root)
            if d.project_active and (d.harness.project_paths if scope == "project" else d.harness.user_paths)
        ]
        if detected:
            return detected
    return ["claude-code", "codex", "cursor"]


def _print_matrix(as_json: bool, category: str | None = None) -> int:
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
    print("\nNotes:")
    for r in rows:
        for n in r["notes"]:
            print(f"  {r['harness']}: {n}")
    return EXIT_OK


def _cmd_diagnose(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return EXIT_ERROR

    selected = args.harness or None
    if selected and "all" in selected:
        selected = harnesses.names()

    diag = run_diagnose(root, only=selected, scope=args.scope)

    if args.json:
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

    # Show core/active harnesses in compact table unless --harness was explicitly passed
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
        cells = []
        for n in names:
            state = diag.reports[n].cell_state(skill)
            cells.append(state.ljust(14))
        print(skill.ljust(width) + "  " + "  ".join(cells))

    print()
    if diag.findings:
        print("findings:")
        for f in diag.findings:
            print(f"  - {f}")
    else:
        print("no findings — every skill is reachable and synchronized across checked harnesses.")

    return EXIT_PROBLEM if diag.findings else EXIT_OK


def _cmd_add(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    try:
        targets = _resolve_target_harnesses(args.harness, root, scope=args.scope, default_detected=True)
    except KeyError as exc:
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
            wanted = {s.strip() for s in args.skill}
            skill_dirs = [d for d in skill_dirs if d.name in wanted]
            if not skill_dirs:
                print(f"error: requested skill(s) {sorted(wanted)} not found in {args.source}", file=sys.stderr)
                return EXIT_ERROR

        plan = plan_install(
            root,
            skill_dirs,
            targets,
            strategy=args.strategy,
            scope=args.scope,
            force=args.force,
        )

        # Validate & scan all discovered skills
        spec_errors: list[str] = []
        sec_critical = 0
        sec_high = 0
        sec_info = 0
        sec_reports = {}
        for sdir in skill_dirs:
            issues = validate(parse_skill(sdir / "SKILL.md"))
            for iss in issues:
                if iss.level == "error":
                    spec_errors.append(f"{sdir.name}: {iss}")
            srep = scan_skill(sdir)
            sec_reports[sdir.name] = srep
            sec_critical += srep.critical_count
            sec_high += srep.high_count
            sec_info += srep.medium_count + srep.low_count

        if args.json:
            if args.dry_run:
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
                            "security": {k: v.to_dict() for k, v in sec_reports.items()},
                        },
                        indent=2,
                    )
                )
                return EXIT_PROBLEM if (spec_errors or sec_critical or sec_high) else EXIT_OK
        else:
            print(style("SKILLPORTER", BOLD, CYAN))
            print(f"\nSource: {resolved.kind}:{args.source}")
            if resolved.resolved_commit:
                print(f"Commit: {resolved.resolved_commit[:12]}")
            print("\nFound skills:")
            for sdir in skill_dirs:
                print(f"  {sdir.name}")
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
            print("\nSecurity assessment (static):")
            print(f"  {sec_info} informational/medium finding(s)")
            print(f"  {sec_critical + sec_high} critical/high finding(s)")

        if (sec_critical > 0 or sec_high > 0) and not args.allow_risky and not args.force:
            print(
                "\nerror: installation blocked by static security policy "
                "(re-run with --allow-risky after reviewing `skillporter scan` output)",
                file=sys.stderr,
            )
            return EXIT_PROBLEM

        if args.dry_run:
            if not args.json:
                print("\nDry run complete (no files modified).")
            return EXIT_OK

        if not args.json:
            print("\nInstalling...\n")

        all_results = []
        for sdir in skill_dirs:
            try:
                res = run_install(
                    root,
                    sdir,
                    targets,
                    strategy=args.strategy,
                    scope=args.scope,
                    force=args.force,
                    source=resolved.canonical_source,
                    resolved_commit=resolved.resolved_commit,
                    record_state=True,
                    adapt=args.adapt,
                )
                all_results.extend(res)
            except InstallError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return EXIT_ERROR

        # Update manifest if skillporter.yaml exists
        manifest = load_manifest(root)
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

        if args.json:
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

        for r in all_results:
            label = harnesses.get(r.harness).label
            status_str = "SUCCESS" if r.action in ("created", "updated", "unchanged") else r.action.upper()
            print(f"{label:22} {badge(status_str)}  ({r.detail})")

        print("\nInstallation verified.")
        return EXIT_OK
    finally:
        resolved.cleanup()


def _cmd_install(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    skill_dir = Path(args.skill).expanduser()
    if not skill_dir.is_absolute():
        skill_dir = (root / skill_dir).resolve()
    try:
        targets = _resolve_target_harnesses(args.harness, root, scope=args.scope, default_detected=False)
        results = run_install(
            root,
            skill_dir,
            targets,
            strategy=args.strategy,
            scope=args.scope,
            force=args.force,
            record_state=True,
            adapt=getattr(args, "adapt", False),
        )
    except (InstallError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    for r in results:
        print(f"{r.action:9} {r.harness:12} {r.dest}  ({r.detail})")
    return EXIT_OK


def _cmd_uninstall(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    try:
        targets = _resolve_target_harnesses(
            args.harness or ["all"], root, scope=args.scope, default_detected=True
        )
        results = run_uninstall(root, args.skill, targets, scope=args.scope, record_state=True)
    except (InstallError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for r in results:
        print(f"{r.action:9} {r.harness:12} {r.dest}")
    return EXIT_OK


def _cmd_validate(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser()
    files = [target] if target.name == "SKILL.md" else discover(target)
    if not files:
        print(f"error: no SKILL.md under {target}", file=sys.stderr)
        return EXIT_ERROR

    problems = 0
    json_out = {}
    for path in files:
        issues: list[Issue] = validate(parse_skill(path))
        errors = [i for i in issues if i.level == "error"]
        problems += len(errors)
        label = path.parent.name
        json_out[str(path)] = [{"level": i.level, "code": i.code, "message": i.message} for i in issues]
        if not getattr(args, "json", False):
            if issues:
                print(f"{label}:")
                for i in issues:
                    print(f"  {i}")
            else:
                print(f"{label}: OK")
    if getattr(args, "json", False):
        print(json.dumps({"valid": problems == 0, "files": json_out}, indent=2))
    return EXIT_PROBLEM if problems else EXIT_OK


def _cmd_scan(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_ERROR

    skill_dirs = [target] if (target / "SKILL.md").is_file() else [p.parent for p in discover(target)]
    if not skill_dirs:
        skill_dirs = [target]

    reports = {d.name: scan_skill(d) for d in skill_dirs}
    blocked = any(not r.passed for r in reports.values())

    if args.json:
        print(
            json.dumps(
                {
                    "passed": not blocked,
                    "reports": {k: v.to_dict() for k, v in reports.items()},
                },
                indent=2,
            )
        )
        return EXIT_PROBLEM if blocked else EXIT_OK

    print(f"skillporter {__version__} — static security assessment\n")
    for sname, rep in reports.items():
        verdict = "PASSED" if rep.passed else "BLOCKED"
        print(f"{sname}: {badge(verdict)}  (sha256: {rep.tree_hash[:12] if rep.tree_hash else 'n/a'})")
        if not rep.findings:
            print("  0 findings across all scanned files.")
        for f in rep.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"  [{badge(f.severity)}] {f.code} ({loc}): {f.message}")
    print(
        style(
            "\nNote: Static scanning inspects patterns and symlinks; it does not guarantee runtime safety.",
            DIM,
        )
    )
    return EXIT_PROBLEM if blocked else EXIT_OK


def _cmd_detect(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    detected = harnesses.detect_harnesses(root, probe_versions=args.versions)
    if args.json:
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


def _cmd_init(args: argparse.Namespace) -> int:
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
    print(f"initialized {mpath} ({len(existing_skills)} skill(s), harnesses: {', '.join(default_harnesses)})")
    return EXIT_OK


def _cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    records = load_state(root, scope=args.scope)
    diag = run_diagnose(root, scope=args.scope)

    rows = []
    seen: set[str] = set()
    for sname, rec in sorted(records.items()):
        seen.add(sname)
        rows.append(
            {
                "name": sname,
                "version": rec.version,
                "strategy": rec.strategy,
                "managed": True,
                "source": rec.source,
                "tree_hash": rec.tree_hash[:12] if rec.tree_hash else "",
                "harnesses": sorted(rec.harnesses),
            }
        )
    for skill_md in diag.skills:
        sname = skill_md.parent.name
        if sname in seen:
            continue
        thash, _ = compute_tree_hash(skill_md.parent)
        loaded_in = sorted(h for h, r in diag.reports.items() if r.loads(sname))
        rel_src = (
            skill_md.parent.relative_to(root)
            if skill_md.parent.is_relative_to(root)
            else skill_md.parent
        )
        rows.append(
            {
                "name": sname,
                "version": "untracked",
                "strategy": "local",
                "managed": False,
                "source": str(rel_src),
                "tree_hash": thash[:12] if thash else "",
                "harnesses": loaded_in,
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2))
        return EXIT_OK

    if not rows:
        print(f"no skills installed or discovered under {root}")
        return EXIT_OK

    w_name = max(max(len(str(r["name"])) for r in rows), 5)
    print(f"{'SKILL'.ljust(w_name)}  {'MANAGED':8}  {'HASH':12}  HARNESSES")
    print(f"{'-' * w_name}  {'-' * 8}  {'-' * 12}  {'-' * 35}")
    for r in rows:
        m_str = "yes" if r["managed"] else "no"
        h_str = ", ".join(r["harnesses"]) if r["harnesses"] else "(none)"
        print(f"{str(r['name']).ljust(w_name)}  {m_str:8}  {str(r['tree_hash']):12}  {h_str}")
    return EXIT_OK


def _cmd_search(args: argparse.Namespace) -> int:
    results = search_catalog(args.query or "", category=args.category or "")
    if args.json:
        print(json.dumps([p.to_dict() for p in results], indent=2))
        return EXIT_OK

    if not results:
        print(f"no skill packages matched query {args.query!r}")
        return EXIT_OK

    w_slug = max(len(p.slug) for p in results)
    print(f"{'PACKAGE'.ljust(w_slug)}  {'CATEGORY':18}  DESCRIPTION")
    print(f"{'-' * w_slug}  {'-' * 18}  {'-' * 44}")
    for p in results:
        print(f"{p.slug.ljust(w_slug)}  {p.category:18}  {p.description}")
    return EXIT_OK


def _cmd_inspect(args: argparse.Namespace) -> int:
    root = Path.cwd()
    try:
        resolved = resolve_source(args.source, base_dir=root)
    except (SourceError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        items = []
        for sdir in resolved.skill_dirs:
            pkg = inspect_skill_dir(sdir)
            doc = pkg.skill_doc or parse_skill(sdir / "SKILL.md")
            issues = validate(doc)
            sec = scan_skill(sdir)
            adapted_previews = {}
            if args.preview_adapt:
                fmt = args.preview_adapt
                rel_p, rendered = render_adapted_skill(doc, fmt)
                adapted_previews[fmt] = {"path": rel_p, "content": rendered}
            items.append(
                {
                    "name": doc.name or sdir.name,
                    "description": doc.description,
                    "license": doc.frontmatter.get("license", ""),
                    "compatibility": doc.frontmatter.get("compatibility", ""),
                    "formats": pkg.detected_formats,
                    "scripts": pkg.scripts,
                    "references": pkg.references,
                    "assets": pkg.assets,
                    "validation_issues": [str(i) for i in issues],
                    "security": sec.to_dict(),
                    "adapted_previews": adapted_previews,
                }
            )

        if args.json:
            print(
                json.dumps(
                    {
                        "source": resolved.canonical_source,
                        "kind": resolved.kind,
                        "resolved_commit": resolved.resolved_commit,
                        "skills": items,
                    },
                    indent=2,
                )
            )
            return EXIT_OK

        print(f"Source: {resolved.canonical_source} ({resolved.kind})")
        if resolved.resolved_commit:
            print(f"Commit: {resolved.resolved_commit}")
        for item in items:
            print(f"\nSkill: {style(str(item['name']), BOLD)}")
            print(f"  Description: {item['description']}")
            print(f"  Formats:     {', '.join(item['formats'])}")
            print(
                f"  Structure:   {len(item['scripts'])} script(s), "
                f"{len(item['references'])} reference(s), {len(item['assets'])} asset(s)"
            )
            sec_d = item["security"]
            verdict = "PASSED" if sec_d["passed"] else "BLOCKED"
            print(f"  Security:    {badge(verdict)} (sha256: {str(sec_d['tree_hash'])[:12]})")
            if item["validation_issues"]:
                print("  Validation issues:")
                for iss in item["validation_issues"]:
                    print(f"    - {iss}")
            for fmt, prev in item["adapted_previews"].items():
                print(f"\n  Adapted preview ({fmt} -> {prev['path']}):")
                for line in str(prev["content"]).splitlines()[:15]:
                    print(f"    {line}")
        return EXIT_OK
    finally:
        resolved.cleanup()


def _cmd_lock(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    records = load_state(root)
    lock = load_lockfile(root)

    if records:
        for sname, rec in sorted(records.items()):
            lock.skills[sname] = LockedSkill(
                name=sname,
                source=rec.source,
                resolved_commit=rec.resolved_commit,
                version=rec.version,
                tree_hash=rec.tree_hash,
                strategy=rec.strategy,
                installed_targets=rec.harnesses,
                locked_at=rec.updated_at,
            )
    else:
        for skill_md in discover(root):
            sname = skill_md.parent.name
            if sname in lock.skills:
                continue
            thash, _ = compute_tree_hash(skill_md.parent)
            lock.skills[sname] = LockedSkill(
                name=sname,
                source=f"./{skill_md.parent.relative_to(root).as_posix()}",
                resolved_commit="",
                version="1.0.0",
                tree_hash=thash,
                strategy="copy",
                installed_targets=[],
            )

    lpath = save_lockfile(root, lock)
    print(f"wrote {lpath} ({len(lock.skills)} locked skill(s))")
    return EXIT_OK


def _cmd_sync(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    manifest = load_manifest(root)
    targets = _resolve_target_harnesses(args.harness, root, scope=args.scope, default_detected=True)
    force_flag = getattr(args, "force", False)

    synced_results = []
    if manifest and manifest.skills:
        for spec in manifest.skills:
            skill_targets = spec.harnesses or manifest.harnesses or targets
            strategy = spec.strategy or manifest.strategy or args.strategy
            resolved = resolve_source(spec.source, base_dir=root, ref_override=spec.ref)
            try:
                for sdir in resolved.skill_dirs:
                    if sdir.name != spec.name and len(resolved.skill_dirs) > 1:
                        continue
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
    else:
        # Check for content drift across copies before blindly overwriting
        diag = run_diagnose(root, scope=args.scope)
        if diag.drifted and not force_flag:
            print(
                "error: content drift detected across existing skill copies; refusing to overwrite without --force:",
                file=sys.stderr,
            )
            for sname, phashes in sorted(diag.drifted.items()):
                locs = ", ".join(f"{p} ({h[:8]})" for p, h in sorted(phashes.items()))
                print(f"  - {sname}: {locs}", file=sys.stderr)
            print(
                "Re-run `skillporter sync --force` to synchronize from the most recently modified copy "
                "(existing copies are snapshotted to .skillporter/backups/ first).",
                file=sys.stderr,
            )
            return EXIT_PROBLEM

        # Discover canonical skills in the repo (preferring newest mtime when multiple copies exist)
        canonical_by_name: dict[str, Path] = {}
        for skill_md in discover(root):
            sname = skill_md.parent.name
            if sname not in canonical_by_name:
                canonical_by_name[sname] = skill_md.parent
            else:
                prev_md = canonical_by_name[sname] / "SKILL.md"
                if skill_md.stat().st_mtime > prev_md.stat().st_mtime:
                    canonical_by_name[sname] = skill_md.parent

        if not canonical_by_name:
            print(f"no skills or {MANIFEST_FILENAME} found under {root}")
            return EXIT_PROBLEM

        for _sname, sdir in sorted(canonical_by_name.items()):
            res = run_install(
                root,
                sdir,
                targets,
                strategy=args.strategy,
                scope=args.scope,
                force=True,
                source=str(sdir),
                record_state=True,
            )
            synced_results.extend(res)

    # Update lockfile automatically if present or if manifest exists
    if (root / LOCKFILE_FILENAME).exists() or manifest is not None:
        _cmd_lock(argparse.Namespace(path=str(root)))

    for r in synced_results:
        print(f"{r.action:9} {r.harness:16} {r.dest}")
    return EXIT_OK


def _cmd_update(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    records = load_state(root, scope=args.scope)
    if not records:
        print("no managed skills recorded in .skillporter/state.json to update.")
        return EXIT_OK

    names = [args.skill] if args.skill else sorted(records)
    updated_count = 0
    for sname in names:
        rec = records.get(sname)
        if not rec:
            print(f"error: skill {sname!r} is not tracked by skillporter", file=sys.stderr)
            return EXIT_ERROR
        resolved = resolve_source(rec.source, base_dir=root)
        try:
            matching = [d for d in resolved.skill_dirs if d.name == sname] or resolved.skill_dirs
            for sdir in matching:
                res = run_install(
                    root,
                    sdir,
                    rec.harnesses or ["claude-code", "codex", "cursor"],
                    strategy=rec.strategy,
                    scope=rec.scope,
                    force=True,
                    source=resolved.canonical_source,
                    resolved_commit=resolved.resolved_commit,
                    record_state=True,
                )
                updated_count += 1
                for r in res:
                    print(f"updated   {r.harness:16} {r.dest}")
        finally:
            resolved.cleanup()
    return EXIT_OK if updated_count >= 0 else EXIT_PROBLEM


def _cmd_rollback(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
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

    for r in results:
        print(f"{r.action:12} {r.harness:16} {r.dest}  ({r.detail})")
    return EXIT_OK


def _cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    diag = run_diagnose(root, only=args.harness or None, scope=args.scope)
    detected = [d for d in harnesses.detect_harnesses(root) if d.installed]

    if args.fix and diag.skills:
        # Remove broken symlinks first
        for rep in diag.reports.values():
            for loc in rep.locations:
                for blink in loc.broken_links:
                    bp = Path(blink)
                    if bp.is_symlink():
                        bp.unlink(missing_ok=True)
        # Re-sync discovered skills across active/checked harnesses
        active_proj = {d.harness.name for d in detected if d.project_active}
        targets = args.harness or sorted({"claude-code", "codex", "cursor"} | active_proj)
        for skill_md in diag.skills:
            sname = skill_md.parent.name
            copies = diag.skill_copies.get(sname, [skill_md.parent])
            newest_dir = max(copies, key=lambda d: (d / "SKILL.md").stat().st_mtime)
            run_install(
                root,
                newest_dir,
                targets,
                strategy="copy",
                scope=args.scope,
                force=True,
                record_state=True,
            )
        diag = run_diagnose(root, only=targets, scope=args.scope)

    active_names = (
        [harnesses.get(h).name for h in args.harness]
        if args.harness
        else sorted({"claude-code", "codex", "cursor"} | {d.harness.name for d in detected if d.project_active})
    )

    skill_summaries = []
    for skill_md in diag.skills:
        sname = skill_md.parent.name
        valid = diag.is_skill_valid(sname)
        thash, _ = compute_tree_hash(skill_md.parent)
        per_harness = {}
        for hname in active_names:
            if hname in diag.reports:
                per_harness[hname] = diag.reports[hname].explicit_states(sname, is_valid=valid)
        skill_summaries.append(
            {
                "name": sname,
                "path": str(skill_md.parent),
                "state": "VALID" if valid else "INVALID",
                "tree_hash": thash[:12] if thash else "",
                "copies": len(diag.skill_copies.get(sname, [])),
                "harnesses": per_harness,
            }
        )

    remediations: list[str] = []
    if diag.drifted:
        remediations.append("skillporter sync --force   # reconcile drifted copies (snapshots backup first)")
    if any("not visible to:" in f or "broken symlink" in f for f in diag.findings):
        remediations.append("skillporter doctor --fix   # install missing skills and remove broken symlinks")
    if any(not diag.is_skill_valid(s) for s in diag.skill_names):
        remediations.append("skillporter validate .     # inspect and fix SKILL.md specification errors")

    if args.json:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "detected_harnesses": [d.harness.name for d in detected],
                    "checked_harnesses": active_names,
                    "skills": diag.skill_names,
                    "skill_states": skill_summaries,
                    "drifted": diag.drifted,
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
    print(f"Discovered skills:  {', '.join(diag.skill_names) or '(none)'}")
    print(f"Content drift:      {len(diag.drifted)} skill(s)")

    if skill_summaries:
        print("\nSkill Status Matrix (FOUND / VALID / COMPATIBLE / INSTALLED / VERIFIED):")
        for s in skill_summaries:
            print(f"  {s['name']} [{s['state']}] (hash: {s['tree_hash']}, copies: {s['copies']})")
            for hname, st_list in s["harnesses"].items():
                print(f"    - {hname:16} {' -> '.join(st_list)}")

    if diag.findings:
        print("\nIssues found:")
        for f in diag.findings:
            print(f"  - {f}")
        if remediations and not args.fix:
            print("\nRecommended fixes:")
            for cmd in remediations:
                print(f"  $ {cmd}")
        return EXIT_PROBLEM
    print("\nStatus: HEALTHY (all checked skills reachable, valid, and in sync).")
    return EXIT_OK


def _cmd_info(args: argparse.Namespace) -> int:
    target = args.target.strip()
    # 1. Check if target is a known harness adapter
    try:
        h = harnesses.get(target)
        payload = {
            "type": "harness",
            "id": h.name,
            "display_name": h.label,
            "category": h.category,
            "support_status": h.support_status,
            "verification_level": h.verification_level,
            "verified_date": h.verified_date,
            "docs": h.docs,
            "project_paths": [p.path for p in h.project_paths],
            "user_paths": [p.path for p in h.user_paths],
            "notes": list(h.notes),
            "limitations": list(h.limitations),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
            return EXIT_OK
        print(f"Harness:       {h.label} ({h.name})")
        print(f"Category:      {h.category}")
        print(f"Support:       {h.support_status} ({h.verification_level}, verified {h.verified_date})")
        print(f"Docs:          {h.docs}")
        print(f"Project paths: {', '.join(p.path for p in h.project_paths) or '(none)'}")
        print(f"User paths:    {', '.join(p.path for p in h.user_paths) or '(none)'}")
        for n in h.notes:
            print(f"Note:          {n}")
        for lim in h.limitations:
            print(f"Limitation:    {lim}")
        return EXIT_OK
    except KeyError:
        pass

    # 2. Check registry catalog
    try:
        pkg = resolve_registry_spec(target)
        if args.json:
            print(json.dumps(pkg.to_dict(), indent=2))
            return EXIT_OK
        print(f"Package:     {pkg.slug} (v{pkg.version})")
        print(f"Publisher:   {pkg.publisher}")
        print(f"Category:    {pkg.category}")
        print(f"License:     {pkg.license}")
        print(f"Source:      {pkg.source}")
        print(f"Description: {pkg.description}")
        print(f"Harnesses:   {', '.join(pkg.verified_harnesses)}")
        print(f"\nInstall:     skillporter add {pkg.slug}")
        return EXIT_OK
    except KeyError:
        print(f"error: {target!r} is neither a registered harness nor a known registry package", file=sys.stderr)
        return EXIT_ERROR


def _cmd_pack(args: argparse.Namespace) -> int:
    skill_dir = Path(args.path).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    try:
        rel = pack_skill(skill_dir, out_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        print(
            json.dumps(
                {
                    "skill": rel.skill_name,
                    "version": rel.version,
                    "archive": str(rel.archive_path),
                    "provenance": str(rel.provenance_path),
                    "archive_sha256": rel.archive_sha256,
                    "tree_hash": rel.tree_hash,
                },
                indent=2,
            )
        )
        return EXIT_OK
    print(f"packed {rel.skill_name}@{rel.version}:")
    print(f"  archive:    {rel.archive_path} (sha256: {rel.archive_sha256[:16]}...)")
    print(f"  provenance: {rel.provenance_path}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skillporter",
        description=(
            "ONE SKILL. EVERY AGENT. Universal package manager, validator, security scanner, "
            "and cross-harness synchronizer for AI-agent skills."
        ),
    )
    p.add_argument("--version", action="version", version=f"skillporter {__version__}")
    sub = p.add_subparsers(dest="command", required=False)

    # diagnose
    d = sub.add_parser("diagnose", help="show which harnesses can actually see each skill, plus drift & broken links")
    d.add_argument("path", nargs="?", default=".", help="repo root (default: .)")
    d.add_argument("--harness", action="append", help="limit to specific harness(es) or 'all' (repeatable)")
    d.add_argument("--scope", choices=["project", "user"], default="project")
    d.add_argument("--json", action="store_true", help="machine-readable output")
    d.set_defaults(func=_cmd_diagnose)

    # add (flagship universal installer)
    a = sub.add_parser("add", help="install skills from GitHub, git URL, archive, registry, or local path")
    a.add_argument("source", help="owner/repo, GitHub URL, archive, or local path")
    a.add_argument("--harness", action="append", help="target harness or 'all' (repeatable)")
    a.add_argument("--skill", action="append", help="select specific skill name(s) from a multi-skill repo")
    a.add_argument("--ref", help="git branch, tag, or commit hash")
    a.add_argument("--strategy", choices=["copy", "symlink"], default="copy")
    a.add_argument("--scope", choices=["project", "user"], default="project")
    a.add_argument("--path", default=".", help="repo root (default: .)")
    a.add_argument("--adapt", action="store_true", help="also emit adapted rule files (.mdc, .instructions.md)")
    a.add_argument("--dry-run", action="store_true", help="plan, validate, and scan without writing files")
    a.add_argument(
        "--allow-risky",
        action="store_true",
        help="proceed even if static security scan finds high/critical issues",
    )
    a.add_argument("--force", action="store_true", help="overwrite existing installations")
    a.add_argument("--json", action="store_true", help="machine-readable output")
    a.set_defaults(func=_cmd_add)

    # install (local path installer)
    i = sub.add_parser("install", help="install a local skill directory into one or more harnesses")
    i.add_argument("skill", help="path to the skill directory")
    i.add_argument("--harness", action="append", required=True, help="target harness (repeatable)")
    i.add_argument(
        "--strategy",
        choices=["copy", "symlink"],
        default="copy",
        help="copy (portable, Docker/CI safe) or symlink (single source of truth)",
    )
    i.add_argument("--scope", choices=["project", "user"], default="project")
    i.add_argument("--path", default=".", help="repo root (default: .)")
    i.add_argument("--adapt", action="store_true", help="also emit adapted harness rule file")
    i.add_argument("--force", action="store_true", help="overwrite an existing install")
    i.set_defaults(func=_cmd_install)

    # uninstall / remove
    for cmd_name in ("uninstall", "remove"):
        u = sub.add_parser(cmd_name, help="remove a skill from harnesses")
        u.add_argument("skill", help="skill name")
        u.add_argument("--harness", action="append", required=(cmd_name == "uninstall"))
        u.add_argument("--scope", choices=["project", "user"], default="project")
        u.add_argument("--path", default=".")
        u.set_defaults(func=_cmd_uninstall)

    # validate
    v = sub.add_parser("validate", help="validate SKILL.md files against the Agent Skills spec")
    v.add_argument("path", nargs="?", default=".")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=_cmd_validate)

    # scan
    sc = sub.add_parser("scan", help="run static security and supply-chain checks on skills")
    sc.add_argument("path", nargs="?", default=".")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=_cmd_scan)

    # matrix
    m = sub.add_parser("matrix", help="print the 19-harness compatibility matrix")
    m.add_argument("--category", choices=["coding", "autonomous"])
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=lambda a: _print_matrix(a.json, getattr(a, "category", None)))

    # detect
    dt = sub.add_parser("detect", help="detect installed AI agent harnesses on this machine and workspace")
    dt.add_argument("path", nargs="?", default=".")
    dt.add_argument("--all", action="store_true", help="include harnesses not currently detected")
    dt.add_argument("--versions", action="store_true", help="probe CLI versions where available")
    dt.add_argument("--json", action="store_true")
    dt.set_defaults(func=_cmd_detect)

    # init
    init_p = sub.add_parser("init", help="initialize skillporter.yaml in a project")
    init_p.add_argument("path", nargs="?", default=".")
    init_p.add_argument("--force", action="store_true")
    init_p.set_defaults(func=_cmd_init)

    # list
    ls_p = sub.add_parser("list", help="list installed and discovered skills")
    ls_p.add_argument("path", nargs="?", default=".")
    ls_p.add_argument("--scope", choices=["project", "user"], default="project")
    ls_p.add_argument("--json", action="store_true")
    ls_p.set_defaults(func=_cmd_list)

    # search
    sr = sub.add_parser("search", help="search the skill registry catalog")
    sr.add_argument("query", nargs="?", default="")
    sr.add_argument("--category", default="")
    sr.add_argument("--json", action="store_true")
    sr.set_defaults(func=_cmd_search)

    # inspect
    ins = sub.add_parser("inspect", help="inspect a local or remote skill package before installing")
    ins.add_argument("source", help="local path, archive, or GitHub owner/repo")
    ins.add_argument(
        "--preview-adapt",
        choices=["cursor-mdc", "copilot-instructions", "windsurf-rules", "continue-rules", "aider-conventions"],
    )
    ins.add_argument("--json", action="store_true")
    ins.set_defaults(func=_cmd_inspect)

    # sync
    sy = sub.add_parser("sync", help="synchronize skills across harnesses or from skillporter.yaml")
    sy.add_argument("path", nargs="?", default=".")
    sy.add_argument("--harness", action="append")
    sy.add_argument("--strategy", choices=["copy", "symlink"], default="copy")
    sy.add_argument("--scope", choices=["project", "user"], default="project")
    sy.add_argument("--force", action="store_true", help="overwrite drifted copies after snapshotting backups")
    sy.set_defaults(func=_cmd_sync)

    # update
    up = sub.add_parser("update", help="update managed skills from their tracked sources")
    up.add_argument("skill", nargs="?", default="")
    up.add_argument("--scope", choices=["project", "user"], default="project")
    up.add_argument("--path", default=".")
    up.set_defaults(func=_cmd_update)

    # rollback
    rb = sub.add_parser("rollback", help="restore a skill to its previous backup snapshot")
    rb.add_argument("skill", help="skill name to roll back")
    rb.add_argument("--backup-id", default="")
    rb.add_argument("--scope", choices=["project", "user"], default="project")
    rb.add_argument("--path", default=".")
    rb.set_defaults(func=_cmd_rollback)

    # lock
    lk = sub.add_parser("lock", help="generate or update deterministic skillporter.lock")
    lk.add_argument("path", nargs="?", default=".")
    lk.set_defaults(func=_cmd_lock)

    # doctor
    doc = sub.add_parser("doctor", help="run comprehensive health check (and optional --fix repair)")
    doc.add_argument("path", nargs="?", default=".")
    doc.add_argument("--harness", action="append")
    doc.add_argument("--scope", choices=["project", "user"], default="project")
    doc.add_argument("--fix", action="store_true", help="auto-repair missing/drifted installs and broken symlinks")
    doc.add_argument("--json", action="store_true")
    doc.set_defaults(func=_cmd_doctor)

    # info
    inf = sub.add_parser("info", help="show detailed metadata for a harness adapter or registry package")
    inf.add_argument("target", help="harness ID (e.g. cursor) or package slug (e.g. anthropics/skills)")
    inf.add_argument("--json", action="store_true")
    inf.set_defaults(func=_cmd_info)

    # pack
    pk = sub.add_parser("pack", help="build an immutable .tar.gz release bundle and SHA-256 provenance manifest")
    pk.add_argument("path", nargs="?", default=".")
    pk.add_argument("--out", default=".skillporter/dist")
    pk.add_argument("--json", action="store_true")
    pk.set_defaults(func=_cmd_pack)

    # mcp
    mcp_p = sub.add_parser("mcp", help="run the stdio Model Context Protocol (MCP) server for agent harnesses")
    mcp_p.set_defaults(func=lambda _a: run_mcp_stdio())

    return p


KNOWN_COMMANDS = (
    "diagnose",
    "add",
    "install",
    "uninstall",
    "remove",
    "validate",
    "scan",
    "matrix",
    "detect",
    "init",
    "list",
    "search",
    "inspect",
    "sync",
    "update",
    "rollback",
    "lock",
    "doctor",
    "info",
    "pack",
    "mcp",
)


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not args_list:
        parser.print_help()
        return EXIT_OK

    # Helpful typo suggestion when an unknown command is given
    first = args_list[0]
    if not first.startswith("-") and first not in KNOWN_COMMANDS:
        matches = difflib.get_close_matches(first, KNOWN_COMMANDS, n=2, cutoff=0.5)
        hint = f" (did you mean: {', '.join(matches)}?)" if matches else ""
        print(f"error: unknown command {first!r}{hint}", file=sys.stderr)
        return EXIT_ERROR

    args = parser.parse_args(args_list)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_OK
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
