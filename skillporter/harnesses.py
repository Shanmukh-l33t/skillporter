"""Harness registry.

Each entry records the directories a harness actually reads, taken from that
harness's own documentation (not invented). ``scope`` is ``project`` (relative
to the repo root) or ``user`` (relative to ``$HOME``).

Sources verified 2026-11-10:
  * Claude Code  — https://code.claude.com/docs/en/skills
        Skills live in ``.claude/skills/`` (project) and ``~/.claude/skills/``.
  * OpenAI Codex — https://developers.openai.com/codex/skills
        ``.agents/skills/`` (project) and ``~/.agents/skills/``.
  * Cursor       — https://cursor.com/docs/context/skills
        ``.agents/skills/``, ``.cursor/skills/`` (project);
        ``~/.agents/skills/``, ``~/.cursor/skills/`` (user); plus compatibility
        reads of ``.claude/skills/``, ``.codex/skills/``,
        ``~/.claude/skills/``, ``~/.codex/skills/``. Nested subdirectories are
        walked recursively.
  * Hermes Agent — skills live under ``$HERMES_HOME/skills/<category>/<name>``.
  * OpenClaw     — ``~/.openclaw/skills/`` (community convention).

A harness is only marked ``verified`` when the path came from its published
documentation; ``expected`` marks community convention we have not confirmed
against upstream docs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillPath:
    """One filesystem location a harness reads skills from."""

    path: str
    scope: str  # "project" | "user"
    note: str = ""


@dataclass(frozen=True)
class Harness:
    """A supported agent harness and the paths it reads."""

    name: str
    paths: tuple[SkillPath, ...]
    verified: bool = True
    recursive: bool = False
    docs: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def project_paths(self) -> tuple[SkillPath, ...]:
        return tuple(p for p in self.paths if p.scope == "project")

    @property
    def user_paths(self) -> tuple[SkillPath, ...]:
        return tuple(p for p in self.paths if p.scope == "user")


HARNESSES: dict[str, Harness] = {
    "claude-code": Harness(
        name="claude-code",
        paths=(
            SkillPath(".claude/skills", "project"),
            SkillPath(".claude/skills", "user"),
        ),
        docs="https://code.claude.com/docs/en/skills",
        notes=(
            "Reads only .claude/skills. A skill authored in .agents/skills is "
            "invisible here unless bridged -- the most common silent failure.",
        ),
    ),
    "codex": Harness(
        name="codex",
        paths=(
            SkillPath(".agents/skills", "project"),
            SkillPath(".agents/skills", "user"),
        ),
        docs="https://developers.openai.com/codex/skills",
        notes=(
            "Reads .agents/skills only. A skill authored in .claude/skills is "
            "invisible here unless bridged.",
        ),
    ),
    "cursor": Harness(
        name="cursor",
        paths=(
            SkillPath(".agents/skills", "project"),
            SkillPath(".cursor/skills", "project"),
            SkillPath(".agents/skills", "user"),
            SkillPath(".cursor/skills", "user"),
            SkillPath(".claude/skills", "project", "compatibility read"),
            SkillPath(".codex/skills", "project", "compatibility read"),
            SkillPath(".claude/skills", "user", "compatibility read"),
            SkillPath(".codex/skills", "user", "compatibility read"),
        ),
        recursive=True,
        docs="https://cursor.com/docs/context/skills",
        notes=(
            "Walks skill roots recursively, so nested category folders resolve.",
            "Local user skills are not copied to Cloud Agents or remote workers.",
        ),
    ),
    "hermes": Harness(
        name="hermes",
        paths=(
            SkillPath("$HERMES_HOME/skills", "user", "$HERMES_HOME/skills/<category>/<name>"),
        ),
        docs="https://hermes-agent.nousresearch.com/docs",
        notes=("Profile-scoped: resolves against $HERMES_HOME, never a hardcoded path.",),
    ),
    "openclaw": Harness(
        name="openclaw",
        paths=(SkillPath(".openclaw/skills", "user"),),
        verified=False,
        docs="https://github.com/openclaw/openclaw",
        notes=("Community convention; confirm against your installed version.",),
    ),
}


def get(name: str) -> Harness:
    """Return a harness by name, raising a helpful error when unknown."""
    try:
        return HARNESSES[name.lower()]
    except KeyError:
        known = ", ".join(sorted(HARNESSES))
        raise KeyError(f"unknown harness {name!r}; known harnesses: {known}") from None


def names() -> list[str]:
    return sorted(HARNESSES)
