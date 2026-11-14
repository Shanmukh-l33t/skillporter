"""Shared CLI command helpers, exit-code constants, UI flags, and harness target resolution."""

from __future__ import annotations

import argparse
import contextlib
from pathlib import Path

from .. import harnesses
from ..diagnose import load_custom_harness_paths, select_harness_install_raw_path
from ..manifest import load_manifest
from ..ui import set_no_color

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_ERROR = 2


def apply_ui_flags(args: argparse.Namespace) -> None:
    """Apply global CLI presentation flags such as ``--no-color``."""
    set_no_color(bool(getattr(args, "no_color", False)))


def fmt_mode(args: argparse.Namespace) -> str:
    apply_ui_flags(args)
    fmt = str(getattr(args, "format", "") or "").strip().lower()
    if fmt in ("json", "sarif", "text", "markdown"):
        return fmt
    if getattr(args, "json", False):
        return "json"
    return "text"


def is_quiet(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "quiet", False))


def is_verbose(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "verbose", False))


def parse_custom_path_args(raw_pairs: list[str] | None) -> dict[str, str]:
    """Parse repeatable ``--custom-path harness=rel/dir`` arguments."""
    out: dict[str, str] = {}
    if not raw_pairs:
        return out
    for raw in raw_pairs:
        for item in raw.split(","):
            part = item.strip()
            if not part:
                continue
            if "=" not in part:
                raise ValueError(f"invalid --custom-path {part!r}; expected HARNESS=RELATIVE_PATH")
            hk, _, hp = part.partition("=")
            h = harnesses.get(hk.strip())
            out[h.name] = hp.strip()
    return out


def _expand_harness_tokens(
    raw_items: list[str],
    root: Path,
    *,
    scope: str,
) -> list[str]:
    expanded: list[str] = []
    for item in raw_items:
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
            elif tok == "compatible":
                compat_scoped = [
                    n
                    for n in harnesses.names()
                    if harnesses.get(n).support_status in ("NATIVE", "COMPATIBLE")
                    and (harnesses.get(n).project_paths if scope == "project" else harnesses.get(n).user_paths)
                ]
                expanded.extend(compat_scoped)
            elif tok == "detected":
                detected = [
                    d.harness.name
                    for d in harnesses.detect_harnesses(root)
                    if d.installed
                    and (d.harness.project_paths if scope == "project" else d.harness.user_paths)
                ]
                expanded.extend(detected if detected else ["claude-code", "codex", "cursor"])
            else:
                expanded.append(harnesses.get(tok).name)
    seen: list[str] = []
    for h in expanded:
        if h not in seen:
            seen.append(h)
    return seen


def resolve_target_harnesses(
    raw_harnesses: list[str] | None,
    root: Path,
    *,
    scope: str = "project",
    default_detected: bool = True,
    exclude_harnesses: list[str] | None = None,
) -> list[str]:
    """Resolve ``--harness`` and ``--exclude-harness`` arguments deterministically.

    Supports ``all``, ``compatible``, ``detected``, canonical IDs, aliases, and
    comma-separated lists.
    """
    excluded_set: set[str] = set()
    if exclude_harnesses:
        excluded_set = set(_expand_harness_tokens(exclude_harnesses, root, scope=scope))

    if raw_harnesses:
        base = _expand_harness_tokens(raw_harnesses, root, scope=scope)
    elif default_detected:
        manifest = load_manifest(root) if scope == "project" else None
        if manifest and manifest.harnesses:
            base = [harnesses.get(h).name for h in manifest.harnesses]
        else:
            detected = [
                d.harness.name
                for d in harnesses.detect_harnesses(root)
                if d.project_active
                and (d.harness.project_paths if scope == "project" else d.harness.user_paths)
            ]
            base = detected if detected else ["claude-code", "codex", "cursor"]
    else:
        base = ["claude-code", "codex", "cursor"]

    filtered = [h for h in base if h not in excluded_set]
    if not filtered:
        raise KeyError("no target harnesses remaining after applying --exclude-harness")
    return filtered


def shared_path_exclusion_notes(
    selected_targets: list[str],
    exclude_harnesses: list[str] | None,
    root: Path,
    *,
    scope: str = "project",
    isolated: bool = False,
    custom_paths: dict[str, str] | None = None,
) -> list[str]:
    """Explain honestly when an excluded harness natively reads a shared install path."""
    if not exclude_harnesses:
        return []
    excluded = _expand_harness_tokens(exclude_harnesses, root, scope=scope)
    eff_custom = load_custom_harness_paths(root, scope=scope, explicit=custom_paths)

    written_raw: dict[str, list[str]] = {}
    for t in selected_targets:
        h = harnesses.get(t)
        rp = select_harness_install_raw_path(h, scope, custom_paths=eff_custom, isolated=isolated)
        if rp:
            written_raw.setdefault(rp, []).append(h.name)

    notes: list[str] = []
    for ex_name in excluded:
        eh = harnesses.get(ex_name)
        eh_paths = eh.project_paths if scope == "project" else eh.user_paths
        for sp in eh_paths:
            if sp.path in written_raw:
                owners = ", ".join(written_raw[sp.path])
                notes.append(
                    f"{eh.name} was excluded from managed targets, "
                    f"note that {eh.name} natively scans {sp.path} (used by {owners})"
                )
                break
    return notes


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
