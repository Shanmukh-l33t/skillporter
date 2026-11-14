"""CLI command for project security policy management (`skillporter policy`)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..diagnose import diagnose
from ..policy import POLICY_FILENAME, PolicyConfig, evaluate_policy, load_policy, save_policy
from ..state import load_state
from ..ui import BOLD, action_symbol, badge, render_next_steps, style
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode, is_quiet


def cmd_policy(args: argparse.Namespace) -> int:
    action = getattr(args, "policy_action", None) or "check"
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return EXIT_ERROR

    if action == "init":
        pfile = root / POLICY_FILENAME
        if pfile.exists() and not getattr(args, "force", False):
            print(f"error: {pfile} already exists (pass --force to overwrite)", file=sys.stderr)
            return EXIT_ERROR
        default_cfg = PolicyConfig(
            block_severity="HIGH",
            max_risk_score=50,
            require_declared_capabilities=False,
            require_pinned_refs=False,
        )
        saved = save_policy(root, default_cfg)
        if fmt_mode(args) == "json":
            print(json.dumps({"policy_file": str(saved), "policy": default_cfg.to_dict()}, indent=2))
            return EXIT_OK
        if not is_quiet(args):
            print(f"{action_symbol('created')} Initialized {style(str(saved), BOLD)}")
        return EXIT_OK

    policy = load_policy(root)
    if action == "show":
        if policy is None:
            if fmt_mode(args) == "json":
                print(json.dumps({"present": False, "policy": None}, indent=2))
            else:
                print(f"No {POLICY_FILENAME} found in {root} (run `skillporter policy init`).")
            return EXIT_OK
        if fmt_mode(args) == "json":
            print(json.dumps({"present": True, "policy": policy.to_dict()}, indent=2))
        else:
            print(policy.to_yaml(), end="")
        return EXIT_OK

    # `policy check`
    if policy is None:
        if fmt_mode(args) == "json":
            print(json.dumps({"present": False, "passed": True, "violations": []}, indent=2))
        elif not is_quiet(args):
            print(f"No {POLICY_FILENAME} present in {root} (0 policy violations).")
        return EXIT_OK

    diag = diagnose(root, scope="project")
    records = load_state(root, scope="project")
    violations: list[str] = []
    for sname, copies in sorted(diag.skill_copies.items()):
        rec = records.get(sname)
        srcs = [rec.source] if (rec and rec.source) else []
        rec_harnesses = set(rec.harnesses) if rec else set()
        harnesses_used = sorted(h for h, rep in diag.reports.items() if rep.loads(sname) and h in rec_harnesses)
        v_list = evaluate_policy(
            policy,
            skill_dirs=[copies[0]],
            source_candidates=srcs,
            resolved_commit=rec.resolved_commit if rec else "",
            target_harnesses=harnesses_used,
        )
        violations.extend(v_list)

    passed = len(violations) == 0
    if fmt_mode(args) == "json":
        print(
            json.dumps(
                {
                    "present": True,
                    "policy_file": str(root / POLICY_FILENAME),
                    "passed": passed,
                    "skills_checked": sorted(diag.skill_copies),
                    "violations": violations,
                },
                indent=2,
            )
        )
        return EXIT_OK if passed else EXIT_PROBLEM

    if is_quiet(args):
        return EXIT_OK if passed else EXIT_PROBLEM

    verdict = badge("PASSED" if passed else "FAILED")
    print(f"Policy check ({POLICY_FILENAME}) [{verdict}] · {len(diag.skill_copies)} skill(s) checked")
    for v in violations:
        print(f"  x {v}")
    if violations:
        print("\n" + render_next_steps(["skillporter scan .          # inspect detailed finding evidence"]))
    return EXIT_OK if passed else EXIT_PROBLEM
