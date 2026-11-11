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
import contextlib
import difflib
import json
import sys
from pathlib import Path

from . import __version__, harnesses
from .ci_report import check_lockfile_staleness, generate_ci_report, post_github_pr_comment
from .demo import run_demo
from .diagnose import diagnose as run_diagnose
from .explain import explain_finding
from .formats import inspect_skill_dir, render_adapted_skill
from .frontmatter import Issue, discover, parse_skill, validate
from .install import InstallError, install_many, plan_install, rollback_skill
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
from .registry import pack_skill, publish_skill, resolve_registry_spec, search_catalog
from .resolver import DependencyConflictError, DependencyCycleError, DependencyError, resolve_dependency_graph
from .sandbox import run_sandbox
from .security import CATEGORY_KEYS, SCANNER_ENGINE_VERSION, compute_tree_hash, scan_skill, to_sarif
from .sources import SourceError, resolve_source
from .state import load_state
from .telemetry import record_telemetry_event
from .ui import BOLD, CYAN, DIM, badge, style

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_ERROR = 2


def _fmt_mode(args: argparse.Namespace) -> str:
    fmt = str(getattr(args, "format", "") or "").strip().lower()
    if fmt in ("json", "sarif", "text", "markdown"):
        return fmt
    if getattr(args, "json", False):
        return "json"
    return "text"


def _resolve_target_harnesses(
    raw_harnesses: list[str] | None,
    root: Path,
    *,
    scope: str = "project",
    default_detected: bool = True,
) -> list[str]:
    """Resolve ``--harness`` arguments, supporting ``all``, ``detected``, and auto-detection."""
    if raw_harnesses:
        expanded: list[str] = []
        for item in raw_harnesses:
            for part in item.split(","):
                tok = part.strip().lower()
                if not tok:
                    continue
                if tok == "all":
                    all_scoped = [
                        n
                        for n in harnesses.names()
                        if (harnesses.get(n).project_paths if scope == "project" else harnesses.get(n).user_paths)
                    ]
                    expanded.extend(all_scoped)
                elif tok == "detected":
                    detected = [
                        d.harness.name
                        for d in harnesses.detect_harnesses(root)
                        if d.installed and (d.harness.project_paths if scope == "project" else d.harness.user_paths)
                    ]
                    expanded.extend(detected if detected else ["claude-code", "codex", "cursor"])
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
    fmt = _fmt_mode(args)

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
        )

        # Validate & scan all discovered skills
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

        is_json = _fmt_mode(args) == "json"
        if is_json:
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
                            "max_risk_score": max_risk_score,
                            "risk_threshold_exceeded": risk_threshold_exceeded,
                            "security": {k: v.to_dict() for k, v in sec_reports.items()},
                        },
                        indent=2,
                    )
                )
                return EXIT_PROBLEM if (spec_errors or sec_critical or sec_high or risk_threshold_exceeded) else EXIT_OK
        else:
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

        has_structural_escape = any(r.has_structural_escape for r in sec_reports.values())
        if has_structural_escape:
            print(
                "\nerror: installation blocked by structural filesystem escape "
                "(escaping symlinks or path traversal cannot be overridden with --allow-risky or --force)",
                file=sys.stderr,
            )
            return EXIT_PROBLEM

        if risk_threshold_exceeded and not args.allow_risky:
            print(
                f"\nerror: installation blocked by configured security.max_risk_score ({max_risk_score}): "
                + ", ".join(risk_threshold_exceeded),
                file=sys.stderr,
            )
            return EXIT_PROBLEM

        if (sec_critical > 0 or sec_high > 0) and not args.allow_risky:
            print(
                "\nerror: installation blocked by static security policy "
                "(re-run with --allow-risky after reviewing `skillporter scan` output)",
                file=sys.stderr,
            )
            return EXIT_PROBLEM

        if args.dry_run:
            if not is_json:
                print("\nDry run complete (no files modified).")
            return EXIT_OK

        if not is_json:
            print("\nInstalling...\n")

        try:
            all_results = install_many(
                root,
                skill_dirs,
                targets,
                strategy=args.strategy,
                scope=args.scope,
                force=args.force,
                source=resolved.canonical_source,
                resolved_commit=resolved.resolved_commit,
                record_state=True,
                adapt=args.adapt,
            )
        except InstallError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR

        # Update manifest if skillporter.yaml exists
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
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_ERROR
    fmt = _fmt_mode(args)
    files = [target] if target.name == "SKILL.md" else discover(target)
    if not files:
        empty_cats = {cat: 0 for cat in CATEGORY_KEYS}
        if fmt == "sarif":
            print(json.dumps(to_sarif([]), indent=2))
        elif fmt == "json":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "risk_score": 0,
                        "risk_level": "LOW",
                        "recommendation": "APPROVE",
                        "category_breakdown": empty_cats,
                        "engine": "skillporter-static",
                        "engine_version": SCANNER_ENGINE_VERSION,
                        "files": {},
                        "skills": {},
                    },
                    indent=2,
                )
            )
        else:
            print(f"no SKILL.md found under {target} (0 errors).")
        return EXIT_OK

    problems = 0
    json_out = {}
    skill_details = {}
    sec_reports = []
    agg_categories: dict[str, int] = {cat: 0 for cat in CATEGORY_KEYS}
    max_risk = 0
    engine_name = "skillporter-static"
    engine_ver = SCANNER_ENGINE_VERSION
    max_risk_threshold = getattr(args, "max_risk_score", None)

    for path in files:
        issues: list[Issue] = validate(parse_skill(path))
        errors = [i for i in issues if i.level == "error"]
        problems += len(errors)
        srep = scan_skill(
            path.parent,
            engine=getattr(args, "engine", "auto"),
            offline=getattr(args, "offline", False),
        )
        sec_reports.append(srep)
        engine_name = srep.engine
        engine_ver = srep.engine_version
        if srep.risk_score > max_risk:
            max_risk = srep.risk_score
        for cat, cscore in srep.category_breakdown.items():
            agg_categories[cat] = max(agg_categories.get(cat, 0), cscore)
        if srep.exceeds_risk_threshold(max_risk_threshold):
            problems += 1

        label = path.parent.name
        json_out[str(path)] = [{"level": i.level, "code": i.code, "message": i.message} for i in issues]
        skill_details[label] = {
            "path": str(path.parent),
            "valid": len(errors) == 0,
            "risk_score": srep.risk_score,
            "risk_level": srep.risk_level,
            "recommendation": srep.recommendation,
            "category_breakdown": srep.category_breakdown,
            "engine": srep.engine,
            "engine_version": srep.engine_version,
            "issues": json_out[str(path)],
        }
        if fmt == "text":
            if issues:
                print(
                    f"{label}: (risk: {srep.risk_score}/100 · {srep.recommendation} · "
                    f"engine: {srep.engine} v{srep.engine_version})"
                )
                for i in issues:
                    print(f"  {i}")
            else:
                print(
                    f"{label}: OK  (risk: {srep.risk_score}/100 · {srep.recommendation} · "
                    f"engine: {srep.engine} v{srep.engine_version})"
                )

    if fmt == "sarif":
        print(json.dumps(to_sarif(sec_reports, tool_version=engine_ver), indent=2))
    elif fmt == "json":
        rec = "REJECT" if max_risk > 50 else ("CAUTION" if max_risk > 20 else "APPROVE")
        rlevel = "CRITICAL" if max_risk > 80 else ("HIGH" if max_risk > 50 else ("MEDIUM" if max_risk > 20 else "LOW"))
        print(
            json.dumps(
                {
                    "valid": problems == 0,
                    "risk_score": max_risk,
                    "risk_level": rlevel,
                    "recommendation": rec,
                    "category_breakdown": agg_categories,
                    "engine": engine_name,
                    "engine_version": engine_ver,
                    "files": json_out,
                    "skills": skill_details,
                },
                indent=2,
            )
        )
    return EXIT_PROBLEM if problems else EXIT_OK


