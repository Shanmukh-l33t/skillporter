"""Modular subparser builders for environment, portability, harness, and profile commands."""

from __future__ import annotations

import argparse

from .authoring_cmd import cmd_lint, cmd_new, cmd_preview, cmd_test
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
from .instructions_cmd import cmd_consolidate, cmd_context
from .intelligence_cmd import cmd_insights, cmd_suggest
from .policy_cmd import cmd_policy

HELP_EPILOG = """Workflow command groups:
  Instructions & Context
    consolidate  Discover, deduplicate, conflict-check, and unify agent instructions
    context      Inspect active instructions, ignored files, and startup token stack
    suggest      Recommend relevant, security-graded skills for this repository
    insights     Measure skill/instruction token overhead and opt-in local usage

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

  Authoring & Quality
    new          Scaffold a spec-compliant skill with scripts, references, and tests
    lint         Validate metadata, local file references, scripts, and limits
    preview      Preview exact native and adapted outputs received by each harness
    test         Run skill.test.yaml trigger activation and structural test suites

  Harnesses & Diagnostics
    harness      List, inspect, and check status across 19 AI agent harnesses
    detect       Auto-detect installed AI coding and autonomous agents
    diagnose     Check reachability, content drift, and broken symlinks
    doctor       Run full health check and optional --fix auto-repair
    matrix       Print the 19-harness compatibility and verification matrix

  Security & Agent Integration
    scan         Run static supply-chain & prompt-injection checks (JSON/SARIF)
    policy       Initialize, show, or enforce project skillporter.policy.yaml rules
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

    # new (skill scaffolding)
    nw = sub.add_parser(
        "new",
        parents=[shared_parent],
        help="scaffold a new spec-compliant skill directory",
    )
    nw.add_argument("name", help="skill name (lowercase alphanumeric with hyphens)")
    nw.add_argument("--path", default=".", help="parent directory to create skill inside (default: .)")
    nw.add_argument("--description", default="", help="skill description including trigger guidance")
    nw.add_argument("--author", default="developer", help="author metadata field")
    nw.add_argument("--with-scripts", action="store_true", help="include starter scripts/helper.py")
    nw.add_argument("--with-references", action="store_true", help="include starter references/guide.md")
    nw.add_argument("--with-tests", action="store_true", help="include starter skill.test.yaml")
    nw.add_argument("--force", action="store_true", help="overwrite existing skill directory")
    nw.add_argument("--format", choices=["text", "json"], default="")
    nw.add_argument("--json", action="store_true")
    nw.set_defaults(func=cmd_new)

    # lint (deep authoring & reference linter)
    ln = sub.add_parser(
        "lint",
        parents=[shared_parent],
        help="validate metadata, file references, scripts, limits, and security",
    )
    ln.add_argument("path", nargs="?", default=".", help="skill directory or workspace root")
    ln.add_argument("--harness", action="append", help="check token/capability limits for specific harness(es)")
    ln.add_argument("--strict", action="store_true", help="treat warnings as failures (exit code 1)")
    ln.add_argument("--format", choices=["text", "json"], default="")
    ln.add_argument("--json", action="store_true")
    ln.set_defaults(func=cmd_lint)

    # preview (native & adapted delivery preview)
    pv = sub.add_parser(
        "preview",
        parents=[shared_parent],
        help="preview exact native or adapted content each target harness receives",
    )
    pv.add_argument("target", help="installed skill name or path to skill directory")
    pv.add_argument("--harness", action="append", help="target harness(es) (e.g. cursor, claude-code, aider)")
    pv.add_argument("--adapt-format", default="", help="explicit adapted format override")
    pv.add_argument("--scope", choices=["project", "user"], default="project")
    pv.add_argument("--path", default=".", help="workspace root when resolving by skill name")
    pv.add_argument("--format", choices=["text", "json"], default="")
    pv.add_argument("--json", action="store_true")
    pv.set_defaults(func=cmd_preview)

    # test (skill.test.yaml activation & structural test runner)
    ts = sub.add_parser(
        "test",
        parents=[shared_parent],
        help="run skill.test.yaml trigger activation and structural checks",
    )
    ts.add_argument("path", nargs="?", default=".", help="skill directory, workspace root, or skill.test.yaml")
    ts.add_argument("--model", default="", help="optional LLM provider:model for model-assisted routing eval")
    ts.add_argument("--yes-send", action="store_true", help="authorize sending descriptions/prompts to --model API")
    ts.add_argument("--format", choices=["text", "json"], default="")
    ts.add_argument("--json", action="store_true")
    ts.set_defaults(func=cmd_test)

    # consolidate (multi-agent rules consolidation & bidirectional sync)
    cs = sub.add_parser(
        "consolidate",
        parents=[shared_parent],
        help="discover, deduplicate, conflict-check, and synchronize agent instruction files",
    )
    cs.add_argument("path", nargs="?", default=".", help="workspace root (default: .)")
    cs.add_argument("--harness", action="append", help="target harness(es) to generate native instruction files for")
    cs.add_argument("--apply", action="store_true", help="back up originals and write canonical.md + native files")
    cs.add_argument("--status", action="store_true", help="check managed instruction files for manual modifications")
    cs.add_argument("--reconcile", action="store_true", help="merge manual edits from agent files into canonical.md")
    cs.add_argument("--rollback", action="store_true", help="restore pre-consolidation original instruction files")
    cs.add_argument("--force", action="store_true", help="overwrite manually modified managed files")
    cs.add_argument("--format", choices=["text", "json"], default="")
    cs.add_argument("--json", action="store_true")
    cs.set_defaults(func=cmd_consolidate)

    # context (active harness instruction & skill stack inspector)
    cx = sub.add_parser(
        "context",
        parents=[shared_parent],
        help="inspect exact active instructions, ignored files, and skills loaded by a harness",
    )
    cx.add_argument("path", nargs="?", default=".", help="workspace root (default: .)")
    cx.add_argument("--harness", action="append", help="specific harness(es) to inspect")
    cx.add_argument("--scope", choices=["project", "user"], default="project")
    cx.add_argument("--format", choices=["text", "json"], default="")
    cx.add_argument("--json", action="store_true")
    cx.set_defaults(func=cmd_context)

    # policy {init,check,show}
    pol = sub.add_parser(
        "policy",
        parents=[shared_parent],
        help="manage and enforce project skillporter.policy.yaml rules",
    )
    pol.add_argument("--path", default=".")
    pol.add_argument("--format", choices=["text", "json"], default="")
    pol.add_argument("--json", action="store_true")
    pol_sub = pol.add_subparsers(dest="policy_action", required=False)

    pol_init = pol_sub.add_parser("init", parents=[shared_parent], help="create starter skillporter.policy.yaml")
    pol_init.add_argument("path", nargs="?", default=".")
    pol_init.add_argument("--force", action="store_true")
    pol_init.add_argument("--format", choices=["text", "json"], default="")
    pol_init.add_argument("--json", action="store_true")

    pol_chk = pol_sub.add_parser("check", parents=[shared_parent], help="evaluate installed skills against policy")
    pol_chk.add_argument("path", nargs="?", default=".")
    pol_chk.add_argument("--format", choices=["text", "json"], default="")
    pol_chk.add_argument("--json", action="store_true")

    pol_sh = pol_sub.add_parser("show", parents=[shared_parent], help="display active policy configuration")
    pol_sh.add_argument("path", nargs="?", default=".")
    pol_sh.add_argument("--format", choices=["text", "json"], default="")
    pol_sh.add_argument("--json", action="store_true")
    pol.set_defaults(func=cmd_policy)

    # suggest (smart local-first project skill recommendations)
    sg = sub.add_parser(
        "suggest",
        parents=[shared_parent],
        help="recommend relevant, security-graded skills based on local project stack",
    )
    sg.add_argument("path", nargs="?", default=".", help="workspace root (default: .)")
    sg.add_argument("--harness", action="append", help="filter compatibility for specific harness(es)")
    sg.add_argument("--format", choices=["text", "json"], default="")
    sg.add_argument("--json", action="store_true")
    sg.set_defaults(func=cmd_suggest)

    # insights (context cost & opt-in local usage insights)
    ig = sub.add_parser(
        "insights",
        parents=[shared_parent],
        help="measure skill and instruction token overhead and opt-in local usage",
    )
    ig.add_argument("path", nargs="?", default=".", help="workspace root (default: .)")
    ig.add_argument("--scope", choices=["project", "user"], default="project")
    ig.add_argument("--record-usage", default="", help="record a local opt-in activation event for <skill>")
    ig.add_argument("--harness-used", default="", help="optional harness ID for --record-usage")
    ig.add_argument("--format", choices=["text", "json"], default="")
    ig.add_argument("--json", action="store_true")
    ig.set_defaults(func=cmd_insights)
