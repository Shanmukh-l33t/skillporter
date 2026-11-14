"""Granular Harness Discovery, Inspection, and Status Commands (`skillporter harness`).

Distinguishes the five canonical harness states:
  1. Supported: Adapter exists in Skillporter's 19-harness registry.
  2. Compatible: NATIVE or COMPATIBLE SKILL.md support in the requested scope.
  3. Detected: Binary, user config dir, env var, or project marker found on this machine.
  4. Selected: Configured as an active target in ``skillporter.yaml`` / active profile.
  5. Configured: One or more valid skills are currently installed and reachable in this harness.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from .. import __version__, harnesses
from ..diagnose import diagnose as run_diagnose
from ..diagnose import load_custom_harness_paths, select_harness_install_raw_path
from ..manifest import load_manifest
from ..ui import BOLD, badge, render_next_steps, render_table, style
from .common import EXIT_ERROR, EXIT_OK, EXIT_PROBLEM, fmt_mode, is_quiet


def _collect_harness_records(root: Path, scope: str) -> list[dict[str, object]]:
    detected_map = {d.harness.name: d for d in harnesses.detect_harnesses(root, probe_versions=False)}
    diag = run_diagnose(root, scope=scope)
    manifest = load_manifest(root) if scope == "project" else None
    custom_paths = load_custom_harness_paths(root, scope=scope)

    selected_set: set[str] = set()
    if manifest and manifest.harnesses:
        for mh in manifest.harnesses:
            with contextlib.suppress(KeyError):
                selected_set.add(harnesses.get(mh).name)
    else:
        for name, det in detected_map.items():
            if det.project_active:
                selected_set.add(name)

    rows: list[dict[str, object]] = []
    for name in harnesses.names():
        h = harnesses.get(name)
        det = detected_map[name]
        rep = diag.reports.get(name)
        scoped_paths = h.project_paths if scope == "project" else h.user_paths
        has_scope_support = len(scoped_paths) > 0
        is_compatible = has_scope_support and h.support_status in ("NATIVE", "COMPATIBLE")
        reachable = sorted(rep.reachable_skills) if rep else []
        drifted = sorted(rep.drifted_skills) if rep else []
        duplicates = sorted(rep.duplicate_skills) if rep else []
        broken = [b for loc in (rep.locations if rep else []) for b in loc.broken_links]
        primary_raw = select_harness_install_raw_path(h, scope, custom_paths=custom_paths) or "(none)"

        rows.append(
            {
                "harness": h.name,
                "display_name": h.label,
                "category": h.category,
                "support_status": h.support_status,
                "verification_level": h.verification_level,
                "compatible": is_compatible,
                "scope_supported": has_scope_support,
                "detected": det.installed,
                "workspace_active": det.project_active,
                "selected": h.name in selected_set,
                "configured": len(reachable) > 0 and not broken,
                "skill_count": len(reachable),
                "skills": reachable,
                "drifted_skills": drifted,
                "duplicate_skills": duplicates,
                "broken_links": broken,
                "primary_path": primary_raw,
                "custom_path": custom_paths.get(h.name, ""),
                "reasons": det.reasons,
            }
        )
    return rows


def cmd_harness(args: argparse.Namespace) -> int:
    sub_action = getattr(args, "harness_action", None) or "list"
    if sub_action == "inspect":
        return cmd_harness_inspect(args)
    if sub_action == "status":
        return cmd_harness_status(args)
    return cmd_harness_list(args)


def cmd_harness_list(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    scope = getattr(args, "scope", "project")
    only_detected = bool(getattr(args, "detected", False))
    only_compatible = bool(getattr(args, "compatible", False))
    category = getattr(args, "category", None)

    records = _collect_harness_records(root, scope)
    filtered = []
    for r in records:
        if category and r["category"] != category:
            continue
        if only_detected and not r["detected"]:
            continue
        if only_compatible and not r["compatible"]:
            continue
        filtered.append(r)

    if fmt_mode(args) == "json":
        print(json.dumps({"root": str(root), "scope": scope, "harnesses": filtered}, indent=2))
        return EXIT_OK

    if is_quiet(args):
        for r in filtered:
            print(r["harness"])
        return EXIT_OK

    det_cnt = sum(1 for r in filtered if r["detected"])
    cfg_cnt = sum(1 for r in filtered if r["configured"])
    print(
        f"skillporter {__version__} · {len(filtered)} supported harness(es) "
        f"({det_cnt} detected, {cfg_cnt} configured in {scope} scope)\n"
    )
    table_rows = []
    for r in filtered:
        det_cell = "active" if r["workspace_active"] else ("yes" if r["detected"] else "-")
        sel_cell = "yes" if r["selected"] else "-"
        cfg_cell = f"yes ({r['skill_count']})" if r["configured"] else "-"
        table_rows.append(
            [
                str(r["harness"]),
                str(r["support_status"]),
                det_cell,
                sel_cell,
                cfg_cell,
                str(r["primary_path"]),
            ]
        )
    print(
        render_table(
            ["HARNESS", "SUPPORT", "DETECTED", "SELECTED", "CONFIGURED", "INSTALL PATH"],
            table_rows,
        )
    )
    return EXIT_OK


def cmd_harness_inspect(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    scope = getattr(args, "scope", "project")
    target = getattr(args, "target", "")
    try:
        h = harnesses.get(target)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    det_list = harnesses.detect_harnesses(root, probe_versions=True)
    det = next(d for d in det_list if d.harness.name == h.name)
    diag = run_diagnose(root, only=[h.name], scope=scope)
    rep = diag.reports[h.name]
    custom_paths = load_custom_harness_paths(root, scope=scope)
    primary_raw = select_harness_install_raw_path(h, scope, custom_paths=custom_paths)
    isolated_raw = select_harness_install_raw_path(h, scope, custom_paths=custom_paths, isolated=True)

    shared_peers: list[str] = []
    if primary_raw:
        for other_id in harnesses.names():
            if other_id == h.name:
                continue
            oh = harnesses.get(other_id)
            op = select_harness_install_raw_path(oh, scope, custom_paths=custom_paths)
            if op == primary_raw:
                shared_peers.append(oh.name)

    payload = {
        "harness": h.name,
        "display_name": h.label,
        "aliases": list(h.aliases),
        "category": h.category,
        "support_status": h.support_status,
        "verification_level": h.verification_level,
        "verified_date": h.verified_date,
        "docs": h.docs,
        "detected": det.installed,
        "workspace_active": det.project_active,
        "user_present": det.user_present,
        "binary": det.binary_path,
        "version": det.version,
        "detection_reasons": det.reasons,
        "scope": scope,
        "primary_install_path": primary_raw,
        "isolated_install_path": isolated_raw,
        "custom_path_override": custom_paths.get(h.name, ""),
        "shared_path_peers": shared_peers,
        "project_paths": [
            {"path": p.path, "compatibility": p.is_compatibility, "note": p.note} for p in h.project_paths
        ],
        "user_paths": [{"path": p.path, "compatibility": p.is_compatibility, "note": p.note} for p in h.user_paths],
        "capabilities": {
            "allowed_tools": h.capabilities.allowed_tools,
            "context_fork": h.capabilities.context_fork,
            "hooks": h.capabilities.hooks,
            "recursive_discovery": h.capabilities.recursive_discovery,
            "scripts_dir": h.capabilities.scripts_dir,
            "references_dir": h.capabilities.references_dir,
            "adapted_format": h.capabilities.adapted_format,
        },
        "reachable_skills": sorted(rep.reachable_skills),
        "drifted_skills": sorted(rep.drifted_skills),
        "duplicate_skills": rep.duplicate_skills,
        "notes": list(h.notes),
        "limitations": list(h.limitations),
    }

    if fmt_mode(args) == "json":
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    print(f"{style(h.label, BOLD)} ({h.name})")
    print(f"  Support:        {badge(h.support_status)} ({h.verification_level}, verified {h.verified_date})")
    print(f"  Category:       {h.category}" + (f" · aliases: {', '.join(h.aliases)}" if h.aliases else ""))
    det_label = "YES" if det.installed else "NO"
    ev = ", ".join(det.reasons) if det.reasons else "not detected on this machine"
    if det.version:
        ev += f" ({det.version})"
    print(f"  Detected:       {badge(det_label)} ({ev})")
    print(f"  Install path:   {primary_raw or '(none)'} (scope: {scope})")
    if isolated_raw and isolated_raw != primary_raw:
        print(f"  Isolated path:  {isolated_raw} (via --isolated)")
    if shared_peers:
        print(f"  Shared peers:   {', '.join(shared_peers)} (also read {primary_raw})")
    caps = [
        k
        for k, v in payload["capabilities"].items()  # type: ignore[union-attr]
        if v is True
    ]
    if h.capabilities.adapted_format:
        caps.append(f"adapt:{h.capabilities.adapted_format}")
    print(f"  Capabilities:   {', '.join(caps) if caps else 'basic_skills'}")
    print(f"  Loaded skills:  {', '.join(sorted(rep.reachable_skills)) or '(none)'}")
    print(f"  Docs:           {h.docs}")
    for n in h.notes:
        print(f"  Note:           {n}")
    for lim in h.limitations:
        print(f"  Limitation:     {lim}")
    return EXIT_OK


def cmd_harness_status(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "path", ".") or ".").expanduser().resolve()
    scope = getattr(args, "scope", "project")
    records = _collect_harness_records(root, scope)
    active_rows = [r for r in records if r["detected"] or r["selected"] or r["configured"]]
    issues: list[str] = []
    for r in records:
        if r["broken_links"]:
            issues.append(f"{r['harness']}: {len(r['broken_links'])} broken symlink(s)")  # type: ignore[arg-type]
        if r["drifted_skills"]:
            issues.append(
                f"{r['harness']}: content drift in {', '.join(r['drifted_skills'])}"  # type: ignore[arg-type]
            )
        if r["duplicate_skills"]:
            issues.append(
                f"{r['harness']}: duplicate skill paths for {', '.join(r['duplicate_skills'])}"  # type: ignore[arg-type]
            )

    healthy = len(issues) == 0
    if fmt_mode(args) == "json":
        print(
            json.dumps(
                {
                    "root": str(root),
                    "scope": scope,
                    "healthy": healthy,
                    "active_harnesses": active_rows,
                    "issues": issues,
                },
                indent=2,
            )
        )
        return EXIT_OK if healthy else EXIT_PROBLEM

    print(f"skillporter {__version__} · harness status for {root} (scope: {scope})\n")
    if not active_rows:
        print("No harnesses detected or configured yet.")
        print("\n" + render_next_steps(["skillporter harness list          # view all 19 supported harnesses"]))
        return EXIT_OK

    trows = []
    for r in active_rows:
        state_str = "HEALTHY"
        if r["broken_links"] or r["drifted_skills"]:
            state_str = "DRIFTED"
        elif r["duplicate_skills"]:
            state_str = "DUPLICATE"
        elif r["configured"]:
            state_str = "CONFIGURED"
        elif r["selected"]:
            state_str = "SELECTED"
        else:
            state_str = "DETECTED"
        skills_preview = ", ".join(r["skills"][:4])  # type: ignore[index]
        if len(r["skills"]) > 4:  # type: ignore[arg-type]
            skills_preview += f" (+{len(r['skills']) - 4} more)"  # type: ignore[arg-type]
        trows.append(
            [
                str(r["harness"]),
                state_str,
                str(r["skill_count"]),
                str(r["primary_path"]),
                skills_preview or "(none)",
            ]
        )
    print(render_table(["HARNESS", "STATE", "SKILLS", "PATH", "REACHABLE SKILLS"], trows))
    if issues:
        print("\nAttention:")
        for iss in issues:
            print(f"  ! {iss}")
        print(
            "\n" + render_next_steps(["skillporter doctor --fix          # repair broken links and missing installs"])
        )
    return EXIT_OK if healthy else EXIT_PROBLEM
