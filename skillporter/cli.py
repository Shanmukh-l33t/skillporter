"""skillporter CLI.

Commands: ``diagnose``, ``install``, ``uninstall``, ``validate``, ``matrix``.
Every command exits non-zero when it finds a real problem, so it drops straight
into CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, harnesses
from .diagnose import diagnose as run_diagnose
from .frontmatter import Issue, parse_skill, validate
from .install import InstallError
from .install import install as run_install
from .install import uninstall as run_uninstall

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_ERROR = 2


def _print_matrix(as_json: bool) -> int:
    rows = []
    for name in harnesses.names():
        h = harnesses.get(name)
        rows.append({
            "harness": h.name,
            "verified": h.verified,
            "recursive": h.recursive,
            "project_paths": [p.path for p in h.project_paths],
            "user_paths": [p.path for p in h.user_paths],
            "docs": h.docs,
            "notes": list(h.notes),
        })
    if as_json:
        print(json.dumps(rows, indent=2))
        return EXIT_OK

    print(f"skillporter {__version__} — harness compatibility matrix\n")
    width = max(len(r["harness"]) for r in rows)
    print(f"{'HARNESS'.ljust(width)}  {'STATUS':9}  PROJECT PATHS")
    print(f"{'-' * width}  {'-' * 9}  {'-' * 40}")
    for r in rows:
        status = "verified" if r["verified"] else "expected"
        paths = ", ".join(r["project_paths"]) or "(user-level only: " + ", ".join(r["user_paths"]) + ")"
        print(f"{r['harness'].ljust(width)}  {status:9}  {paths}")
    print("\nNotes:")
    for r in rows:
        for n in r["notes"]:
            print(f"  {r['harness']}: {n}")
    return EXIT_OK


def _cmd_diagnose(args) -> int:
    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return EXIT_ERROR

    diag = run_diagnose(root, only=args.harness or None)

    if args.json:
        payload = {
            "root": str(diag.root),
            "skills": diag.skill_names,
            "harnesses": {
                name: {
                    "verified": r.verified,
                    "reachable_skills": sorted(r.reachable_skills),
                    "locations": [
                        {
                            "path": str(loc.resolved),
                            "status": loc.status,
                            "skills": loc.skill_dirs,
                            "broken_links": loc.broken_links,
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

    print(f"skillporter {__version__} — diagnosing {diag.root}\n")
    if not diag.skills:
        print("no SKILL.md found under this path.")
        return EXIT_PROBLEM

    print(f"skills found: {', '.join(diag.skill_names)}\n")

    names = sorted(diag.reports)
    width = max(len(s) for s in diag.skill_names)
    header = "SKILL".ljust(width) + "  " + "  ".join(n[:14].ljust(14) for n in names)
    print(header)
    print("-" * len(header))
    for skill in diag.skill_names:
        cells = []
        for n in names:
            cells.append(("yes" if diag.reports[n].loads(skill) else "MISSING").ljust(14))
        print(skill.ljust(width) + "  " + "  ".join(cells))

    print()
    if diag.findings:
        print("findings:")
        for f in diag.findings:
            print(f"  - {f}")
    else:
        print("no findings — every skill is reachable by every checked harness.")

    return EXIT_PROBLEM if diag.findings else EXIT_OK


def _cmd_install(args) -> int:
    root = Path(args.path).expanduser().resolve()
    skill_dir = Path(args.skill).expanduser()
    if not skill_dir.is_absolute():
        skill_dir = (root / skill_dir).resolve()
    try:
        results = run_install(
            root, skill_dir, args.harness,
            strategy=args.strategy, scope=args.scope, force=args.force,
        )
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    for r in results:
        print(f"{r.action:9} {r.harness:12} {r.dest}  ({r.detail})")
    return EXIT_OK


def _cmd_uninstall(args) -> int:
    root = Path(args.path).expanduser().resolve()
    try:
        results = run_uninstall(root, args.skill, args.harness, scope=args.scope)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for r in results:
        print(f"{r.action:9} {r.harness:12} {r.dest}")
    return EXIT_OK


def _cmd_validate(args) -> int:
    target = Path(args.path).expanduser()
    files = [target] if target.name == "SKILL.md" else sorted(target.rglob("SKILL.md"))
    if not files:
        print(f"error: no SKILL.md under {target}", file=sys.stderr)
        return EXIT_ERROR

    problems = 0
    for path in files:
        issues: list[Issue] = validate(parse_skill(path))
        errors = [i for i in issues if i.level == "error"]
        problems += len(errors)
        label = path.parent.name
        if issues:
            print(f"{label}:")
            for i in issues:
                print(f"  {i}")
        else:
            print(f"{label}: OK")
    return EXIT_PROBLEM if problems else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skillporter",
        description="Diagnose and fix Agent Skill installation across Claude Code, Codex, Cursor, Hermes and OpenClaw.",
    )
    p.add_argument("--version", action="version", version=f"skillporter {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("diagnose", help="show which harnesses can actually see each skill")
    d.add_argument("path", nargs="?", default=".", help="repo root (default: .)")
    d.add_argument("--harness", action="append", help="limit to one harness (repeatable)")
    d.add_argument("--json", action="store_true", help="machine-readable output")
    d.set_defaults(func=_cmd_diagnose)

    i = sub.add_parser("install", help="install a skill into one or more harnesses")
    i.add_argument("skill", help="path to the skill directory")
    i.add_argument("--harness", action="append", required=True, help="target harness (repeatable)")
    i.add_argument("--strategy", choices=["copy", "symlink"], default="copy",
                   help="copy (portable, Docker/CI safe) or symlink (single source of truth)")
    i.add_argument("--scope", choices=["project", "user"], default="project")
    i.add_argument("--path", default=".", help="repo root (default: .)")
    i.add_argument("--force", action="store_true", help="overwrite an existing install")
    i.set_defaults(func=_cmd_install)

    u = sub.add_parser("uninstall", help="remove a skill from harnesses")
    u.add_argument("skill", help="skill name")
    u.add_argument("--harness", action="append", required=True)
    u.add_argument("--scope", choices=["project", "user"], default="project")
    u.add_argument("--path", default=".")
    u.set_defaults(func=_cmd_uninstall)

    v = sub.add_parser("validate", help="validate SKILL.md files against the Agent Skills spec")
    v.add_argument("path", nargs="?", default=".")
    v.set_defaults(func=_cmd_validate)

    m = sub.add_parser("matrix", help="print the harness path matrix")
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=lambda a: _print_matrix(a.json))

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
