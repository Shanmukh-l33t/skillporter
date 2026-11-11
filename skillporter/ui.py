"""Terminal UI helpers for Skillporter.

Provides clean, accessible ANSI styling that automatically disables color when:
  * ``NO_COLOR`` is set in the environment
  * ``TERM=dumb``
  * stdout is not a TTY (e.g. CI logs, pipes, pytest capsys)
"""

from __future__ import annotations

import os
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"


def use_color(force_no_color: bool = False) -> bool:
    if force_no_color:
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
    if up in ("PASSED", "SUCCESS", "OK", "YES", "NATIVE", "CLEAN"):
        return style(status, GREEN, BOLD, enabled=on)
    if up in ("DRIFT", "DUPLICATE", "WARNING", "ADAPTED", "PARTIAL", "COMPATIBLE"):
        return style(status, YELLOW, BOLD, enabled=on)
    if up in ("FAILED", "BLOCKED", "CRITICAL", "HIGH", "MISSING", "BROKEN", "ERROR"):
        return style(status, RED, BOLD, enabled=on)
    return style(status, CYAN, enabled=on)
