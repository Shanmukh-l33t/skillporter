"""skillporter CLI — Argument Parser & Modular Command Dispatcher."""

from __future__ import annotations

import argparse
import contextlib
import difflib
import os
import stat
import sys
from pathlib import Path

from . import __version__
from .commands.add import cmd_add, cmd_install, cmd_update
from .commands.audit import cmd_audit
from .commands.common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, apply_ui_flags
from .commands.doctor import (
    cmd_ci_report,
    cmd_demo,
    cmd_detect,
    cmd_diagnose,
    cmd_doctor,
    cmd_matrix,
)
from .commands.parsers import (
    HELP_EPILOG,
    attach_harness_control_flags,
    build_shared_flag_parent,
    register_evolution_commands,
)
from .commands.registry import cmd_info, cmd_inspect, cmd_list, cmd_pack, cmd_publish, cmd_search
from .commands.remove import cmd_rollback, cmd_uninstall
from .commands.scan import cmd_explain, cmd_sandbox, cmd_scan, cmd_validate
from .commands.sync import cmd_graph, cmd_init, cmd_lock, cmd_sync
from .mcp_server import run_mcp_stdio
from .telemetry import record_telemetry_event

__all__ = ["EXIT_ERROR", "EXIT_OK", "EXIT_PROBLEM", "KNOWN_COMMANDS", "build_parser", "entrypoint", "main"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skillporter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "ONE SKILL. EVERY AGENT. Control center for managing, securing, synchronizing, "
            "and moving AI agent skills across 19 harnesses, projects, and machines."
        ),
        epilog=HELP_EPILOG,
    )
    p.add_argument("--version", action="version", version=f"skillporter {__version__}")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress non-essential status output")
    p.add_argument("-v", "--verbose", action="store_true", help="show detailed paths, unchanged items, and full lists")
    p.add_argument("--no-color", action="store_true", help="disable ANSI color codes")

    shared = build_shared_flag_parent()
    sub = p.add_subparsers(dest="command", required=False, metavar="<command>")

    # diagnose
    d = sub.add_parser("diagnose", parents=[shared], help="check reachability, drift, and broken symlinks")
    d.add_argument("path", nargs="?", default=".", help="repo root (default: .)")
    d.add_argument("--harness", action="append", help="limit to specific harness(es) or 'all' (repeatable)")
    d.add_argument("--scope", choices=["project", "user"], default="project")
    d.add_argument("--format", choices=["text", "json"], default="")
    d.add_argument("--json", action="store_true", help="machine-readable JSON output")
    d.set_defaults(func=cmd_diagnose)

    # add
    a = sub.add_parser("add", parents=[shared], help="install skills from GitHub, git URL, archive, or path")
    a.add_argument("source", help="owner/repo, GitHub URL, archive, or local path")
    a.add_argument("--harness", action="append", help="target harness or 'all'/'compatible'/'detected' (repeatable)")
    attach_harness_control_flags(a, include_conflict=True, include_isolated=True)
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
    a.add_argument("--allow-risky", action="store_true", help="explicitly accept non-structural security findings")
    a.add_argument("--force", action="store_true", help="overwrite existing installations (never bypasses security)")
    a.add_argument("--format", choices=["text", "json"], default="")
    a.add_argument("--json", action="store_true", help="machine-readable JSON output")
    a.set_defaults(func=cmd_add)

    # install
    i = sub.add_parser("install", parents=[shared], help="install a local skill directory into one or more harnesses")
    i.add_argument("skill", help="path to the skill directory")
    i.add_argument("--harness", action="append", required=True, help="target harness (repeatable)")
    attach_harness_control_flags(i, include_conflict=True, include_isolated=True)
    i.add_argument("--strategy", choices=["copy", "symlink"], default="copy")
    i.add_argument("--scope", choices=["project", "user"], default="project")
    i.add_argument("--path", default=".", help="repo root (default: .)")
    i.add_argument("--adapt", action="store_true", help="also emit adapted harness rule file")
    i.add_argument("--dry-run", action="store_true", help="preview destinations and conflicts without writing")
    i.add_argument("--allow-risky", action="store_true", help="explicitly accept non-structural security findings")
    i.add_argument("--force", action="store_true", help="overwrite an existing install (never bypasses security)")
    i.add_argument("--format", choices=["text", "json"], default="")
    i.add_argument("--json", action="store_true", help="machine-readable JSON output")
    i.set_defaults(func=cmd_install)

    # uninstall / remove
    for cmd_name in ("uninstall", "remove"):
        u = sub.add_parser(cmd_name, parents=[shared], help="remove a skill from harnesses safely")
        u.add_argument("skill", help="skill name")
        u.add_argument("--harness", action="append", required=(cmd_name == "uninstall"))
        attach_harness_control_flags(u)
        u.add_argument("--scope", choices=["project", "user"], default="project")
        u.add_argument("--path", default=".")
        u.add_argument("--dry-run", action="store_true", help="preview removal without deleting files")
        u.add_argument("--format", choices=["text", "json"], default="")
        u.add_argument("--json", action="store_true", help="machine-readable JSON output")
        u.set_defaults(func=cmd_uninstall)

    # validate
    v = sub.add_parser("validate", parents=[shared], help="validate SKILL.md spec compliance and compute risk score")
    v.add_argument("path", nargs="?", default=".")
    v.add_argument("--format", choices=["text", "json", "sarif"], default="")
    v.add_argument("--max-risk-score", type=int, default=None)
    v.add_argument("--engine", choices=["auto", "skillspector", "static"], default="auto")
    v.add_argument("--offline", action="store_true")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_validate)

    # scan
    sc = sub.add_parser("scan", parents=[shared], help="run static security and supply-chain checks (JSON/SARIF)")
    sc.add_argument("path", nargs="?", default=".")
    sc.add_argument("--format", choices=["text", "json", "sarif"], default="")
    sc.add_argument("--max-risk-score", type=int, default=None)
    sc.add_argument("--engine", choices=["auto", "skillspector", "static"], default="auto")
    sc.add_argument("--offline", action="store_true")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=cmd_scan)

    # audit
    au = sub.add_parser("audit", parents=[shared], help="audit provenance, lockfile integrity, and security log")
    au.add_argument("path", nargs="?", default=".")
    au.add_argument("--scope", choices=["project", "user"], default="project")
    au.add_argument("--limit", type=int, default=50, help="max recent audit events to include")
    au.add_argument("--format", choices=["text", "json"], default="")
    au.add_argument("--json", action="store_true")
    au.set_defaults(func=cmd_audit)

    # sandbox
    sb = sub.add_parser("sandbox", parents=[shared], help="[experimental] run opt-in dry-run behavioral sandbox")
    sb.add_argument("skill", nargs="?", default="run", help="'run <skill>' or direct skill path")
    sb.add_argument("target", nargs="?", default="", help="skill path when invoked as `sandbox run <skill>`")
    sb.add_argument("--runtime", choices=["auto", "wasm", "gvisor", "dry-run"], default="auto")
    sb.add_argument("--format", choices=["text", "json"], default="")
    sb.add_argument("--json", action="store_true")
    sb.set_defaults(func=cmd_sandbox)

    # demo
    dm = sub.add_parser("demo", parents=[shared], help="run zero-residue demo resolving broken symlinks & drift")
    dm.add_argument("--format", choices=["text", "json"], default="")
    dm.add_argument("--json", action="store_true")
    dm.set_defaults(func=cmd_demo)

    # explain
    ex = sub.add_parser("explain", parents=[shared], help="translate diagnostic or security codes into plain English")
    ex.add_argument("finding", nargs="+", help="finding code (e.g. DRIFT, BROKEN, sec-prompt-override) or message")
    ex.add_argument("--format", choices=["text", "json"], default="")
    ex.add_argument("--json", action="store_true")
    ex.set_defaults(func=cmd_explain)

    # graph
    gr = sub.add_parser("graph", parents=[shared], help="visualize and verify the resolved skill dependency graph")
    gr.add_argument("path", nargs="?", default=".")
    gr.add_argument("--format", choices=["text", "json"], default="")
    gr.add_argument("--json", action="store_true")
    gr.set_defaults(func=cmd_graph)

    # publish
    pub = sub.add_parser("publish", parents=[shared], help="validate, security-gate, pack, and publish to registry")
    pub.add_argument("path", nargs="?", default=".")
    pub.add_argument("--registry", default=None, help="custom registry index path or URL")
    pub.add_argument("--dry-run", action="store_true", help="verify registry client contract without publishing")
    pub.add_argument("--format", choices=["text", "json"], default="")
    pub.add_argument("--json", action="store_true")
    pub.set_defaults(func=cmd_publish)

    # ci-report
    cir = sub.add_parser("ci-report", parents=[shared], help="generate a Markdown/JSON PR diagnostic & security report")
    cir.add_argument("path", nargs="?", default=".")
    cir.add_argument("--scope", choices=["project", "user"], default="project")
    cir.add_argument("--output", default=None, help="write Markdown report to file")
    cir.add_argument("--github-repo", default=None, help="owner/repo to comment on when --pr is set")
    cir.add_argument("--pr", type=int, default=None, help="PR number to post comment to")
    cir.add_argument("--format", choices=["markdown", "json", "text"], default="")
    cir.add_argument("--json", action="store_true")
    cir.set_defaults(func=cmd_ci_report)

    # matrix
    m = sub.add_parser("matrix", parents=[shared], help="print the 19-harness compatibility and verification matrix")
    m.add_argument("--category", choices=["coding", "autonomous"])
    m.add_argument("--format", choices=["text", "json"], default="")
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=cmd_matrix)

    # detect
    dt = sub.add_parser("detect", parents=[shared], help="detect installed AI agent harnesses on this machine")
    dt.add_argument("path", nargs="?", default=".")
    dt.add_argument("--all", action="store_true", help="include harnesses not currently detected")
    dt.add_argument("--versions", action="store_true", help="probe CLI versions where available")
    dt.add_argument("--format", choices=["text", "json"], default="")
    dt.add_argument("--json", action="store_true")
    dt.set_defaults(func=cmd_detect)

    # init
    init_p = sub.add_parser("init", parents=[shared], help="initialize skillporter.yaml in a project")
    init_p.add_argument("path", nargs="?", default=".")
    init_p.add_argument("--force", action="store_true")
    init_p.add_argument("--format", choices=["text", "json"], default="")
    init_p.add_argument("--json", action="store_true")
    init_p.set_defaults(func=cmd_init)

    # list
    ls_p = sub.add_parser("list", parents=[shared], help="list installed and discovered skills")
    ls_p.add_argument("path", nargs="?", default=".")
    ls_p.add_argument("--scope", choices=["project", "user"], default="project")
    ls_p.add_argument("--format", choices=["text", "json"], default="")
    ls_p.add_argument("--json", action="store_true")
    ls_p.set_defaults(func=cmd_list)

    # search
    sr = sub.add_parser("search", parents=[shared], help="search the skill registry catalog")
    sr.add_argument("query", nargs="?", default="")
    sr.add_argument("--category", default="")
    sr.add_argument("--format", choices=["text", "json"], default="")
    sr.add_argument("--json", action="store_true")
    sr.set_defaults(func=cmd_search)

    # inspect
    ins = sub.add_parser("inspect", parents=[shared], help="inspect a local or remote skill package before installing")
    ins.add_argument("source", help="local path, archive, or GitHub owner/repo")
    ins.add_argument("--skill", action="append", help="select specific skill name(s) from a multi-skill repo")
    ins.add_argument(
        "--preview-adapt",
        choices=["cursor-mdc", "copilot-instructions", "windsurf-rules", "continue-rules", "aider-conventions"],
    )
    ins.add_argument("--format", choices=["text", "json", "sarif"], default="")
    ins.add_argument("--json", action="store_true")
    ins.set_defaults(func=cmd_inspect)

    # sync
    sy = sub.add_parser("sync", parents=[shared], help="synchronize skills and dependencies across harnesses")
    sy.add_argument("path", nargs="?", default=".")
    sy.add_argument("--harness", action="append")
    attach_harness_control_flags(sy)
    sy.add_argument("--strategy", choices=["copy", "symlink"], default="copy")
    sy.add_argument("--scope", choices=["project", "user"], default="project")
    sy.add_argument("--prefer", help="authoritative skill path when resolving content drift")
    sy.add_argument("--dry-run", action="store_true", help="preview synchronization without modifying files")
    sy.add_argument(
        "--max-risk-score", type=int, default=None, help="fail closed if skill risk score exceeds threshold"
    )
    sy.add_argument("--allow-risky", action="store_true", help="explicitly accept non-structural security findings")
    sy.add_argument("--force", action="store_true", help="overwrite drifted copies after snapshotting backups")
    sy.add_argument("--format", choices=["text", "json"], default="")
    sy.add_argument("--json", action="store_true")
    sy.set_defaults(func=cmd_sync)

    # update
    up = sub.add_parser("update", parents=[shared], help="update managed skills from their tracked sources")
    up.add_argument("skill", nargs="?", default="")
    up.add_argument("--scope", choices=["project", "user"], default="project")
    up.add_argument("--path", default=".")
    up.add_argument("--dry-run", action="store_true", help="check upstream and scan without modifying files")
    up.add_argument("--allow-risky", action="store_true", help="explicitly accept non-structural security findings")
    up.add_argument("--format", choices=["text", "json"], default="")
    up.add_argument("--json", action="store_true")
    up.set_defaults(func=cmd_update)

    # rollback
    rb = sub.add_parser("rollback", parents=[shared], help="restore a skill to a verified backup snapshot")
    rb.add_argument("skill", help="skill name to roll back (or 'all')")
    rb.add_argument("--backup-id", default="")
    rb.add_argument("--scope", choices=["project", "user"], default="project")
    rb.add_argument("--path", default=".")
    rb.add_argument("--dry-run", action="store_true", help="preview target backup snapshot without restoring")
    rb.add_argument("--format", choices=["text", "json"], default="")
    rb.add_argument("--json", action="store_true")
    rb.set_defaults(func=cmd_rollback)

    # lock
    lk = sub.add_parser("lock", parents=[shared], help="generate, update, or verify skillporter.lock")
    lk.add_argument("path", nargs="?", default=".")
    lk.add_argument("--check", action="store_true", help="fail with exit code 1 if lockfile is stale or drifted")
    lk.add_argument("--format", choices=["text", "json"], default="")
    lk.add_argument("--json", action="store_true")
    lk.set_defaults(func=cmd_lock)

    # doctor
    doc = sub.add_parser("doctor", parents=[shared], help="run comprehensive health check (and optional --fix repair)")
    doc.add_argument("path", nargs="?", default=".")
    doc.add_argument("--harness", action="append")
    doc.add_argument("--scope", choices=["project", "user"], default="project")
    doc.add_argument("--fix", action="store_true", help="auto-repair missing/drifted installs and broken symlinks")
    doc.add_argument("--dry-run", action="store_true", help="preview doctor check without applying --fix writes")
    doc.add_argument("--format", choices=["text", "json"], default="")
    doc.add_argument("--json", action="store_true")
    doc.set_defaults(func=cmd_doctor)

    # info
    inf = sub.add_parser("info", parents=[shared], help="show metadata for a harness, registry package, or local skill")
    inf.add_argument("target", nargs="?", default=".", help="harness ID, package slug, or local skill name")
    inf.add_argument("--format", choices=["text", "json"], default="")
    inf.add_argument("--json", action="store_true")
    inf.set_defaults(func=cmd_info)

    # pack
    pk = sub.add_parser("pack", parents=[shared], help="build an immutable .tar.gz skill release bundle")
    pk.add_argument("path", nargs="?", default=".")
    pk.add_argument("--out", default=".skillporter/dist")
    pk.add_argument("--format", choices=["text", "json"], default="")
    pk.add_argument("--json", action="store_true")
    pk.set_defaults(func=cmd_pack)

    # mcp
    mcp_p = sub.add_parser("mcp", parents=[shared], help="run the stdio Model Context Protocol (MCP) server")
    mcp_p.add_argument("--root", default=None, help="explicit workspace root boundary (default: cwd)")
    mcp_p.add_argument("--allow-writes", action="store_true", help="enable mutating MCP tools; default is read-only")
    mcp_p.add_argument("--allow-user-scope", action="store_true", help="permit scope='user' reads outside workspace")
    mcp_p.set_defaults(
        func=lambda a: run_mcp_stdio(
            workspace_root=Path(a.root).expanduser().resolve() if getattr(a, "root", None) else None,
            allow_writes=True if getattr(a, "allow_writes", False) else None,
            allow_user_scope=True if getattr(a, "allow_user_scope", False) else None,
        )
    )

    register_evolution_commands(sub, shared)
    return p


