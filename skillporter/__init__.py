"""skillporter — diagnose and fix cross-harness Agent Skill installation.

Every agent harness reads skills from a different directory. Claude Code reads
``.claude/skills``, Codex reads ``.agents/skills``, Cursor reads eight paths,
Hermes reads its own profile tree. Authors therefore hand-roll symlinks and
those links break under git worktrees, Docker builds and fresh clones.

skillporter answers the question those tools do not: *why is my skill not
loading in harness X?* — and then fixes it portably (copy, symlink, or
``.agents/skills`` bridge) instead of guessing.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