def _cmd_scan(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_ERROR

    fmt = _fmt_mode(args)
    skill_dirs = [target] if (target / "SKILL.md").is_file() else [p.parent for p in discover(target)]
    if not skill_dirs:
        skill_dirs = [target]

    reports = {
        d.name: scan_skill(
            d,
            engine=getattr(args, "engine", "auto"),
            offline=getattr(args, "offline", False),
        )
        for d in skill_dirs
    }
    max_risk_threshold = getattr(args, "max_risk_score", None)
    blocked = any(
        (not r.passed) or r.has_structural_escape or r.exceeds_risk_threshold(max_risk_threshold)
        for r in reports.values()
    )

    if fmt == "sarif":
        print(json.dumps(to_sarif(reports), indent=2))
        return EXIT_PROBLEM if blocked else EXIT_OK

    if fmt == "json":
        max_score = max((r.risk_score for r in reports.values()), default=0)
        first_rep = next(iter(reports.values()), None)
        print(
            json.dumps(
                {
                    "passed": not blocked,
                    "risk_score": max_score,
                    "engine": first_rep.engine if first_rep else "skillporter-static",
                    "engine_version": first_rep.engine_version if first_rep else SCANNER_ENGINE_VERSION,
                    "reports": {k: v.to_dict() for k, v in reports.items()},
                },
                indent=2,
            )
        )
        return EXIT_PROBLEM if blocked else EXIT_OK

    print(f"skillporter {__version__} — security assessment\n")
    for sname, rep in reports.items():
        exceeds = rep.exceeds_risk_threshold(max_risk_threshold)
        verdict = "PASSED" if (rep.passed and not exceeds) else "BLOCKED"
        print(
            f"{sname}: {badge(verdict)}  "
            f"(risk: {rep.risk_score}/100 · {rep.recommendation} · "
            f"engine: {rep.engine} v{rep.engine_version} · "
            f"sha256: {rep.tree_hash[:12] if rep.tree_hash else 'n/a'})"
        )
        non_zero_cats = {k: v for k, v in rep.category_breakdown.items() if v > 0}
        if non_zero_cats:
            cats_str = ", ".join(f"{k}={v}" for k, v in non_zero_cats.items())
            print(f"  Categories: {cats_str}")
        if not rep.findings:
            print("  0 findings across all scanned files.")
        for f in rep.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"  [{badge(f.severity)}] {f.code} ({loc}): {f.message}")
            if f.remediation:
                print(f"      Fix: {f.remediation}")
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
    fmt_out = _fmt_mode(args)
    try:
        resolved = resolve_source(args.source, base_dir=root)
    except (SourceError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        skill_dirs = resolved.skill_dirs
        if getattr(args, "skill", None):
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

        items = []
        sec_reports = []
        for sdir in skill_dirs:
            pkg = inspect_skill_dir(sdir)
            doc = pkg.skill_doc or parse_skill(sdir / "SKILL.md")
            issues = validate(doc)
            sec = scan_skill(sdir)
            sec_reports.append(sec)
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
                    "risk_score": sec.risk_score,
                    "risk_level": sec.risk_level,
                    "recommendation": sec.recommendation,
                    "category_breakdown": sec.category_breakdown,
                    "engine": sec.engine,
                    "engine_version": sec.engine_version,
                    "security": sec.to_dict(),
                    "adaptation_limitations": pkg.adaptation_limitations,
                    "adapted_previews": adapted_previews,
                }
            )

        if fmt_out == "sarif":
            print(json.dumps(to_sarif(sec_reports), indent=2))
            return EXIT_OK

        if fmt_out == "json":
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
            print(
                f"  Security:    {badge(verdict)} "
                f"(risk: {item['risk_score']}/100 · {item['recommendation']} · "
                f"engine: {item['engine']} v{item['engine_version']} · "
                f"sha256: {str(sec_d['tree_hash'])[:12]})"
            )
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
    fmt = _fmt_mode(args)
    if getattr(args, "check", False):
        issues = check_lockfile_staleness(root)
        manifest = load_manifest(root)
        if manifest and manifest.skills:
            try:
                graph = resolve_dependency_graph(root, manifest)
                lock_now = load_lockfile(root, warn_migration=False)
                for sname in graph.install_order:
                    if sname not in lock_now.skills:
                        issues.append(f"unpinned dependency in graph: {sname!r} is missing from {LOCKFILE_FILENAME}")
            except DependencyError as exc:
                issues.append(f"dependency error: {exc}")

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

    records = load_state(root)
    manifest = load_manifest(root)
    lock = load_lockfile(root, warn_migration=False)

    graph = None
    with contextlib.suppress(Exception):
        graph = resolve_dependency_graph(root, manifest)

    if records:
        for sname, rec in sorted(records.items()):
            gnode = graph.nodes.get(sname) if graph else None
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
            )
    if graph:
        for sname, gnode in sorted(graph.nodes.items()):
            if sname in lock.skills:
                lock.skills[sname].dependencies = dict(gnode.dependencies)
                lock.skills[sname].risk_score = gnode.risk_score
                lock.skills[sname].direct = gnode.direct
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
                )
    elif not records:
        for skill_md in discover(root):
            sname = skill_md.parent.name
            if sname in lock.skills:
                continue
            thash, _ = compute_tree_hash(skill_md.parent)
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
            )

    lpath = save_lockfile(root, lock)
    if fmt == "json":
        print(json.dumps(lock.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"wrote {lpath} ({len(lock.skills)} locked skill(s))")
    return EXIT_OK


def _latest_tree_mtime_ns(skill_dir: Path) -> int:
    """Return the maximum modification timestamp (in ns) across all files in *skill_dir*."""
    latest = 0
    for fpath in skill_dir.rglob("*"):
        if fpath.is_symlink():
            continue
        with contextlib.suppress(OSError):
            ns = fpath.stat().st_mtime_ns
            if ns > latest:
                latest = ns
    return latest


def _cmd_sync(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    manifest = load_manifest(root)
    lock = load_lockfile(root)
    targets = _resolve_target_harnesses(args.harness, root, scope=args.scope, default_detected=True)
    force_flag = getattr(args, "force", False)
    prefer_path = getattr(args, "prefer", None)
    allow_risky = getattr(args, "allow_risky", False)
    max_risk_score = getattr(args, "max_risk_score", None)
    if max_risk_score is None and manifest is not None:
        max_risk_score = manifest.max_risk_score

    diag = run_diagnose(root, scope=args.scope)

    # 1. Security scan every discovered skill copy before syncing or updating lockfile
    for sname, copies in sorted(diag.skill_copies.items()):
        for cdir in copies:
            srep = scan_skill(cdir)
            if srep.has_structural_escape or (not srep.passed and not allow_risky):
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

    # 2. Check lockfile drift before overwriting skillporter.lock
    if (root / LOCKFILE_FILENAME).is_file() and not force_flag and not prefer_path:
        lock_mismatches: list[str] = []
        for sname, locked in sorted(lock.skills.items()):
            for cdir in diag.skill_copies.get(sname, []):
                actual_hash, _ = compute_tree_hash(cdir)
                if locked.tree_hash and actual_hash != locked.tree_hash:
                    lock_mismatches.append(f"{sname} ({cdir}): locked {locked.tree_hash[:8]} != disk {actual_hash[:8]}")
        if lock_mismatches:
            print(
                "error: on-disk skill content differs from skillporter.lock; refusing to re-lock without --force:",
                file=sys.stderr,
            )
            for lm in lock_mismatches:
                print(f"  - {lm}", file=sys.stderr)
            return EXIT_PROBLEM

    # 3. Check copy drift across harnesses
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
        # Resolve full transitive dependency graph first (detects cycles and semver conflicts)
        try:
            graph = resolve_dependency_graph(root, manifest)
        except (DependencyCycleError, DependencyConflictError, DependencyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_PROBLEM

        spec_by_name = {s.name: s for s in manifest.skills}
        for sname in graph.install_order:
            node = graph.nodes[sname]
            spec = spec_by_name.get(sname)
            skill_targets = (spec.harnesses if spec and spec.harnesses else None) or manifest.harnesses or targets
            strategy = (spec.strategy if spec and spec.strategy else None) or manifest.strategy or args.strategy

            if node.skill_dir and node.skill_dir.exists():
                sdir = node.skill_dir
                srep = scan_skill(sdir)
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
                    source=node.source,
                    resolved_commit=node.resolved_commit,
                    version=node.version,
                    record_state=True,
                    skill_name_override=sname,
                )
                synced_results.extend(res)
            elif spec:
                resolved = resolve_source(spec.source, base_dir=root, ref_override=spec.ref)
                try:
                    for sdir in resolved.skill_dirs:
                        if sdir.name != spec.name and len(resolved.skill_dirs) > 1:
                            continue
                        srep = scan_skill(sdir)
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
            ranked = sorted(copies, key=_latest_tree_mtime_ns, reverse=True)
            if _latest_tree_mtime_ns(ranked[0]) == _latest_tree_mtime_ns(ranked[1]):
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

    if (root / LOCKFILE_FILENAME).exists() or manifest is not None:
        _cmd_lock(argparse.Namespace(path=str(root)))

    for r in synced_results:
        print(f"{r.action:9} {r.harness:16} {r.dest}")
    return EXIT_OK


def _cmd_update(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    target_arg = (args.skill or "").strip()
    if target_arg in (".", "./") or (target_arg and Path(target_arg).expanduser().is_dir()):
        if target_arg not in ("", ".", "./"):
            root = Path(target_arg).expanduser().resolve()
        target_arg = ""

    records = load_state(root, scope=args.scope)
    if not records:
        print("no managed skills recorded in .skillporter/state.json to update.")
        return EXIT_OK

    names = [target_arg] if target_arg else sorted(records)
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
    lock = load_lockfile(root)

    if args.fix and diag.skills:
        for rep in diag.reports.values():
            for loc in rep.locations:
                for blink in loc.broken_links:
                    bp = Path(blink)
                    if bp.is_symlink():
                        bp.unlink(missing_ok=True)
        active_proj = {d.harness.name for d in detected if d.project_active}
        targets = args.harness or sorted({"claude-code", "codex", "cursor"} | active_proj)
        for skill_md in diag.skills:
            sname = skill_md.parent.name
            copies = diag.skill_copies.get(sname, [skill_md.parent])
            locked_entry = lock.skills.get(sname)

            # Filter for copies that pass static security scan AND (when locked) match lockfile hash
            clean_copies: list[Path] = []
            for cdir in copies:
                srep = scan_skill(cdir)
                if not srep.passed or srep.has_structural_escape:
                    continue
                if locked_entry and locked_entry.tree_hash:
                    chash, _ = compute_tree_hash(cdir)
                    if chash != locked_entry.tree_hash:
                        continue
                clean_copies.append(cdir)

            if not clean_copies:
                # Never spread a tampered or security-blocked copy across harnesses
                continue

            best_dir = max(clean_copies, key=_latest_tree_mtime_ns)
            with contextlib.suppress(InstallError):
                run_install(
                    root,
                    best_dir,
                    targets,
                    strategy="copy",
                    scope=args.scope,
                    force=True,
                    record_state=True,
                )
        diag = run_diagnose(root, only=targets, scope=args.scope)

    # Check static security and lockfile integrity across all discovered copies
    for sname, copies in sorted(diag.skill_copies.items()):
        locked_entry = lock.skills.get(sname)
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
    if any("security:" in f for f in diag.findings):
        remediations.append("skillporter scan .         # inspect and remediate security findings")
    if any("lockfile drift:" in f for f in diag.findings):
        remediations.append("skillporter rollback <skill>  # or `skillporter lock` if edit was intentional")
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
        print(f"\nStatus: {badge('UNHEALTHY')} ({len(diag.findings)} issue(s) found).")
        return EXIT_PROBLEM
    print(f"\nStatus: {badge('HEALTHY')} (all checked skills reachable, valid, and in sync).")
    return EXIT_OK


def _cmd_info(args: argparse.Namespace) -> int:
    target = (args.target or ".").strip()
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
        pass

    # 3. Check local skill by name or local directory path
    cwd = Path.cwd().resolve()
    cand_path = Path(target).expanduser()
    if not cand_path.is_absolute():
        cand_path = (cwd / cand_path).resolve()

    matched_skill_md: Path | None = None
    if (cand_path / "SKILL.md").is_file():
        matched_skill_md = cand_path / "SKILL.md"
    elif cand_path.is_dir():
        found = discover(cand_path)
        if found:
            matched_skill_md = found[0]
        else:
            if args.json:
                print(json.dumps({"type": "workspace", "root": str(cand_path), "skills": []}, indent=2))
            else:
                print(f"Workspace:   {cand_path} (0 skills discovered)")
            return EXIT_OK
    else:
        for smd in discover(cwd):
            if smd.parent.name == target or parse_skill(smd).name == target:
                matched_skill_md = smd
                break

    if matched_skill_md is not None:
        doc = parse_skill(matched_skill_md)
        thash, _ = compute_tree_hash(matched_skill_md.parent)
        info_payload = {
            "type": "local-skill",
            "name": doc.name or matched_skill_md.parent.name,
            "path": str(matched_skill_md.parent),
            "description": doc.description,
            "license": doc.frontmatter.get("license", ""),
            "tree_hash": thash,
        }
        if args.json:
            print(json.dumps(info_payload, indent=2))
            return EXIT_OK
        print(f"Skill:       {info_payload['name']}")
        print(f"Path:        {info_payload['path']}")
        print(f"Description: {info_payload['description']}")
        print(f"SHA-256:     {thash[:16]}...")
        return EXIT_OK

    print(
        f"error: {target!r} is not a registered harness, registry package, or local skill",
        file=sys.stderr,
    )
    return EXIT_ERROR


def _cmd_pack(args: argparse.Namespace) -> int:
    raw_target = args.path.strip()
    cand = Path(raw_target).expanduser()
    if not cand.is_absolute():
        cand = (Path.cwd() / cand).resolve()
    out_dir = Path(args.out).expanduser().resolve()

    skill_dirs: list[Path] = []
    if (cand / "SKILL.md").is_file():
        skill_dirs = [cand]
    elif cand.is_dir():
        seen_names: set[str] = set()
        for smd in discover(cand):
            if smd.parent.name not in seen_names:
                seen_names.add(smd.parent.name)
                skill_dirs.append(smd.parent)
        if not skill_dirs:
            print(f"no SKILL.md found under {cand}")
            return EXIT_OK
    else:
        for smd in discover(Path.cwd()):
            if smd.parent.name == raw_target or parse_skill(smd).name == raw_target:
                skill_dirs = [smd.parent]
                break

    if not skill_dirs:
        print(f"error: {args.path!r} does not contain SKILL.md", file=sys.stderr)
        return EXIT_ERROR

    packed_items = []
    try:
        for sdir in skill_dirs:
            rel = pack_skill(sdir, out_dir)
            packed_items.append(rel)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        first = packed_items[0]
        print(
            json.dumps(
                {
                    "skill": first.skill_name,
                    "version": first.version,
                    "archive": str(first.archive_path),
                    "provenance": str(first.provenance_path),
                    "archive_sha256": first.archive_sha256,
                    "tree_hash": first.tree_hash,
                },
                indent=2,
            )
        )
        return EXIT_OK
    for rel in packed_items:
        print(f"packed {rel.skill_name}@{rel.version}:")
        print(f"  archive:    {rel.archive_path} (sha256: {rel.archive_sha256[:16]}...)")
        print(f"  provenance: {rel.provenance_path}")
    return EXIT_OK


def _cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    manifest = load_manifest(root)
    lock = load_lockfile(root, warn_migration=False)
    records = load_state(root, scope=args.scope)
    diag = run_diagnose(root, scope=args.scope)
    detected = [d for d in harnesses.detect_harnesses(root) if d.installed]

    lock_drift: list[str] = []
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
    if _fmt_mode(args) == "json":
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


def _cmd_sandbox(args: argparse.Namespace) -> int:
    raw_target = (args.skill or ".").strip()
    if raw_target == "run" and getattr(args, "target", ""):
        raw_target = str(args.target).strip()
    cand = Path(raw_target).expanduser()
    if not cand.is_absolute():
        cand = (Path.cwd() / cand).resolve()
    if not cand.exists():
        for smd in discover(Path.cwd()):
            if smd.parent.name == raw_target or parse_skill(smd).name == raw_target:
                cand = smd.parent.resolve()
                break
    if not cand.exists():
        print(f"error: {raw_target!r} does not exist", file=sys.stderr)
        return EXIT_ERROR

    rep = run_sandbox(cand, runtime=getattr(args, "runtime", "auto"))
    if _fmt_mode(args) == "json":
        print(json.dumps(rep.to_dict(), indent=2))
        return EXIT_OK if rep.verdict != "REJECT" else EXIT_PROBLEM

    print(f"skillporter {__version__} — [EXPERIMENTAL] Dry-Run Sandbox Report")
    print(f"Skill:              {rep.root.name} ({rep.root})")
    print(f"Runtime:            {rep.runtime_used} (requested: {rep.runtime_requested})")
    print(f"Filesystem mutated: {'YES' if rep.mutated_filesystem else 'NO (verified by SHA-256 tree hash)'}")
    print(f"Network mutated:    {'YES' if rep.mutated_network else 'NO (outbound sockets disabled)'}")
    print(f"Risk Score:         {rep.risk_score}/100 · {badge(rep.verdict)}")
    print(f"\nProposed file writes:      {len(rep.proposed_file_writes)}")
    for ev in rep.proposed_file_writes:
        print(f"  - {ev.file}:{ev.line} -> {ev.detail}")
    print(f"Proposed sensitive reads:  {len(rep.proposed_file_reads)}")
    for ev in rep.proposed_file_reads:
        print(f"  - {ev.file}:{ev.line} -> {ev.detail}")
    print(f"Proposed network calls:    {len(rep.proposed_network_calls)}")
    for ev in rep.proposed_network_calls:
        print(f"  - {ev.file}:{ev.line} -> {ev.detail}")
    print(f"Proposed tool invocations: {len(rep.proposed_tool_invocations)}")
    for ev in rep.proposed_tool_invocations:
        print(f"  - {ev.file}:{ev.line} -> {ev.detail}")
    print(f"Proposed env accesses:     {len(rep.proposed_env_accesses)}")
    for ev in rep.proposed_env_accesses:
        print(f"  - {ev.file}:{ev.line} -> {ev.target}")
    print(
        style(
            "\nDisclaimer: Experimental dry-run sandbox traces proposed operations without touching host state; "
            "it reduces but does not eliminate runtime risk.",
            DIM,
        )
    )
    return EXIT_OK if rep.verdict != "REJECT" else EXIT_PROBLEM


def _cmd_demo(args: argparse.Namespace) -> int:
    result = run_demo()
    if _fmt_mode(args) == "json":
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


def _cmd_explain(args: argparse.Namespace) -> int:
    query = " ".join(args.finding).strip()
    if not query:
        print("error: provide a finding code or message to explain (e.g. `skillporter explain DRIFT`)", file=sys.stderr)
        return EXIT_ERROR
    exp = explain_finding(query)
    if _fmt_mode(args) == "json":
        print(json.dumps(exp.to_dict(), indent=2))
        return EXIT_OK

    print(f"{style(exp.code, BOLD, CYAN)} — {exp.title} ({exp.category})")
    print(f"\nCause:\n  {exp.cause}")
    print(f"\nWhy it matters:\n  {exp.impact}")
    print(f"\nSuggested fix:\n  {exp.suggested_fix}")
    if exp.commands:
        print("\nRun:")
        for cmd in exp.commands:
            print(f"  $ {cmd}")
    return EXIT_OK


def _cmd_graph(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    manifest = load_manifest(root)
    try:
        graph = resolve_dependency_graph(root, manifest)
    except (DependencyCycleError, DependencyConflictError, DependencyError) as exc:
        if _fmt_mode(args) == "json":
            print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROBLEM

    if _fmt_mode(args) == "json":
        payload = graph.to_dict()
        payload["valid"] = True
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    print(f"skillporter {__version__} — resolved dependency graph ({len(graph.nodes)} node(s))\n")
    print(graph.render_tree())
    if graph.install_order:
        print(f"\nTopological install order: {' -> '.join(graph.install_order)}")
    return EXIT_OK


def _cmd_publish(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    try:
        res = publish_skill(
            target,
            registry_url=getattr(args, "registry", None),
            dry_run=getattr(args, "dry_run", False),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PROBLEM

    if _fmt_mode(args) == "json":
        print(json.dumps(res, indent=2))
        return EXIT_OK

    pkg = res["package"]  # type: ignore[index]
    print(f"Published {pkg['slug']}@{pkg['version']} (contract v{res['contract_version']})")  # type: ignore[index]
    print(f"  Archive:    {res['archive']} (sha256: {str(res['archive_sha256'])[:16]}...)")
    print(f"  Provenance: {res['provenance']}")
    print(f"  Risk score: {res['risk_score']}/100")
    print(f"  Target:     {res['published_to']}")
    return EXIT_OK


def _cmd_ci_report(args: argparse.Namespace) -> int:
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

    if _fmt_mode(args) == "json":
        print(json.dumps(payload, indent=2))
    else:
        print(md, end="")
    return exit_code


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
    d.add_argument("--format", choices=["text", "json"], default="")
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
    a.add_argument("--max-risk-score", type=int, default=None, help="fail closed if skill risk score exceeds threshold")
    a.add_argument("--engine", choices=["auto", "skillspector", "static"], default="auto")
    a.add_argument("--offline", action="store_true", help="use built-in offline security scanner only")
    a.add_argument(
        "--allow-risky",
        action="store_true",
        help="proceed even if static security scan finds high/critical issues",
    )
    a.add_argument("--force", action="store_true", help="overwrite existing installations")
    a.add_argument("--format", choices=["text", "json"], default="")
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
    v = sub.add_parser("validate", help="validate SKILL.md files against the Agent Skills spec and compute risk score")
    v.add_argument("path", nargs="?", default=".")
    v.add_argument("--format", choices=["text", "json", "sarif"], default="")
    v.add_argument("--max-risk-score", type=int, default=None)
    v.add_argument("--engine", choices=["auto", "skillspector", "static"], default="auto")
    v.add_argument("--offline", action="store_true")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=_cmd_validate)

    # scan
    sc = sub.add_parser("scan", help="run security and supply-chain checks (0-100 risk score, JSON/SARIF)")
    sc.add_argument("path", nargs="?", default=".")
    sc.add_argument("--format", choices=["text", "json", "sarif"], default="")
    sc.add_argument("--max-risk-score", type=int, default=None)
    sc.add_argument("--engine", choices=["auto", "skillspector", "static"], default="auto")
    sc.add_argument("--offline", action="store_true")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=_cmd_scan)

    # sandbox
    sb = sub.add_parser("sandbox", help="[experimental] run opt-in dry-run behavioral sandbox on a skill")
    sb.add_argument("skill", nargs="?", default="run", help="'run <skill>' or direct skill path")
    sb.add_argument("target", nargs="?", default="", help="skill path when invoked as `sandbox run <skill>`")
    sb.add_argument("--runtime", choices=["auto", "wasm", "gvisor", "dry-run"], default="auto")
    sb.add_argument("--format", choices=["text", "json"], default="")
    sb.add_argument("--json", action="store_true")
    sb.set_defaults(func=_cmd_sandbox)

    # demo
    dm = sub.add_parser("demo", help="run a 60-second zero-residue demo resolving broken symlinks & drift")
    dm.add_argument("--format", choices=["text", "json"], default="")
    dm.add_argument("--json", action="store_true")
    dm.set_defaults(func=_cmd_demo)

    # explain
    ex = sub.add_parser("explain", help="translate any diagnostic, lockfile, or security finding into plain English")
    ex.add_argument("finding", nargs="+", help="finding code (e.g. DRIFT, BROKEN, sec-prompt-override) or message")
    ex.add_argument("--format", choices=["text", "json"], default="")
    ex.add_argument("--json", action="store_true")
    ex.set_defaults(func=_cmd_explain)

    # graph
    gr = sub.add_parser("graph", help="visualize and verify the resolved skill dependency graph")
    gr.add_argument("path", nargs="?", default=".")
    gr.add_argument("--format", choices=["text", "json"], default="")
    gr.add_argument("--json", action="store_true")
    gr.set_defaults(func=_cmd_graph)

    # publish
    pub = sub.add_parser("publish", help="validate, security-gate, pack, and publish a skill to the registry")
    pub.add_argument("path", nargs="?", default=".")
    pub.add_argument("--registry", default=None, help="custom registry index path or URL")
    pub.add_argument("--dry-run", action="store_true", help="verify registry client contract without publishing")
    pub.add_argument("--format", choices=["text", "json"], default="")
    pub.add_argument("--json", action="store_true")
    pub.set_defaults(func=_cmd_publish)

    # ci-report
    cir = sub.add_parser("ci-report", help="generate a Markdown/JSON PR diagnostic & security report")
    cir.add_argument("path", nargs="?", default=".")
    cir.add_argument("--scope", choices=["project", "user"], default="project")
    cir.add_argument("--output", default=None, help="write Markdown report to file")
    cir.add_argument("--github-repo", default=None, help="owner/repo to comment on when --pr is set")
    cir.add_argument("--pr", type=int, default=None, help="PR number to post comment to")
    cir.add_argument("--format", choices=["markdown", "json", "text"], default="")
    cir.add_argument("--json", action="store_true")
    cir.set_defaults(func=_cmd_ci_report)

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
    ins.add_argument("--skill", action="append", help="select specific skill name(s) from a multi-skill repo")
    ins.add_argument(
        "--preview-adapt",
        choices=["cursor-mdc", "copilot-instructions", "windsurf-rules", "continue-rules", "aider-conventions"],
    )
    ins.add_argument("--format", choices=["text", "json", "sarif"], default="")
    ins.add_argument("--json", action="store_true")
    ins.set_defaults(func=_cmd_inspect)

    # sync
    sy = sub.add_parser("sync", help="synchronize skills (and transitive dependencies) across harnesses")
    sy.add_argument("path", nargs="?", default=".")
    sy.add_argument("--harness", action="append")
    sy.add_argument("--strategy", choices=["copy", "symlink"], default="copy")
    sy.add_argument("--scope", choices=["project", "user"], default="project")
    sy.add_argument("--prefer", help="authoritative skill path when resolving content drift")
    sy.add_argument(
        "--max-risk-score",
        type=int,
        default=None,
        help="fail closed if skill risk score exceeds threshold",
    )
    sy.add_argument(
        "--allow-risky",
        action="store_true",
        help="proceed even if static security scan finds high/critical issues",
    )
    sy.add_argument("--force", action="store_true", help="overwrite drifted copies after snapshotting backups")
    sy.set_defaults(func=_cmd_sync)

    # update
    up = sub.add_parser("update", help="update managed skills from their tracked sources")
    up.add_argument("skill", nargs="?", default="")
    up.add_argument("--scope", choices=["project", "user"], default="project")
    up.add_argument("--path", default=".")
    up.set_defaults(func=_cmd_update)

    # rollback
    rb = sub.add_parser("rollback", help="restore a skill (and its dependency graph) to its previous backup snapshot")
    rb.add_argument("skill", help="skill name to roll back (or 'all')")
    rb.add_argument("--backup-id", default="")
    rb.add_argument("--scope", choices=["project", "user"], default="project")
    rb.add_argument("--path", default=".")
    rb.set_defaults(func=_cmd_rollback)

    # lock
    lk = sub.add_parser("lock", help="generate, update, or verify (--check) deterministic skillporter.lock")
    lk.add_argument("path", nargs="?", default=".")
    lk.add_argument("--check", action="store_true", help="fail with exit code 1 if lockfile is stale or drifted")
    lk.add_argument("--format", choices=["text", "json"], default="")
    lk.add_argument("--json", action="store_true")
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
    inf = sub.add_parser("info", help="show detailed metadata for a harness adapter, registry package, or local skill")
    inf.add_argument("target", nargs="?", default=".", help="harness ID, package slug, or local skill name")
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

    # status
    st_p = sub.add_parser("status", help="show unified workspace manifest, lockfile, per-harness, and drift status")
    st_p.add_argument("path", nargs="?", default=".")
    st_p.add_argument("--scope", choices=["project", "user"], default="project")
    st_p.add_argument("--format", choices=["text", "json"], default="")
    st_p.add_argument("--json", action="store_true")
    st_p.set_defaults(func=_cmd_status)

    return p


KNOWN_COMMANDS = (
    "diagnose",
    "add",
    "install",
    "uninstall",
    "remove",
    "validate",
    "scan",
    "sandbox",
    "demo",
    "explain",
    "graph",
    "publish",
    "ci-report",
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
    "status",
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
    rc = int(args.func(args))
    with contextlib.suppress(Exception):
        record_telemetry_event(Path.cwd(), str(args.command), rc)
    return rc


def entrypoint() -> None:
    """Console & zipapp entrypoint that propagates exit codes to the OS."""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
