"""Shared CLI command helpers, exit-code constants, and harness target resolution."""

from __future__ import annotations

import argparse
import contextlib
from pathlib import Path

from .. import harnesses
from ..manifest import load_manifest

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_ERROR = 2


def fmt_mode(args: argparse.Namespace) -> str:
    fmt = str(getattr(args, "format", "") or "").strip().lower()
    if fmt in ("json", "sarif", "text", "markdown"):
        return fmt
    if getattr(args, "json", False):
        return "json"
    return "text"


def resolve_target_harnesses(
    raw_harnesses: list[str] | None,
    root: Path,
    *,
    scope: str = "project",
    default_detected: bool = True,
) -> list[str]:
    """Resolve ``--harness`` arguments, supporting ``all``, ``detected``, and auto-detection."""
    if raw_harnesses:
        expanded: list[str] = []
        for item in raw_harnesses:
            for part in item.split(","):
                tok = part.strip().lower()
                if not tok:
                    continue
                if tok == "all":
                    all_scoped = [
                        n
                        for n in harnesses.names()
                        if (harnesses.get(n).project_paths if scope == "project" else harnesses.get(n).user_paths)
                    ]
                    expanded.extend(all_scoped)
                elif tok == "detected":
                    detected = [
                        d.harness.name
                        for d in harnesses.detect_harnesses(root)
                        if d.installed and (d.harness.project_paths if scope == "project" else d.harness.user_paths)
                    ]
                    expanded.extend(detected if detected else ["claude-code", "codex", "cursor"])
                else:
                    expanded.append(harnesses.get(tok).name)
        seen: list[str] = []
        for h in expanded:
            if h not in seen:
                seen.append(h)
        return seen

    if default_detected:
        manifest = load_manifest(root)
        if manifest and manifest.harnesses:
            return [harnesses.get(h).name for h in manifest.harnesses]
        detected = [
            d.harness.name
            for d in harnesses.detect_harnesses(root)
            if d.project_active and (d.harness.project_paths if scope == "project" else d.harness.user_paths)
        ]
        if detected:
            return detected
    return ["claude-code", "codex", "cursor"]


def latest_tree_mtime_ns(skill_dir: Path) -> int:
    """Return the maximum modification timestamp (in ns) across all files in *skill_dir*."""
    latest = 0
    for fpath in skill_dir.rglob("*"):
        if fpath.is_symlink():
            continue
        with contextlib.suppress(OSError):
            ns = fpath.stat().st_mtime_ns
            if ns > latest:
                latest = ns
    return latest
