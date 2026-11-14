"""CLI commands for skill authoring, deep linting, native harness preview, and testing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import harnesses
from ..authoring import (
    AuthoringError,
    create_skill_scaffold,
    lint_skill_dir,
    preview_skill_for_harness,
    resolve_skill_dir_for_inspection,
    run_skill_tests,
)
from ..frontmatter import discover
from ..ui import BOLD, DIM, action_symbol, badge, render_next_steps, render_table, style
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode, is_quiet, is_verbose, resolve_target_harnesses


def cmd_new(args: argparse.Namespace) -> int:
    base_dir = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    try:
        res = create_skill_scaffold(
            base_dir,
            args.name,
            description=getattr(args, "description", "") or "",
            author=getattr(args, "author", "developer") or "developer",
            with_scripts=bool(getattr(args, "with_scripts", False)),
            with_references=bool(getattr(args, "with_references", False)),
            with_tests=bool(getattr(args, "with_tests", False)),
            force=bool(getattr(args, "force", False)),
        )
    except AuthoringError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if fmt_mode(args) == "json":
        print(json.dumps(res, indent=2))
        return EXIT_OK

    if is_quiet(args):
        print(res["skill_dir"])
        return EXIT_OK

    print(f"{action_symbol('created')} Created skill {style(str(res['name']), BOLD)} at {res['skill_dir']}")
    for rel in res["created_files"]:  # type: ignore[union-attr]
        print(f"  + {rel}")
    sdir = res["skill_dir"]
    print(
        "\n"
        + render_next_steps(
            [
                f"skillporter lint {sdir}                         # validate metadata, links, and security",
                f"skillporter preview {sdir} --harness cursor     # preview native and adapted formats",
                f"skillporter install {sdir} --harness detected   # install into active harnesses",
            ]
        )
    )
    return EXIT_OK


def cmd_lint(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return EXIT_ERROR

    strict = bool(getattr(args, "strict", False))
    try:
        target_h = (
            resolve_target_harnesses(args.harness, target, default_detected=False)
            if getattr(args, "harness", None)
            else None
        )
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if target.is_file() and target.name == "SKILL.md":
        skill_dirs = [target.parent]
    elif (target / "SKILL.md").is_file():
        skill_dirs = [target]
    else:
        skill_dirs = [p.parent for p in discover(target)]

    if not skill_dirs:
        if fmt_mode(args) == "json":
            print(json.dumps({"passed": True, "error_count": 0, "warning_count": 0, "skills": {}}, indent=2))
        elif not is_quiet(args):
            print(f"no SKILL.md found under {target} (0 lint issues).")
        return EXIT_OK

    reports = {d.name: lint_skill_dir(d, target_harnesses=target_h) for d in skill_dirs}
    err_total = sum(r.error_count for r in reports.values())
    warn_total = sum(r.warning_count for r in reports.values())
    passed = all(r.passed(strict=strict) for r in reports.values())

    if fmt_mode(args) == "json":
        print(
            json.dumps(
                {
                    "passed": passed,
                    "strict": strict,
                    "error_count": err_total,
                    "warning_count": warn_total,
                    "skills": {k: v.to_dict(strict=strict) for k, v in reports.items()},
                },
                indent=2,
            )
        )
        return EXIT_OK if passed else EXIT_PROBLEM

    if is_quiet(args):
        return EXIT_OK if passed else EXIT_PROBLEM

    for sname, rep in reports.items():
        st = badge("PASSED" if rep.passed(strict=strict) else "FAILED")
        print(
            f"{style(sname, BOLD)}: {st}  "
            f"(~{rep.estimated_tokens} body tokens · risk {rep.risk_score}/100 · "
            f"{rep.error_count} error(s), {rep.warning_count} warning(s))"
        )
        for iss in rep.issues:
            print(f"  {iss}")

    return EXIT_OK if passed else EXIT_PROBLEM


def cmd_preview(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    scope = getattr(args, "scope", "project")
    fmt_override = getattr(args, "adapt_format", None) or None

    try:
        skill_dir = resolve_skill_dir_for_inspection(args.target, root, scope=scope)
    except AuthoringError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    raw_harness = getattr(args, "harness", None)
    if raw_harness:
        try:
            selected = resolve_target_harnesses(raw_harness, root, scope=scope, default_detected=False)
        except KeyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR

        previews = [
            preview_skill_for_harness(skill_dir, h, scope=scope, adapt_format_override=fmt_override)
            for h in selected
        ]
        payload = previews[0] if len(previews) == 1 else {"skill": skill_dir.name, "previews": previews}
        if fmt_mode(args) == "json":
            print(json.dumps(payload, indent=2))
            return EXIT_OK

        for idx, prev in enumerate(previews):
            if idx > 0:
                print("\n" + ("-" * 60))
            print(
                f"{style(str(prev['display_name']), BOLD)} ({prev['harness']}) · "
                f"{badge(str(prev['support_status']))} · {prev['verification_level']}"
            )
            print(f"  Native path:  {prev['native_target_path']}")
            print(f"  Body tokens:  ~{prev['estimated_body_tokens']} estimated tokens")
            if prev["information_lost"]:
                print("  Compatibility / translation notes:")
                for loss in prev["information_lost"]:  # type: ignore[union-attr]
                    print(f"    ! {loss}")
            adap = prev["adapted_preview"]
            if isinstance(adap, dict):
                print(f"\n  Adapted output ({adap['format']} -> {adap['path']}):")
                lines = str(adap["content"]).splitlines()
                shown = lines if is_verbose(args) else lines[:30]
                for ln in shown:
                    print(f"    {ln}")
                if len(shown) < len(lines):
                    print(f"    ... ({len(lines) - len(shown)} more lines; pass --verbose for full output)")
            else:
                print(f"\n  Delivered content ({prev['native_target_path']}):")
                lines = str(prev["native_content"]).splitlines()
                shown = lines if is_verbose(args) else lines[:30]
                for ln in shown:
                    print(f"    {ln}")
                if len(shown) < len(lines):
                    print(f"    ... ({len(lines) - len(shown)} more lines; pass --verbose for full output)")
        return EXIT_OK

    # Summary preview across configured / core harnesses when --harness is omitted
    summary_targets = resolve_target_harnesses(None, root, scope=scope, default_detected=True)
    rows = []
    previews_all = []
    for hname in summary_targets:
        p = preview_skill_for_harness(skill_dir, hname, scope=scope)
        previews_all.append(p)
        adap = p["adapted_preview"]
        adap_path = str(adap["path"]) if isinstance(adap, dict) else "-"
        loss_cnt = len(p["information_lost"])  # type: ignore[arg-type]
        loss_str = f"{loss_cnt} note(s)" if loss_cnt else "none"
        rows.append([hname, str(p["support_status"]), str(p["native_target_path"]), adap_path, loss_str])

    if fmt_mode(args) == "json":
        print(json.dumps({"skill": skill_dir.name, "previews": previews_all}, indent=2))
        return EXIT_OK

    print(f"Preview for skill {style(skill_dir.name, BOLD)} ({scope} scope):\n")
    print(render_table(["HARNESS", "SUPPORT", "NATIVE PATH", "ADAPTED RULE PATH", "LOSS / NOTES"], rows))
    print(f"\nTip: run `skillporter preview {args.target} --harness <id>` to inspect exact file content.")
    for h_extra in ("cursor", "github-copilot", "aider"):
        if h_extra in harnesses.HARNESSES and h_extra not in summary_targets:
            break
    return EXIT_OK


def cmd_test(args: argparse.Namespace) -> int:
    target = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    model = getattr(args, "model", "") or ""
    yes_send = bool(getattr(args, "yes_send", False))

    try:
        res = run_skill_tests(target, model=model, authorize_remote=yes_send)
    except AuthoringError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if fmt_mode(args) == "json":
        print(json.dumps(res, indent=2))
        return EXIT_OK if res["passed"] else EXIT_PROBLEM

    if is_quiet(args):
        return EXIT_OK if res["passed"] else EXIT_PROBLEM

    verdict = badge("PASSED" if res["passed"] else "FAILED")
    print(f"Skill test run [{verdict}]  (mode: {res['evaluation_mode']})")
    for suite in res["suites"]:  # type: ignore[union-attr]
        s_badge = badge("PASSED" if suite["passed"] else "FAILED")
        exp_cnt = len(suite["expected_activations"])
        miss_cnt = len(suite["missed_activations"])
        fp_cnt = len(suite["false_positives"])
        tn_cnt = len(suite["true_negatives"])
        print(
            f"  {style(str(suite['skill']), BOLD)}: {s_badge}  "
            f"(triggers: {exp_cnt}/{exp_cnt + miss_cnt} matched · "
            f"non-triggers: {tn_cnt}/{tn_cnt + fp_cnt} rejected)"
        )
        for serr in suite["structural_errors"]:
            print(f"    x structural: {serr}")
        for miss in suite["missed_activations"]:
            unmatched = ", ".join(miss.get("unmatched_terms", [])[:5])
            hint = f" (missing domain terms in description: {unmatched})" if unmatched else ""
            print(f"    x missed trigger: {miss['prompt']!r}{hint}")
        for fp in suite["false_positives"]:
            ov = ", ".join(fp.get("overlapping_terms", [])[:5])
            hint = f" (overlapped on: {ov})" if ov else ""
            print(f"    x false positive: {fp['prompt']!r}{hint}")

    print(style(f"\nNote: {res['disclaimer']}", DIM))
    return EXIT_OK if res["passed"] else EXIT_PROBLEM
