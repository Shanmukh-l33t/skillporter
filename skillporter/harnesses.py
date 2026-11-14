"""Universal Harness Adapter Registry and SDK.

Each adapter records the exact directories a harness reads, its compatibility
classification, verification level, detection rules, capabilities, and official
documentation reference.

Compatibility statuses:
  * NATIVE      — Officially supports the Agent Skills (SKILL.md) format directly.
  * COMPATIBLE  — Supports SKILL.md through a documented compatibility path.
  * ADAPTED     — Requires controlled conversion (e.g. .mdc, .instructions.md, rules).
  * PARTIAL     — Only some skill capabilities or manual invocation flags work.
  * UNSUPPORTED — No reliable file-based skill integration exists.
  * UNVERIFIED  — Implementation exists based on community conventions; upstream unverified.

Verification levels:
  * RUNTIME_VERIFIED       — Discovery verified against a live harness runtime.
  * INTEGRATION_TESTED     — End-to-end filesystem discovery verified in automated tests.
  * DOCUMENTATION_VERIFIED — Paths confirmed directly against official vendor docs.
  * UNIT_TESTED            — Path resolution and adapter rules covered by unit tests.
  * UNVERIFIED             — Not yet verified against official documentation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SUPPORT_STATUSES = (
    "NATIVE",
    "COMPATIBLE",
    "ADAPTED",
    "PARTIAL",
    "UNSUPPORTED",
    "UNVERIFIED",
)

VERIFICATION_LEVELS = (
    "RUNTIME_VERIFIED",
    "INTEGRATION_TESTED",
    "FIXTURE_TESTED",
    "DOCUMENTATION_VERIFIED",
    "UNIT_TESTED",
    "UNVERIFIED",
)


@dataclass(frozen=True)
class SkillPath:
    """One filesystem location a harness reads skills from."""

    path: str
    scope: str  # "project" | "user" | "admin"
    note: str = ""
    is_compatibility: bool = False


@dataclass(frozen=True)
class HarnessCapabilities:
    """Granular feature support for a harness."""

    basic_skills: bool = True
    allowed_tools: bool = True
    context_fork: bool = False
    hooks: bool = False
    recursive_discovery: bool = False
    scripts_dir: bool = True
    references_dir: bool = True
    max_body_tokens: int = 5000
    adapted_format: str | None = None


@dataclass(frozen=True)
class DetectionSpec:
    """Rules for non-destructively detecting whether a harness is present."""

    binaries: tuple[str, ...] = ()
    user_dirs: tuple[str, ...] = ()
    project_markers: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    version_args: tuple[str, ...] = ("--version",)


@dataclass(frozen=True)
class Harness:
    """A supported agent harness adapter and the paths it reads."""

    name: str
    paths: tuple[SkillPath, ...]
    verified: bool = True
    recursive: bool = False
    docs: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    display_name: str = ""
    category: str = "coding"  # "coding" | "autonomous" | "editor"
    support_status: str = "NATIVE"
    verification_level: str = "DOCUMENTATION_VERIFIED"
    verified_date: str = "2026-11-11"
    aliases: tuple[str, ...] = field(default_factory=tuple)
    capabilities: HarnessCapabilities = field(default_factory=HarnessCapabilities)
    detection: DetectionSpec = field(default_factory=DetectionSpec)
    limitations: tuple[str, ...] = field(default_factory=tuple)
    raw_evidence: str = ""

    @property
    def verification_evidence(self) -> str:
        if self.raw_evidence:
            return self.raw_evidence
        if self.verification_level == "RUNTIME_VERIFIED":
            return f"Live runtime discovery verified + conformance fixture ({self.docs})"
        if self.verification_level == "INTEGRATION_TESTED":
            return f"Multi-harness integration & conformance suite ({self.docs})"
        if self.verification_level == "FIXTURE_TESTED":
            return f"19-adapter lifecycle conformance fixture + vendor docs ({self.docs})"
        if self.verification_level == "DOCUMENTATION_VERIFIED" and self.docs:
            return f"Official vendor documentation ({self.docs})"
        return "Declarative adapter specification"

    @property
    def label(self) -> str:
        return self.display_name or self.name

    @property
    def project_paths(self) -> tuple[SkillPath, ...]:
        return tuple(p for p in self.paths if p.scope == "project")

    @property
    def user_paths(self) -> tuple[SkillPath, ...]:
        return tuple(p for p in self.paths if p.scope == "user")

    @property
    def admin_paths(self) -> tuple[SkillPath, ...]:
        return tuple(p for p in self.paths if p.scope == "admin")

    @property
    def primary_project_path(self) -> SkillPath | None:
        pts = self.project_paths
        return pts[0] if pts else None

    @property
    def primary_user_path(self) -> SkillPath | None:
        uts = self.user_paths
        return uts[0] if uts else None


@dataclass
class DetectedHarness:
    """Result of probing a machine and workspace for a harness."""

    harness: Harness
    installed: bool
    project_active: bool
    user_present: bool
    binary_path: str | None = None
    version: str | None = None
    reasons: list[str] = field(default_factory=list)


HARNESSES: dict[str, Harness] = {
    "claude-code": Harness(
        name="claude-code",
        display_name="Claude Code",
        category="coding",
        support_status="NATIVE",
        verification_level="INTEGRATION_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".claude/skills", "project"),
            SkillPath(".claude/skills", "user"),
        ),
        docs="https://code.claude.com/docs/en/skills",
        aliases=("claude",),
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=True,
            hooks=True,
            recursive_discovery=False,
        ),
        detection=DetectionSpec(
            binaries=("claude",),
            user_dirs=(".claude",),
            project_markers=(".claude", "CLAUDE.md", ".claude-plugin"),
            env_vars=("CLAUDE_CONFIG_DIR", "CLAUDECODE"),
        ),
        notes=(
            "Reads only .claude/skills. A skill authored in .agents/skills is "
            "invisible here unless bridged -- the most common silent failure.",
        ),
        limitations=(
            "Does not read .agents/skills natively without a copy or symlink bridge.",
        ),
    ),
    "codex": Harness(
        name="codex",
        display_name="OpenAI Codex",
        category="coding",
        support_status="NATIVE",
        verification_level="INTEGRATION_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".agents/skills", "project"),
            SkillPath(".agents/skills", "user"),
            SkillPath("/etc/codex/skills", "admin", "system-wide admin skills"),
        ),
        docs="https://developers.openai.com/codex/skills",
        aliases=("openai-codex",),
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
        ),
        detection=DetectionSpec(
            binaries=("codex",),
            user_dirs=(".codex", ".agents/skills"),
            project_markers=(".codex", ".agents/skills", "AGENTS.md"),
            env_vars=("CODEX_HOME",),
        ),
        notes=(
            "Reads .agents/skills only. A skill authored in .claude/skills is "
            "invisible here unless bridged.",
        ),
        limitations=(
            "Ignores .claude/skills; expects direct child skill folders under .agents/skills.",
        ),
    ),
    "cursor": Harness(
        name="cursor",
        display_name="Cursor",
        category="coding",
        support_status="NATIVE",
        verification_level="INTEGRATION_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".agents/skills", "project"),
            SkillPath(".cursor/skills", "project"),
            SkillPath(".agents/skills", "user"),
            SkillPath(".cursor/skills", "user"),
            SkillPath(".claude/skills", "project", "compatibility read", is_compatibility=True),
            SkillPath(".codex/skills", "project", "compatibility read", is_compatibility=True),
            SkillPath(".claude/skills", "user", "compatibility read", is_compatibility=True),
            SkillPath(".codex/skills", "user", "compatibility read", is_compatibility=True),
        ),
        recursive=True,
        docs="https://cursor.com/docs/context/skills",
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=True,
            adapted_format="cursor-mdc",
        ),
        detection=DetectionSpec(
            binaries=("cursor",),
            user_dirs=(".cursor",),
            project_markers=(".cursor", ".cursorrules"),
        ),
        notes=(
            "Walks skill roots recursively, so nested category folders resolve.",
            "Local user skills are not copied to Cloud Agents or remote workers.",
        ),
        limitations=(
            "Installing into both .agents/skills and .cursor/skills causes Cursor to list the skill twice.",
        ),
    ),
    "github-copilot": Harness(
        name="github-copilot",
        display_name="GitHub Copilot",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".github/skills", "project"),
            SkillPath(".agents/skills", "project", "compatibility read", is_compatibility=True),
            SkillPath(".claude/skills", "project", "compatibility read", is_compatibility=True),
            SkillPath(".copilot/skills", "user"),
            SkillPath(".agents/skills", "user", "compatibility read", is_compatibility=True),
        ),
        docs="https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills",
        aliases=("copilot",),
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
            adapted_format="copilot-instructions",
        ),
        detection=DetectionSpec(
            binaries=("github-copilot-cli",),
            user_dirs=(".copilot",),
            project_markers=(".github/skills", ".github/copilot-instructions.md", ".github/instructions"),
        ),
        notes=(
            "Reads .github/skills, .agents/skills, and .claude/skills in projects; "
            "~/.copilot/skills and ~/.agents/skills for personal scope.",
        ),
        limitations=(
            "Only immediate subdirectories containing SKILL.md are discovered.",
        ),
    ),
    "gemini-cli": Harness(
        name="gemini-cli",
        display_name="Gemini CLI",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".agents/skills", "project", ".agents/skills takes precedence over .gemini/skills"),
            SkillPath(".gemini/skills", "project"),
            SkillPath(".agents/skills", "user", "~/.agents/skills takes precedence over ~/.gemini/skills"),
            SkillPath(".gemini/skills", "user"),
        ),
        docs="https://geminicli.com/docs/cli/skills/",
        aliases=("gemini",),
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
        ),
        detection=DetectionSpec(
            binaries=("gemini",),
            user_dirs=(".gemini",),
            project_markers=(".gemini", "GEMINI.md"),
            env_vars=("GEMINI_API_KEY",),
        ),
        notes=(
            "Discovers skills in .agents/skills (higher precedence) and .gemini/skills.",
            "Workspace skills require the project folder to be trusted in Gemini CLI.",
        ),
        limitations=(
            "Case-sensitive on Linux: filename must be exact uppercase SKILL.md.",
        ),
    ),
    "antigravity": Harness(
        name="antigravity",
        display_name="Google Antigravity",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".agents/skills", "project"),
            SkillPath(".agent/skills", "project", "legacy compatibility", is_compatibility=True),
            SkillPath(".gemini/config/skills", "user", "shared across Antigravity App and CLI"),
            SkillPath(".gemini/antigravity/skills", "user", "legacy IDE user path", is_compatibility=True),
            SkillPath(".gemini/antigravity-cli/skills", "user", "CLI-only user path", is_compatibility=True),
        ),
        docs="https://antigravity.google/docs/skills",
        aliases=("google-antigravity", "antigravity-cli"),
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
        ),
        detection=DetectionSpec(
            binaries=("antigravity",),
            user_dirs=(".gemini/config", ".gemini/antigravity"),
            project_markers=(".agents/skills.json", ".antigravity-plugin"),
        ),
        notes=(
            "Project scope uses .agents/skills; global scope shared between App and CLI is ~/.gemini/config/skills.",
        ),
    ),
    "windsurf": Harness(
        name="windsurf",
        display_name="Windsurf",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".windsurf/skills", "project"),
            SkillPath(".codeium/windsurf/skills", "user"),
        ),
        docs="https://docs.windsurf.com/windsurf/cascade/skills",
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
            adapted_format="windsurf-rules",
        ),
        detection=DetectionSpec(
            binaries=("windsurf",),
            user_dirs=(".codeium/windsurf",),
            project_markers=(".windsurf", ".windsurfrules"),
        ),
        notes=(
            "Cascade reads project skills from .windsurf/skills and global skills from ~/.codeium/windsurf/skills.",
        ),
        limitations=(
            "Explicit @skill-name mention in Cascade chat is more reliable than automatic invocation.",
        ),
    ),
    "cline": Harness(
        name="cline",
        display_name="Cline",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".cline/skills", "project"),
            SkillPath(".clinerules/skills", "project", "legacy rules-folder skill path", is_compatibility=True),
            SkillPath(".claude/skills", "project", "compatibility read", is_compatibility=True),
            SkillPath(".agents/skills", "project", "compatibility read", is_compatibility=True),
            SkillPath(".cline/skills", "user"),
        ),
        docs="https://docs.cline.bot/customization/skills",
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=True,
            recursive_discovery=False,
            max_body_tokens=5000,
        ),
        detection=DetectionSpec(
            binaries=("cline",),
            user_dirs=(".cline",),
            project_markers=(".cline", ".clinerules"),
        ),
        notes=(
            "Scans .cline/skills (recommended), .clinerules/skills, .claude/skills, and .agents/skills.",
        ),
        limitations=(
            "Mandates SKILL.md body under 5,000 tokens; oversized skills should move detail into references/.",
        ),
    ),
    "roo-code": Harness(
        name="roo-code",
        display_name="Roo Code",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".roo/skills", "project"),
            SkillPath(".agents/skills", "project", "cross-agent compatibility", is_compatibility=True),
            SkillPath(".roo/skills", "user"),
            SkillPath(".agents/skills", "user", "cross-agent compatibility", is_compatibility=True),
        ),
        docs="https://roocodeinc.github.io/Roo-Code/features/skills/",
        aliases=("roo", "roocode"),
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
        ),
        detection=DetectionSpec(
            user_dirs=(".roo",),
            project_markers=(".roo", ".roorules"),
        ),
        notes=(
            "Reads .roo/skills (highest priority) and .agents/skills in project and user scopes.",
            "Also supports mode-specific folders such as .roo/skills-code/ and .roo/skills-architect/.",
        ),
    ),
    "opencode": Harness(
        name="opencode",
        display_name="OpenCode",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".opencode/skills", "project"),
            SkillPath(".agents/skills", "project", "compatibility read", is_compatibility=True),
            SkillPath(".claude/skills", "project", "compatibility read", is_compatibility=True),
            SkillPath(".config/opencode/skills", "user"),
            SkillPath(".agents/skills", "user", "compatibility read", is_compatibility=True),
            SkillPath(".claude/skills", "user", "compatibility read", is_compatibility=True),
        ),
        recursive=True,
        docs="https://opencode.ai/docs/skills",
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=True,
        ),
        detection=DetectionSpec(
            binaries=("opencode",),
            user_dirs=(".config/opencode",),
            project_markers=(".opencode", "opencode.json"),
        ),
        notes=(
            "Searches .opencode/skills, .agents/skills, and .claude/skills across project and global scopes.",
            "Supports nested grouping directories containing SKILL.md.",
        ),
    ),
    "zed": Harness(
        name="zed",
        display_name="Zed",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".agents/skills", "project"),
            SkillPath(".agents/skills", "user"),
        ),
        docs="https://zed.dev/docs/ai/skills",
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
        ),
        detection=DetectionSpec(
            binaries=("zed",),
            user_dirs=(".config/zed",),
            project_markers=(".zed",),
        ),
        notes=(
            "Zed Agent loads skills exclusively from <worktree>/.agents/skills and ~/.agents/skills with live reload.",
        ),
        limitations=(
            "Does not load skills from ~/.config/zed/skills; must use ~/.agents/skills.",
        ),
    ),
    "replit": Harness(
        name="replit",
        display_name="Replit Agent",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".agents/skills", "project"),
            SkillPath(".claude/skills", "project", "compatibility read", is_compatibility=True),
            SkillPath(".config/agents/skills", "user"),
        ),
        recursive=True,
        docs="https://docs.replit.com/features/agent/skills",
        aliases=("replit-agent",),
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=True,
        ),
        detection=DetectionSpec(
            project_markers=(".replit", "replit.nix"),
            env_vars=("REPL_ID", "REPL_SLUG"),
        ),
        notes=(
            "Discovers enabled skills under .agents/skills and .claude/skills, including nested directories.",
        ),
    ),
    "junie": Harness(
        name="junie",
        display_name="JetBrains Junie / AI Assistant",
        category="coding",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".junie/skills", "project"),
            SkillPath(".agents/skills", "project", "shared skills compatibility", is_compatibility=True),
            SkillPath(".junie/skills", "user"),
            SkillPath(".agents/skills", "user", "shared skills compatibility", is_compatibility=True),
        ),
        docs="https://junie.jetbrains.com/docs/agent-skills.html",
        aliases=("jetbrains", "jetbrains-ai"),
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
        ),
        detection=DetectionSpec(
            binaries=("junie",),
            user_dirs=(".junie",),
            project_markers=(".junie",),
        ),
        notes=(
            "Works across Junie CLI and JetBrains IDEs (IntelliJ IDEA, PyCharm, WebStorm, GoLand, etc.).",
        ),
    ),
    "hermes": Harness(
        name="hermes",
        display_name="Hermes Agent",
        category="autonomous",
        support_status="NATIVE",
        verification_level="RUNTIME_VERIFIED",
        verified_date="2026-11-11",
        paths=(
            SkillPath("$HERMES_HOME/skills", "user", "$HERMES_HOME/skills/<category>/<name>"),
            SkillPath(".hermes/skills", "project", "workspace-scoped Hermes skills"),
        ),
        recursive=True,
        docs="https://hermes-agent.nousresearch.com/docs",
        aliases=("hermes-agent",),
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=True,
            hooks=True,
            recursive_discovery=True,
        ),
        detection=DetectionSpec(
            binaries=("hermes",),
            user_dirs=(".hermes",),
            project_markers=(".hermes",),
            env_vars=("HERMES_HOME",),
        ),
        notes=(
            "Profile-scoped: resolves against $HERMES_HOME, never a hardcoded path.",
            "Walks nested category directories ($HERMES_HOME/skills/<category>/<name>/SKILL.md).",
        ),
    ),
    "openclaw": Harness(
        name="openclaw",
        display_name="OpenClaw",
        category="autonomous",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        verified=True,
        paths=(
            SkillPath(".openclaw/skills", "user"),
            SkillPath(".agents/skills", "user", "personal agent skills", is_compatibility=True),
            SkillPath(".openclaw/skills", "project"),
            SkillPath("skills", "project", "workspace skills directory", is_compatibility=True),
            SkillPath(".agents/skills", "project", "project agent skills", is_compatibility=True),
        ),
        recursive=True,
        docs="https://docs.openclaw.ai/tools/skills",
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=True,
        ),
        detection=DetectionSpec(
            binaries=("openclaw",),
            user_dirs=(".openclaw",),
            project_markers=(".openclaw",),
        ),
        notes=(
            "Loads <workspace>/skills, <workspace>/.agents/skills, "
            "~/.agents/skills, and ~/.openclaw/skills up to 6 levels deep.",
        ),
    ),
    "openhands": Harness(
        name="openhands",
        display_name="OpenHands",
        category="autonomous",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".agents/skills", "project"),
            SkillPath(".openhands/skills", "project", "legacy OpenHands path", is_compatibility=True),
            SkillPath(".openhands/microagents", "project", "legacy microagents path", is_compatibility=True),
            SkillPath(".agents/skills", "user"),
            SkillPath(".openhands/skills", "user", "legacy OpenHands path", is_compatibility=True),
        ),
        docs="https://docs.openhands.dev/overview/skills",
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
        ),
        detection=DetectionSpec(
            binaries=("openhands",),
            user_dirs=(".openhands",),
            project_markers=(".openhands",),
        ),
        notes=(
            ".agents/skills takes precedence over legacy .openhands/skills and .openhands/microagents.",
        ),
    ),
    "goose": Harness(
        name="goose",
        display_name="Goose",
        category="autonomous",
        support_status="NATIVE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".agents/skills", "project"),
            SkillPath(".goose/skills", "project", "backward compatibility", is_compatibility=True),
            SkillPath(".agents/skills", "user"),
            SkillPath(".config/goose/skills", "user", "backward compatibility", is_compatibility=True),
        ),
        docs="https://block.github.io/goose/docs/guides/context-engineering/using-skills/",
        capabilities=HarnessCapabilities(
            allowed_tools=True,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
        ),
        detection=DetectionSpec(
            binaries=("goose",),
            user_dirs=(".config/goose", ".goose"),
            project_markers=(".goose", ".goosehints"),
        ),
        notes=(
            "Reads ~/.agents/skills and .agents/skills, plus legacy .goose/skills and ~/.config/goose/skills.",
        ),
    ),
    "continue": Harness(
        name="continue",
        display_name="Continue",
        category="coding",
        support_status="COMPATIBLE",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".continue/skills", "project"),
            SkillPath(".continue/skills", "user"),
        ),
        docs="https://docs.continue.dev/customize/deep-dives/rules",
        aliases=("continue-dev",),
        capabilities=HarnessCapabilities(
            allowed_tools=False,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
            adapted_format="continue-rules",
        ),
        detection=DetectionSpec(
            binaries=("cn",),
            user_dirs=(".continue",),
            project_markers=(".continue", ".continuerules"),
        ),
        notes=(
            "Continue loadMarkdownSkills loader reads .continue/skills/<name>/SKILL.md; "
            "older versions require adapted rules in .continue/rules/<name>.md.",
        ),
        limitations=(
            "Upstream Continue repository entered maintenance-only mode in June 2026.",
        ),
    ),
    "aider": Harness(
        name="aider",
        display_name="Aider / AiderDesk",
        category="coding",
        support_status="ADAPTED",
        verification_level="FIXTURE_TESTED",
        verified_date="2026-11-11",
        paths=(
            SkillPath(".aider-desk/skills", "project", "AiderDesk native skill folder"),
            SkillPath(".aider-desk/skills", "user", "AiderDesk global skill folder"),
        ),
        docs="https://aider.chat/docs/usage/conventions.html",
        aliases=("aider-desk",),
        capabilities=HarnessCapabilities(
            allowed_tools=False,
            context_fork=False,
            hooks=False,
            recursive_discovery=False,
            adapted_format="aider-conventions",
        ),
        detection=DetectionSpec(
            binaries=("aider",),
            user_dirs=(".aider-desk",),
            project_markers=(".aider.conf.yml", ".aider-desk", "CONVENTIONS.md"),
        ),
        notes=(
            "AiderDesk reads .aider-desk/skills/<name>/SKILL.md. Core Aider CLI requires "
            "`aider --read <skill>/SKILL.md` or adapted export to CONVENTIONS.md.",
        ),
        limitations=(
            "Core Aider CLI does not auto-discover SKILL.md folders without --read or CONVENTIONS.md adaptation.",
        ),
    ),
}

CORE_HARNESS_NAMES: tuple[str, ...] = (
    "claude-code",
    "codex",
    "cursor",
    "hermes",
    "openclaw",
)

_ALIAS_MAP: dict[str, str] = {}


def _rebuild_aliases() -> None:
    _ALIAS_MAP.clear()
    for key, h in HARNESSES.items():
        _ALIAS_MAP[key.lower()] = key
        for alias in h.aliases:
            _ALIAS_MAP[alias.lower()] = key


_rebuild_aliases()


def get(name: str) -> Harness:
    """Return a harness by canonical name or alias, raising a helpful KeyError when unknown."""
    key = _ALIAS_MAP.get(name.strip().lower())
    if key and key in HARNESSES:
        return HARNESSES[key]
    known = ", ".join(sorted(HARNESSES))
    raise KeyError(f"unknown harness {name!r}; known harnesses: {known}")


def names(*, core_only: bool = False) -> list[str]:
    """Return sorted harness IDs."""
    if core_only:
        return sorted(k for k in CORE_HARNESS_NAMES if k in HARNESSES)
    return sorted(HARNESSES)


def register_adapter(harness: Harness) -> None:
    """Register or replace a harness adapter dynamically (Adapter SDK)."""
    if harness.support_status not in SUPPORT_STATUSES:
        raise ValueError(f"invalid support_status {harness.support_status!r}; expected one of {SUPPORT_STATUSES}")
    if harness.verification_level not in VERIFICATION_LEVELS:
        raise ValueError(
            f"invalid verification_level {harness.verification_level!r}; expected one of {VERIFICATION_LEVELS}"
        )
    HARNESSES[harness.name.lower()] = harness
    _rebuild_aliases()


def unregister_adapter(name: str) -> None:
    """Remove a dynamically registered adapter."""
    key = _ALIAS_MAP.get(name.lower(), name.lower())
    HARNESSES.pop(key, None)
    _rebuild_aliases()


def load_adapter_file(path: Path) -> list[Harness]:
    """Load declarative third-party adapter definitions from a JSON file.

    Trust boundary: only declarative JSON data is parsed. No arbitrary Python
    code or shell commands are ever executed when loading third-party adapters.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("adapters", [raw])
    loaded: list[Harness] = []
    for item in items:
        if not isinstance(item, dict) or "name" not in item or "paths" not in item:
            raise ValueError(f"invalid adapter definition in {path}: missing 'name' or 'paths'")
        skill_paths: list[SkillPath] = []
        for p in item["paths"]:
            raw_p = str(p["path"]).strip()
            sc = str(p.get("scope", "project"))
            norm_p = raw_p.replace("\\", "/")
            if sc in ("project", "user") and (
                norm_p.startswith("/") or ".." in [seg for seg in norm_p.split("/") if seg]
            ):
                raise ValueError(
                    f"unsafe adapter path {raw_p!r} for scope {sc!r}: "
                    "relative paths without '..' required"
                )
            skill_paths.append(
                SkillPath(
                    path=raw_p,
                    scope=sc,
                    note=str(p.get("note", "")),
                    is_compatibility=bool(p.get("is_compatibility", False)),
                )
            )
        h = Harness(
            name=str(item["name"]).lower(),
            display_name=str(item.get("display_name", item["name"])),
            category=str(item.get("category", "coding")),
            support_status=str(item.get("support_status", "UNVERIFIED")),
            verification_level=str(item.get("verification_level", "UNVERIFIED")),
            verified=bool(item.get("verified", False)),
            verified_date=str(item.get("verified_date", "")),
            recursive=bool(item.get("recursive", False)),
            docs=str(item.get("docs", "")),
            notes=tuple(str(n) for n in item.get("notes", ())),
            limitations=tuple(str(x) for x in item.get("limitations", ())),
            aliases=tuple(str(a) for a in item.get("aliases", ())),
            paths=tuple(skill_paths),
        )
        register_adapter(h)
        loaded.append(h)
    return loaded


