"""CLI commands for smart recommendations (`suggest`) and context/usage insights (`insights`)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..insights import compute_workspace_insights, record_skill_usage_event
from ..install import InstallError
from ..suggest import recommend_skills_for_project
from ..ui import BOLD, DIM, action_symbol, render_next_steps, render_table, style
from .common import EXIT_ERROR, EXIT_OK, fmt_mode, is_quiet, resolve_target_harnesses


def cmd_suggest(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return EXIT_ERROR

    try:
        pref_h = (
            resolve_target_harnesses(args.harness, root, default_detected=False)
            if getattr(args, "harness", None)
            else None
        )
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    res = recommend_skills_for_project(root, preferred_harnesses=pref_h)
    if fmt_mode(args) == "json":
        print(json.dumps(res, indent=2))
        return EXIT_OK

    stack: list[dict[str, str]] = res["detected_stack"]  # type: ignore[assignment]
    recs: list[dict[str, object]] = res["recommendations"]  # type: ignore[assignment]

    if is_quiet(args):
        for r in recs:
            print(r["source"])
        return EXIT_OK

    if not stack:
        print(f"No specific framework, database, or CI signals detected in {root}.")
        print("Run `skillporter search` to browse the full catalog.")
        return EXIT_OK

    sig_summary = ", ".join(f"{s['label']} ({s['evidence']})" for s in stack)
    print(f"Local project analysis for {style(str(root), BOLD)} (100% local, zero uploads):")
    print(f"  Detected stack: {sig_summary}\n")

    if not recs:
        print("All matching curated skills are already installed in this workspace.")
        return EXIT_OK

    print(f"Recommended skills ({len(recs)}):")
    for r in recs:
        h_str = ", ".join(r["compatible_harnesses"][:5])  # type: ignore[index]
        scan_note = f"verified seed · risk {r['risk_score']}/100" if r["security_scanned"] else "scan on install"
        print(f"\n  {action_symbol('added')} {style(str(r['title']), BOLD)} ({r['source']}@{r['version']})")
        print(f"      Why relevant:   {r['why_relevant']}")
        print(f"      Solves:         {r['problem_solved']}")
        print(f"      Harnesses:      {h_str}")
        print(f"      Security:       {scan_note}")
        print(f"      Limitations:    {r['limitations']}")
        print(f"      Install:        {r['install_command']}")

    return EXIT_OK


def cmd_insights(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return EXIT_ERROR

    scope = getattr(args, "scope", "project")
    rec_skill = (getattr(args, "record_usage", "") or "").strip()
    if rec_skill:
        try:
            ufile = record_skill_usage_event(
                root,
                rec_skill,
                harness=getattr(args, "harness_used", "") or "",
                scope=scope,
            )
        except InstallError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR
        if fmt_mode(args) == "json":
            print(json.dumps({"recorded": rec_skill, "usage_file": str(ufile)}, indent=2))
        elif not is_quiet(args):
            print(f"{action_symbol('added')} Recorded local usage event for {rec_skill!r} in {ufile}")
        return EXIT_OK

    rep = compute_workspace_insights(root, scope=scope)
    if fmt_mode(args) == "json":
        print(json.dumps(rep, indent=2))
        return EXIT_OK

    if is_quiet(args):
        print(rep["total_estimated_skill_tokens"])
        return EXIT_OK

    print(f"Context & Usage Insights for {style(str(root), BOLD)} ({scope} scope)")
    print(
        f"  Skill index overhead (always loaded): ~{rep['always_loaded_skill_index_tokens']} estimated tokens"
    )
    print(f"  Total skill body overhead:            ~{rep['total_estimated_skill_tokens']} estimated tokens")
    if scope == "project":
        print(
            f"  Agent instruction files overhead:     ~{rep['total_instruction_tokens']} estimated tokens "
            f"(overlap: {rep['instruction_overlap_percentage']}%)"
        )
    usage_status = "active (local opt-in usage.jsonl)" if rep["usage_tracking_active"] else "inactive (estimates only)"
    print(f"  Usage tracking:                       {usage_status}")

    skills_map: dict[str, dict[str, object]] = rep["skills"]  # type: ignore[assignment]
    if skills_map:
        trows = []
        for sname, sinfo in sorted(
            skills_map.items(),
            key=lambda kv: int(kv[1]["estimated_tokens"]),  # type: ignore[arg-type]
            reverse=True,
        ):
            ucell = str(sinfo["usage_count"]) if sinfo["usage_count"] is not None else "n/a"
            h_list: list[str] = sinfo["harnesses"]  # type: ignore[assignment]
            hcell = ", ".join(h_list[:3]) + (f" (+{len(h_list) - 3})" if len(h_list) > 3 else "")
            flag = "LARGE" if sinfo["oversized"] else ("DUP" if sinfo["duplicate_harnesses"] else "ok")
            trows.append([sname, f"~{sinfo['estimated_tokens']}", ucell, flag, hcell or "(none)"])
        print("\n" + render_table(["SKILL", "EST. TOKENS", "USES", "STATUS", "HARNESSES"], trows, indent="  "))

    opts: list[str] = rep["optimization_opportunities"]  # type: ignore[assignment]
    if opts:
        print("\nOptimization opportunities:")
        for op in opts:
            print(f"  ! {op}")
        print(
            "\n"
            + render_next_steps(
                [
                    "skillporter consolidate             # deduplicate overlapping agent instructions",
                    "skillporter context --harness codex # inspect startup context per harness",
                ]
            )
        )
    print(
        style(
            "\nNote: Token counts are deterministic 4-char/token estimates; usage counts reflect "
            "only opt-in local events in .skillporter/usage.jsonl (zero external telemetry).",
            DIM,
        )
    )
    return EXIT_OK
