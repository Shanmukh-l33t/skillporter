"""List, search, inspect, info, pack, and publish command implementations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import harnesses
from ..diagnose import diagnose as run_diagnose
from ..formats import inspect_skill_dir, render_adapted_skill
from ..frontmatter import discover, parse_skill, validate
from ..registry import pack_skill, publish_skill, resolve_registry_spec, search_catalog
from ..security import compute_tree_hash, scan_skill, to_sarif
from ..sources import SourceError, resolve_source
from ..state import load_state
from ..ui import BOLD, badge, render_table, style
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode, is_quiet, is_verbose


def cmd_list(args: argparse.Namespace) -> int:
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

    if fmt_mode(args) == "json":
        print(json.dumps(rows, indent=2))
        return EXIT_OK

    if is_quiet(args):
        for r in rows:
            print(r["name"])
        return EXIT_OK

    if not rows:
        print(f"no skills installed or discovered under {root} (scope: {args.scope})")
        return EXIT_OK

    trows = [
        [
            str(r["name"]),
            str(r["version"]),
            "yes" if r["managed"] else "no",
            str(r["tree_hash"]),
            ", ".join(r["harnesses"]) if r["harnesses"] else "(none)",
        ]
        for r in rows
    ]
    max_r = None if is_verbose(args) else 30
    print(
        render_table(
            ["SKILL", "VERSION", "MANAGED", "HASH", "HARNESSES"],
            trows,
            max_rows=max_r,
            more_hint="run `skillporter list --verbose` to list all skills",
        )
    )
    return EXIT_OK


def cmd_search(args: argparse.Namespace) -> int:
    results = search_catalog(args.query or "", category=args.category or "")
    if fmt_mode(args) == "json":
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


def cmd_inspect(args: argparse.Namespace) -> int:
    root = Path.cwd()
    fmt_out = fmt_mode(args)
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
                    "posture": sec.posture,
                    "scan_complete": sec.scan_complete,
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


def cmd_info(args: argparse.Namespace) -> int:
    target = (args.target or ".").strip()
    try:
        h = harnesses.get(target)
        payload = {
            "type": "harness",
            "id": h.name,
            "display_name": h.label,
            "category": h.category,
            "support_status": h.support_status,
            "verification_level": h.verification_level,
            "verification_evidence": h.verification_evidence,
            "verified_date": h.verified_date,
            "docs": h.docs,
            "project_paths": [p.path for p in h.project_paths],
            "user_paths": [p.path for p in h.user_paths],
            "notes": list(h.notes),
            "limitations": list(h.limitations),
        }
        if fmt_mode(args) == "json":
            print(json.dumps(payload, indent=2))
            return EXIT_OK
        print(f"Harness:       {h.label} ({h.name})")
        print(f"Category:      {h.category}")
        print(f"Support:       {h.support_status} ({h.verification_level}, verified {h.verified_date})")
        print(f"Evidence:      {h.verification_evidence}")
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

    try:
        pkg = resolve_registry_spec(target)
        if fmt_mode(args) == "json":
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
            if fmt_mode(args) == "json":
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
        if fmt_mode(args) == "json":
            print(json.dumps(info_payload, indent=2))
            return EXIT_OK
        print(f"Skill:       {info_payload['name']}")
        print(f"Path:        {info_payload['path']}")
        print(f"Description: {info_payload['description']}")
        print(f"SHA-256:     {thash[:16]}...")
        return EXIT_OK

    print(
        f"error: {target!r} is not a registered harness, registry package, or local skill "
        "(run `skillporter matrix` or `skillporter search`)",
        file=sys.stderr,
    )
    return EXIT_ERROR


def cmd_pack(args: argparse.Namespace) -> int:
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

    if fmt_mode(args) == "json":
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


def cmd_publish(args: argparse.Namespace) -> int:
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

    if fmt_mode(args) == "json":
        print(json.dumps(res, indent=2))
        return EXIT_OK

    pkg = res["package"]  # type: ignore[index]
    print(f"Published {pkg['slug']}@{pkg['version']} (contract v{res['contract_version']})")  # type: ignore[index]
    print(f"  Archive:    {res['archive']} (sha256: {str(res['archive_sha256'])[:16]}...)")
    print(f"  Provenance: {res['provenance']}")
    print(f"  Risk score: {res['risk_score']}/100")
    print(f"  Target:     {res['published_to']}")
    return EXIT_OK
