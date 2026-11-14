"""Validate, scan, sandbox, and explain command implementations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import __version__
from ..explain import explain_finding
from ..frontmatter import Issue, discover, parse_skill, validate
from ..sandbox import run_sandbox
from ..security import CATEGORY_KEYS, SCANNER_ENGINE_VERSION, scan_skill, to_sarif
from ..ui import BOLD, CYAN, DIM, badge, style
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode


def cmd_validate(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_ERROR
    fmt = fmt_mode(args)
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
            "posture": srep.posture,
            "scan_complete": srep.scan_complete,
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


def cmd_scan(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_ERROR

    fmt = fmt_mode(args)
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
            f"(risk: {rep.risk_score}/100 · {rep.recommendation} · posture: {rep.posture} · "
            f"engine: {rep.engine} v{rep.engine_version} · "
            f"sha256: {rep.tree_hash[:12] if rep.tree_hash else 'n/a'})"
        )
        if not rep.scan_complete:
            print(
                f"  Completeness: INCOMPLETE (truncated={len(rep.files_truncated)}, "
                f"unreadable={len(rep.files_unreadable)})"
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
            "\nNote: Static scanning inspects patterns and symlinks; a clean scan does not prove runtime safety.",
            DIM,
        )
    )
    return EXIT_PROBLEM if blocked else EXIT_OK


def cmd_sandbox(args: argparse.Namespace) -> int:
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
    if fmt_mode(args) == "json":
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


def cmd_explain(args: argparse.Namespace) -> int:
    query = " ".join(args.finding).strip()
    if not query:
        print(
            "error: provide a finding code or message to explain (e.g. `skillporter explain DRIFT`)",
            file=sys.stderr,
        )
        return EXIT_ERROR
    exp = explain_finding(query)
    if fmt_mode(args) == "json":
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