def detect_harnesses(
    root: Path | None = None,
    home: Path | None = None,
    *,
    probe_versions: bool = False,
) -> list[DetectedHarness]:
    """Detect which AI agent harnesses are installed or active in the project."""
    root = (root or Path.cwd()).resolve()
    home = (home or Path(os.path.expanduser("~"))).resolve()
    results: list[DetectedHarness] = []

    for name in names():
        h = HARNESSES[name]
        det = h.detection
        reasons: list[str] = []
        binary_path: str | None = None
        version: str | None = None
        project_active = False
        user_present = False

        for bin_name in det.binaries:
            found_bin = shutil.which(bin_name)
            if found_bin:
                binary_path = found_bin
                reasons.append(f"binary:{bin_name}")
                if probe_versions and not version:
                    try:
                        proc = subprocess.run(
                            [found_bin, *det.version_args],
                            stdin=subprocess.DEVNULL,
                            capture_output=True,
                            text=True,
                            timeout=2,
                            check=False,
                        )
                        out = (proc.stdout or proc.stderr or "").strip().splitlines()
                        if out:
                            version = out[0][:80]
                    except (OSError, subprocess.SubprocessError):
                        pass
                break

        for env_key in det.env_vars:
            if os.environ.get(env_key):
                user_present = True
                reasons.append(f"env:{env_key}")

        for udir in det.user_dirs:
            if (home / udir).exists():
                user_present = True
                reasons.append(f"user:~/{udir}")

        for marker in det.project_markers:
            if (root / marker).exists():
                project_active = True
                reasons.append(f"project:{marker}")

        if h.primary_project_path and (root / h.primary_project_path.path).exists():
            project_active = True
            if f"project:{h.primary_project_path.path}" not in reasons:
                reasons.append(f"project:{h.primary_project_path.path}")

        installed = bool(binary_path or user_present or project_active)
        results.append(
            DetectedHarness(
                harness=h,
                installed=installed,
                project_active=project_active,
                user_present=user_present,
                binary_path=binary_path,
                version=version,
                reasons=reasons,
            )
        )
    return results
