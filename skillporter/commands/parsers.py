"""Modular subparser builders for environment, portability, harness, and profile commands."""

from __future__ import annotations

import argparse

from .environment_cmd import (
    cmd_adopt,
    cmd_diff,
    cmd_export,
    cmd_import,
    cmd_move,
    cmd_outdated,
    cmd_profile,
    cmd_self_skill,
    cmd_status,
)
from .harness_cmd import cmd_harness

HELP_EPILOG = """Workflow command groups:
  Environment & Portability
    status       Unified workspace, lockfile, harness, and drift control center
    diff         Compare workspace against a .skillpack, directory, or profile
    export       Package managed environment into an offline-ready .skillpack
    import       Validate and restore an environment from a .skillpack archive
    profile      Create, inspect, and switch named skill environment profiles

  Skill Lifecycle
    add          Install skills from GitHub, Git URL, archive, registry, or path
    install      Install a local skill directory into selected harnesses
    remove       Remove a skill from selected harnesses without deleting source
    move         Relocate an installed skill across harnesses safely
    adopt        Bring existing unmanaged on-disk skills under management
    sync         Synchronize skills and transitive dependencies across harnesses
    outdated     Check managed skills against upstream commits and versions
    update       Update managed skills from tracked sources with rollback backup
    rollback     Restore a skill (and dependencies) to a verified snapshot
    init / lock  Initialize skillporter.yaml or pin/verify skillporter.lock

  Harnesses & Diagnostics
    harness      List, inspect, and check status across 19 AI agent harnesses
    detect       Auto-detect installed AI coding and autonomous agents
    diagnose     Check reachability, content drift, and broken symlinks
    doctor       Run full health check and optional --fix auto-repair
    matrix       Print the 19-harness compatibility and verification matrix

  Security & Agent Integration
    scan         Run static supply-chain & prompt-injection checks (JSON/SARIF)
    validate     Validate SKILL.md compliance and compute 0-100 risk score
    audit        Inspect provenance, lockfile integrity, and audit.jsonl log
    self-skill   Install the official Skillporter skill into your AI agents
    mcp          Start the workspace-bounded stdio MCP server
"""


