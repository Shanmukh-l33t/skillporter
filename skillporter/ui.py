"""Terminal UI and human-centered CLI formatting helpers for Skillporter.

Provides clean, accessible ANSI styling and structured workflow summaries that
automatically disable color when:
  * ``--no-color`` is passed on the CLI
  * ``NO_COLOR`` is set in the environment
  * ``TERM=dumb``
  * stdout is not a TTY (e.g. CI logs, pipes, pytest capsys)
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"

_FORCE_NO_COLOR = False


def set_no_color(disabled: bool) -> None:
    """Configure process-wide ANSI color suppression (used by ``--no-color``)."""
    global _FORCE_NO_COLOR
    _FORCE_NO_COLOR = bool(disabled)


def use_color(force_no_color: bool = False) -> bool:
    if force_no_color or _FORCE_NO_COLOR:
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return bool(hasattr(sys.stdout, "isatty") and sys.stdout.isatty())


def style(text: str, *codes: str, enabled: bool | None = None) -> str:
    on = use_color() if enabled is None else enabled
    if not on or not codes:
        return text
    return "".join(codes) + text + RESET


def badge(status: str, *, enabled: bool | None = None) -> str:
    on = use_color() if enabled is None else enabled
    up = status.upper()
    if up in (
        "PASSED",
        "SUCCESS",
        "OK",
        "YES",
        "NATIVE",
        "CLEAN",
        "HEALTHY",
        "SYNCED",
        "UP-TO-DATE",
        "CONFIGURED",
    ):
        return style(status, GREEN, BOLD, enabled=on)
    if up in (
        "DRIFT",
        "DRIFTED",
        "DUPLICATE",
        "WARNING",
        "ADAPTED",
        "PARTIAL",
        "COMPATIBLE",
        "UNMANAGED",
        "OUTDATED",
        "OUT_OF_SYNC",
        "SKIPPED",
        "NEEDS ATTENTION",
    ):
        return style(status, YELLOW, BOLD, enabled=on)
    if up in (
        "FAILED",
        "BLOCKED",
        "CRITICAL",
        "HIGH",
        "MISSING",
        "BROKEN",
        "ERROR",
        "UNHEALTHY",
        "ORPHANED",
        "CONFLICT",
        "ACTION REQUIRED",
    ):
        return style(status, RED, BOLD, enabled=on)
    return style(status, CYAN, enabled=on)


def action_symbol(action: str, *, enabled: bool | None = None) -> str:
    """Return a concise, scannable symbol for an operation item."""
    on = use_color() if enabled is None else enabled
    act = action.lower()
    if act in ("created", "installed", "added", "imported", "adopted", "exported"):
        return style("+", GREEN, BOLD, enabled=on)
    if act in ("updated", "moved", "rolled-back", "repaired", "synced"):
        return style("~", CYAN, BOLD, enabled=on)
    if act in ("removed", "deleted", "pruned"):
        return style("-", RED, BOLD, enabled=on)
    if act in ("unchanged", "up-to-date", "preserved-shared"):
        return style("=", DIM, enabled=on)
    if act in ("skipped", "warning", "would-install", "would-update", "would-remove", "would-import"):
        return style("!", YELLOW, BOLD, enabled=on)
    if act in ("failed", "blocked", "conflict"):
        return style("x", RED, BOLD, enabled=on)
    return style("*", CYAN, enabled=on)


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    max_rows: int | None = None,
    indent: str = "",
    more_hint: str = "pass --verbose to view all rows",
) -> str:
    """Render an aligned plain-text table with optional large-result truncation."""
    if not rows:
        return ""
    total = len(rows)
    shown_rows = list(rows[:max_rows]) if (max_rows is not None and max_rows > 0 and total > max_rows) else list(rows)
    widths = [len(h) for h in headers]
    for row in shown_rows:
        for idx, cell in enumerate(row):
            if idx < len(widths):
                widths[idx] = max(widths[idx], len(str(cell)))

    def _fmt_row(cells: Sequence[str]) -> str:
        parts = []
        for idx, cell in enumerate(cells):
            s = str(cell)
            if idx == len(cells) - 1:
                parts.append(s)
            else:
                parts.append(s.ljust(widths[idx]))
        return indent + "  ".join(parts)

    lines = [
        _fmt_row(headers),
        indent + "  ".join("-" * w for w in widths),
    ]
    for row in shown_rows:
        lines.append(_fmt_row(row))
    if len(shown_rows) < total:
        omitted = total - len(shown_rows)
        lines.append(f"{indent}... and {omitted} more ({more_hint})")
    return "\n".join(lines)


def render_next_steps(steps: Sequence[str]) -> str:
    """Render concise, actionable next-step commands."""
    clean = [s for s in steps if s]
    if not clean:
        return ""
    lines = ["Next steps:"]
    for step in clean:
        lines.append(f"  {step}")
    return "\n".join(lines)