KNOWN_COMMANDS = (
    "diagnose",
    "add",
    "install",
    "uninstall",
    "remove",
    "validate",
    "scan",
    "audit",
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
    "diff",
    "export",
    "import",
    "harness",
    "profile",
    "move",
    "adopt",
    "outdated",
    "self-skill",
)


def _stdin_is_pipe() -> bool:
    """True when stdin is a pipe or socket rather than a terminal or a device.

    MCP clients and directory indexers launch a stdio server by spawning the
    console script with a pipe attached. A shell user, or a script that
    redirects /dev/null, gets a terminal or a character device instead.
    """
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
    except (AttributeError, OSError, ValueError):
        return False
    return stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not args_list:
        if _stdin_is_pipe():
            print(
                "skillporter: no subcommand and a piped stdin, starting the MCP server "
                "(use `skillporter mcp` to start it explicitly)",
                file=sys.stderr,
            )
            args_list = ["mcp"]
        else:
            parser.print_help()
            return EXIT_OK

    non_flag = [tok for tok in args_list if not tok.startswith("-")]
    if non_flag and args_list[0] == non_flag[0] and non_flag[0] not in KNOWN_COMMANDS:
        first = non_flag[0]
        matches = difflib.get_close_matches(first, KNOWN_COMMANDS, n=2, cutoff=0.5)
        hint = f" (did you mean: {', '.join(matches)}?)" if matches else ""
        print(f"error: unknown command {first!r}{hint}", file=sys.stderr)
        return EXIT_ERROR

    args = parser.parse_args(args_list)
    apply_ui_flags(args)
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