def build_shared_flag_parent() -> argparse.ArgumentParser:
    """Subparser parent providing ``-q/--quiet``, ``-v/--verbose``, and ``--no-color``."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS, help="minimal output")
    parent.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS, help="detailed output")
    parent.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="disable ANSI colors")
    return parent


def attach_harness_control_flags(
    parser: argparse.ArgumentParser,
    *,
    include_conflict: bool = False,
    include_isolated: bool = False,
) -> None:
    """Attach ``--exclude-harness``, ``--on-conflict``, ``--isolated``, and ``--custom-path``."""
    parser.add_argument(
        "--exclude-harness",
        action="append",
        help="exclude specific harness(es) from target selection (repeatable or comma-separated)",
    )
    if include_conflict:
        parser.add_argument(
            "--on-conflict",
            choices=["fail", "skip", "overwrite"],
            default="fail",
            help="behavior when destination already exists (default: fail)",
        )
    if include_isolated:
        parser.add_argument(
            "--isolated",
            action="store_true",
            help="prefer harness-dedicated paths (e.g. .cursor/skills) over shared .agents/skills",
        )
        parser.add_argument(
            "--custom-path",
            action="append",
            help="override harness install directory as HARNESS=REL_PATH (repeatable)",
        )


def register_evolution_commands(sub: argparse._SubParsersAction, shared_parent: argparse.ArgumentParser) -> None:
    """Register environment, portability, harness, profile, move, adopt, outdated, and self-skill commands."""
    # status (upgraded unified environment status)
    st_p = sub.add_parser(
        "status",
        parents=[shared_parent],
        help="show unified environment, manifest, lockfile, harness, and drift status",
    )
    st_p.add_argument("path", nargs="?", default=".")
    st_p.add_argument("--scope", choices=["project", "user"], default="project")
    st_p.add_argument("--format", choices=["text", "json"], default="")
    st_p.add_argument("--json", action="store_true")
    st_p.set_defaults(func=cmd_status)

    # diff
    df = sub.add_parser(
        "diff",
        parents=[shared_parent],
        help="compare workspace environment against a .skillpack, directory, or profile",
    )
    df.add_argument("target", help=".skillpack file, target directory, or profile:<name>")
    df.add_argument("--base", default=".", help="base workspace, .skillpack, or profile:<name> (default: .)")
    df.add_argument("--scope", choices=["project", "user"], default="project")
    df.add_argument("--format", choices=["text", "json"], default="")
    df.add_argument("--json", action="store_true")
    df.set_defaults(func=cmd_diff)

    # export
    exp = sub.add_parser(
        "export",
        parents=[shared_parent],
        help="package managed skill environment into a portable .skillpack archive",
    )
    exp.add_argument("output", nargs="?", default="", help="output .skillpack file path")
    exp.add_argument("--path", default=".", help="workspace root (default: .)")
    exp.add_argument("--scope", choices=["project", "user"], default="project")
    exp.add_argument("--skill", action="append", help="export only specific skill(s) (repeatable)")
    exp.add_argument("--managed-only", action="store_true", help="exclude unmanaged on-disk skills")
    exp.add_argument("--manifest-only", action="store_true", help="export provenance references without skill files")
    exp.add_argument("--format", choices=["text", "json"], default="")
    exp.add_argument("--json", action="store_true")
    exp.set_defaults(func=cmd_export)

    # import
    imp = sub.add_parser(
        "import",
        parents=[shared_parent],
        help="validate and restore an environment from a .skillpack archive",
    )
    imp.add_argument("pack", help="path to .skillpack archive")
    imp.add_argument("--path", default=".", help="destination workspace root (default: .)")
    imp.add_argument("--scope", choices=["project", "user"], default=None, help="override target scope")
    imp.add_argument("--harness", action="append", help="override target harness(es) or 'detected'/'compatible'")
    imp.add_argument("--exclude-harness", action="append", help="exclude specific harness(es)")
    imp.add_argument("--only-detected", action="store_true", help="install only into harnesses detected on this host")
    imp.add_argument("--on-conflict", choices=["fail", "skip", "overwrite"], default="fail")
    imp.add_argument("--force", action="store_true", help="overwrite existing installations")
    imp.add_argument("--dry-run", action="store_true", help="validate package and preview restoration plan")
    imp.add_argument("--preview", action="store_true", help="alias for --dry-run")
    imp.add_argument("--allow-risky", action="store_true", help="accept non-structural static scan warnings")
    imp.add_argument("--max-risk-score", type=int, default=None)
    imp.add_argument("--no-manifest", action="store_true", help="do not write skillporter.yaml / skillporter.lock")
    imp.add_argument("--format", choices=["text", "json"], default="")
    imp.add_argument("--json", action="store_true")
    imp.set_defaults(func=cmd_import)

    # harness {list,inspect,status}
    hp = sub.add_parser(
        "harness",
        parents=[shared_parent],
        help="discover, inspect, and check status across 19 AI agent harnesses",
    )
    hp.add_argument("--scope", choices=["project", "user"], default="project")
    hp.add_argument("--path", default=".")
    hp.add_argument("--format", choices=["text", "json"], default="")
    hp.add_argument("--json", action="store_true")
    hsub = hp.add_subparsers(dest="harness_action", required=False)

    hl = hsub.add_parser("list", parents=[shared_parent], help="list supported, detected, and configured harnesses")
    hl.add_argument("path", nargs="?", default=".")
    hl.add_argument("--scope", choices=["project", "user"], default="project")
    hl.add_argument("--category", choices=["coding", "autonomous", "editor"])
    hl.add_argument("--detected", action="store_true", help="only show harnesses detected on this machine")
    hl.add_argument("--compatible", action="store_true", help="only show NATIVE and COMPATIBLE harnesses")
    hl.add_argument("--format", choices=["text", "json"], default="")
    hl.add_argument("--json", action="store_true")

    hi = hsub.add_parser("inspect", parents=[shared_parent], help="inspect capabilities, paths, and peers of a harness")
    hi.add_argument("target", help="harness ID or alias (e.g. claude-code, codex, cursor, hermes)")
    hi.add_argument("--path", default=".")
    hi.add_argument("--scope", choices=["project", "user"], default="project")
    hi.add_argument("--format", choices=["text", "json"], default="")
    hi.add_argument("--json", action="store_true")

    hs = hsub.add_parser("status", parents=[shared_parent], help="show active harness configuration and skill health")
    hs.add_argument("path", nargs="?", default=".")
    hs.add_argument("--scope", choices=["project", "user"], default="project")
    hs.add_argument("--format", choices=["text", "json"], default="")
    hs.add_argument("--json", action="store_true")
    hp.set_defaults(func=cmd_harness)

    # profile {list,save,create,show,use,delete}
    pr = sub.add_parser(
        "profile",
        parents=[shared_parent],
        help="manage named skill environment profiles (frontend, backend, security-review, etc.)",
    )
    pr.add_argument("--path", default=".")
    pr.add_argument("--scope", choices=["project", "user"], default="project")
    pr.add_argument("--format", choices=["text", "json"], default="")
    pr.add_argument("--json", action="store_true")
    psub = pr.add_subparsers(dest="profile_action", required=False)

    pl = psub.add_parser("list", parents=[shared_parent], help="list saved profiles and active profile")
    pl.add_argument("--path", default=".")
    pl.add_argument("--scope", choices=["project", "user"], default="project")
    pl.add_argument("--format", choices=["text", "json"], default="")
    pl.add_argument("--json", action="store_true")

    for save_alias in ("save", "create"):
        ps = psub.add_parser(save_alias, parents=[shared_parent], help="save current or selected setup as a profile")
        ps.add_argument("name", help="profile name (e.g. backend, security-review)")
        ps.add_argument("--path", default=".")
        ps.add_argument("--scope", choices=["project", "user"], default="project")
        ps.add_argument("--harness", action="append", help="override harnesses stored in profile")
        ps.add_argument("--skill", action="append", help="include only specific skills")
        ps.add_argument("--format", choices=["text", "json"], default="")
        ps.add_argument("--json", action="store_true")

    psh = psub.add_parser("show", parents=[shared_parent], help="display a profile's YAML or JSON definition")
    psh.add_argument("name", help="profile name")
    psh.add_argument("--path", default=".")
    psh.add_argument("--scope", choices=["project", "user"], default="project")
    psh.add_argument("--format", choices=["text", "json"], default="")
    psh.add_argument("--json", action="store_true")

    pu = psub.add_parser("use", parents=[shared_parent], help="activate a profile and synchronize its skills")
    pu.add_argument("name", help="profile name")
    pu.add_argument("--path", default=".")
    pu.add_argument("--scope", choices=["project", "user"], default="project")
    pu.add_argument("--prune", action="store_true", help="remove managed skills not present in target profile")
    pu.add_argument("--dry-run", action="store_true", help="preview profile switch without modifying files")
    pu.add_argument("--format", choices=["text", "json"], default="")
    pu.add_argument("--json", action="store_true")

    pdel = psub.add_parser("delete", parents=[shared_parent], help="delete a saved profile")
    pdel.add_argument("name", help="profile name")
    pdel.add_argument("--path", default=".")
    pdel.add_argument("--scope", choices=["project", "user"], default="project")
    pdel.add_argument("--format", choices=["text", "json"], default="")
    pdel.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_profile)

    # move
    mv = sub.add_parser(
        "move",
        parents=[shared_parent],
        help="move an installed skill between harnesses safely",
    )
    mv.add_argument("skill", help="installed skill name")
    mv.add_argument("--from", dest="from_harness", action="append", required=True, help="source harness(es)")
    mv.add_argument("--to", dest="to_harness", action="append", required=True, help="destination harness(es)")
    mv.add_argument("--exclude-harness", action="append")
    mv.add_argument("--scope", choices=["project", "user"], default="project")
    mv.add_argument("--strategy", choices=["copy", "symlink"], default="copy")
    mv.add_argument("--path", default=".")
    mv.add_argument("--on-conflict", choices=["fail", "skip", "overwrite"], default="fail")
    mv.add_argument("--force", action="store_true")
    mv.add_argument("--isolated", action="store_true", help="use dedicated harness path where supported")
    mv.add_argument("--custom-path", action="append")
    mv.add_argument("--dry-run", action="store_true")
    mv.add_argument("--format", choices=["text", "json"], default="")
    mv.add_argument("--json", action="store_true")
    mv.set_defaults(func=cmd_move)

    # adopt
    adp = sub.add_parser(
        "adopt",
        parents=[shared_parent],
        help="adopt existing unmanaged on-disk skills into Skillporter tracking",
    )
    adp.add_argument("skills", nargs="*", help="specific skill name(s) to adopt (default: all unmanaged)")
    adp.add_argument("--all", action="store_true", help="adopt all unmanaged skills in scope")
    adp.add_argument("--path", default=".")
    adp.add_argument("--scope", choices=["project", "user"], default="project")
    adp.add_argument("--allow-risky", action="store_true")
    adp.add_argument("--format", choices=["text", "json"], default="")
    adp.add_argument("--json", action="store_true")
    adp.set_defaults(func=cmd_adopt)

    # outdated
    outd = sub.add_parser(
        "outdated",
        parents=[shared_parent],
        help="check managed skills for upstream version or content changes",
    )
    outd.add_argument("skill", nargs="?", default="", help="optional single skill name")
    outd.add_argument("--path", default=".")
    outd.add_argument("--scope", choices=["project", "user"], default="project")
    outd.add_argument("--format", choices=["text", "json"], default="")
    outd.add_argument("--json", action="store_true")
    outd.set_defaults(func=cmd_outdated)

    # self-skill
    ss = sub.add_parser(
        "self-skill",
        parents=[shared_parent],
        help="install or view the official Skillporter AI agent skill",
    )
    ss.add_argument("self_skill_action", nargs="?", choices=["install", "show", "path"], default="install")
    ss.add_argument("--harness", action="append", help="target harness(es) or 'detected'/'compatible'/'all'")
    ss.add_argument("--exclude-harness", action="append")
    ss.add_argument("--scope", choices=["project", "user"], default="project")
    ss.add_argument("--path", default=".")
    ss.add_argument("--force", action="store_true", default=True)
    ss.add_argument("--dry-run", action="store_true")
    ss.add_argument("--format", choices=["text", "json"], default="")
    ss.add_argument("--json", action="store_true")
    ss.set_defaults(func=cmd_self_skill)
