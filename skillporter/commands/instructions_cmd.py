"""CLI commands for rules consolidation (`consolidate`) and active harness context (`context`)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..instructions import (
    InstructionError,
    analyze_instructions,
    apply_consolidation,
    detect_manual_instruction_modifications,
    inspect_harness_context,
    rollback_consolidation,
)
from ..ui import BOLD, action_symbol, badge, render_next_steps, render_table, style
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode, is_quiet, is_verbose, resolve_target_harnesses


def cmd_consolidate(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return EXIT_ERROR

    is_json = fmt_mode(args) == "json"
    do_rollback = bool(getattr(args, "rollback", False))
    do_status = bool(getattr(args, "status", False))
    do_reconcile = bool(getattr(args, "reconcile", False))
    do_apply = bool(getattr(args, "apply", False)) or do_reconcile
    force = bool(getattr(args, "force", False))

    try:
        target_h = (
            resolve_target_harnesses(args.harness, root, default_detected=False)
            if getattr(args, "harness", None)
            else None
        )
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if do_rollback:
        try:
            res_rb = rollback_consolidation(root)
        except InstructionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_PROBLEM
        if is_json:
            print(json.dumps(res_rb, indent=2))
            return EXIT_OK
        if not is_quiet(args):
            print(
                f"{action_symbol('rolled-back')} Restored {len(res_rb['restored_files'])} original instruction file(s) "  # type: ignore[arg-type]
                f"from {res_rb['backup_dir']}"
            )
        return EXIT_OK

    if do_status:
        mods = detect_manual_instruction_modifications(root)
        healthy = len(mods) == 0
        payload = {"root": str(root), "healthy": healthy, "manual_modifications": mods}
        if is_json:
            print(json.dumps(payload, indent=2))
            return EXIT_OK if healthy else EXIT_PROBLEM
        if healthy:
            print(f"Instruction status: {badge('SYNCED')} (0 manual modifications detected).")
            return EXIT_OK
        print(f"Instruction status: {badge('DRIFTED')} ({len(mods)} manual modification(s) detected):")
        for m in mods:
            print(f"  ! {m['file']} ({m['status']})")
            for ad in m.get("added_directives", []):  # type: ignore[union-attr]
                print(f"      + {ad}")
            for rd in m.get("removed_directives", []):  # type: ignore[union-attr]
                print(f"      - {rd}")
        print(
            "\n"
            + render_next_steps(
                [
                    "skillporter consolidate --reconcile  # merge manual edits into canonical.md and re-sync",
                    "skillporter consolidate --apply --force  # overwrite agent files from canonical.md",
                ]
            )
        )
        return EXIT_PROBLEM

    if do_apply:
        try:
            res_ap = apply_consolidation(
                root,
                target_harnesses=target_h,
                force=force,
                reconcile=do_reconcile,
            )
        except InstructionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_PROBLEM
        if is_json:
            print(json.dumps(res_ap, indent=2))
            return EXIT_OK
        if not is_quiet(args):
            verb = "Reconciled and synchronized" if do_reconcile else "Consolidated"
            print(
                f"{action_symbol('synced')} {verb} {res_ap['shared_count']} shared instruction(s) "
                f"across {len(res_ap['written_files'])} native file(s)"  # type: ignore[arg-type]
            )
            print(f"  Canonical source: {res_ap['canonical_path']}")
            print(f"  Backup snapshot:  {res_ap['backup_dir']}")
            for wf in res_ap["written_files"]:  # type: ignore[union-attr]
                print(f"  ~ {wf}")
        return EXIT_OK

    # Default read-only discovery & preview report
    report = analyze_instructions(root, target_harnesses=target_h)
    if is_json:
        print(json.dumps(report, indent=2))
        return EXIT_OK

    files: list[dict[str, object]] = report["discovered_files"]  # type: ignore[assignment]
    if not files:
        print(f"No agent instruction files discovered in {root}.")
        return EXIT_OK

    agents = report["agents_covered"]
    print(
        f"Discovered {style(str(len(files)), BOLD)} instruction file(s) across "
        f"{len(agents)} agent(s) ({', '.join(agents)})"  # type: ignore[arg-type]
    )
    print(f"  Overlapping content:          {report['overlap_percentage']}%")
    print(f"  Shared directives:            {len(report['shared_instructions'])}")  # type: ignore[arg-type]
    print(f"  Agent-specific groups:        {len(report['agent_specific_instructions'])}")  # type: ignore[arg-type]
    print(f"  Potential conflicts:          {len(report['conflicts'])}")  # type: ignore[arg-type]
    print(f"  Potentially outdated refs:    {len(report['outdated_instructions'])}")  # type: ignore[arg-type]
    n_uncls = len(report.get("unclassified_sections", []))  # type: ignore[arg-type]
    if n_uncls:
        print(f"  Unclassified lines (kept verbatim): {n_uncls}")

    trows = [
        [
            str(f["path"]),
            ", ".join(f["harnesses"][:3]) + (f" (+{len(f['harnesses']) - 3})" if len(f["harnesses"]) > 3 else ""),  # type: ignore[index,arg-type]
            str(f["directive_count"]),
            f"~{f['estimated_tokens']}",
            "yes" if f["managed"] else "no",
        ]
        for f in files
    ]
    print("\n" + render_table(["FILE", "TARGET AGENTS", "DIRECTIVES", "TOKENS", "MANAGED"], trows, indent="  "))

    for conf in report["conflicts"]:  # type: ignore[union-attr]
        print(f"\n  ! Conflict: {conf['summary']}")
        print(f"      {conf['file_a']}: {conf['directive_a']}")
        print(f"      {conf['file_b']}: {conf['directive_b']}")

    for outd in report["outdated_instructions"]:  # type: ignore[union-attr]
        print(f"\n  ! Outdated ref ({outd['file']}): `{outd['reference']}` ({outd['reason']})")

    if is_verbose(args):
        for rel_p, content in report["proposed_outputs"].items():  # type: ignore[union-attr]
            print(f"\nProposed output ({rel_p}):")
            for ln in str(content).splitlines()[:25]:
                print(f"  {ln}")

    print(
        "\n"
        + render_next_steps(
            [
                "skillporter consolidate --verbose       # preview generated native files",
                "skillporter consolidate --apply         # back up originals and write canonical.md + targets",
            ]
        )
    )
    return EXIT_OK


def cmd_context(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return EXIT_ERROR

    scope = getattr(args, "scope", "project")
    raw_h = getattr(args, "harness", None)
    try:
        targets = resolve_target_harnesses(raw_h, root, scope=scope, default_detected=True)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    snapshots = [inspect_harness_context(root, h, scope=scope) for h in targets]
    payload = snapshots[0] if (raw_h and len(snapshots) == 1) else {"root": str(root), "harnesses": snapshots}

    if fmt_mode(args) == "json":
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    for idx, snap in enumerate(snapshots):
        if idx > 0:
            print()
        tsum = snap["token_summary"]
        print(
            f"{style(str(snap['display_name']), BOLD)} ({snap['harness']}) · "
            f"startup ~{tsum['always_loaded_startup_tokens']} tokens "  # type: ignore[index]
            f"(+{tsum['max_on_activation_skill_tokens']} skill body tokens on activation)"  # type: ignore[index]
        )
        act_i = snap["active_instructions"]
        if act_i:
            for item in act_i:  # type: ignore[union-attr]
                print(f"  + instruction: {item['path']} (~{item['estimated_tokens']} tokens, {item['scope_kind']})")
        else:
            print("  - active instructions: (none)")

        ign_i = snap["ignored_instructions"]
        if ign_i:
            ign_names = ", ".join(str(x["path"]) for x in ign_i)  # type: ignore[union-attr]
            print(f"  ! ignored in {snap['harness']}: {ign_names}")

        act_s = snap["active_skills"]
        if act_s:
            s_names = ", ".join(f"{x['name']} (~{x['on_activation_body_tokens']}t)" for x in act_s[:6])  # type: ignore[index]
            if len(act_s) > 6:  # type: ignore[arg-type]
                s_names += f" (+{len(act_s) - 6} more)"  # type: ignore[arg-type]
            print(f"  + skills ({len(act_s)}): {s_names}")  # type: ignore[arg-type]
        else:
            print("  - skills: (none)")

    return EXIT_OK
