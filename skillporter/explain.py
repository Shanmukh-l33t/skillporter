"""Plain-English Diagnostic & Security Finding Explainer (`skillporter explain`).

Translates any diagnostic state (`DRIFT`, `DUPLICATE`, `BROKEN`, `MISSING`),
lockfile or dependency error (`LOCK_DRIFT`, `CYCLE`, `CONFLICT`, `RISK_THRESHOLD`),
`SKILL.md` frontmatter validation code, or security finding code (`sec-*`) into:
  1. Plain-English root cause
  2. Why it matters for multi-agent teams
  3. Exact copy-pasteable remediation command(s).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Explanation:
    """Structured explanation for a diagnostic, validation, or security finding."""

    code: str
    category: str
    title: str
    cause: str
    impact: str
    suggested_fix: str
    commands: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "category": self.category,
            "title": self.title,
            "cause": self.cause,
            "impact": self.impact,
            "suggested_fix": self.suggested_fix,
            "commands": list(self.commands),
        }


EXPLANATIONS: dict[str, Explanation] = {
    "DRIFT": Explanation(
        code="DRIFT",
        category="diagnostics",
        title="SHA-256 Content Drift Across Installed Skill Copies",
        cause=(
            "Two or more harness directories (for example `.claude/skills/<skill>` and "
            "`.agents/skills/<skill>`) contain different file contents for the same skill."
        ),
        impact=(
            "Claude Code and Codex/Cursor will execute different versions of the same skill, "
            "causing inconsistent agent behavior across teammates."
        ),
        suggested_fix=(
            "Synchronize all harness copies from your preferred authoritative copy (existing "
            "copies are backed up to `.skillporter/backups/` automatically)."
        ),
        commands=(
            "skillporter sync --force",
            "skillporter sync --prefer .claude/skills/<skill>",
        ),
    ),
    "DUPLICATE": Explanation(
        code="DUPLICATE",
        category="diagnostics",
        title="Duplicate Skill Loading Inside the Same Harness",
        cause=(
            "A skill is installed in two primary directories scanned by the same harness "
            "(for example both `.agents/skills/<skill>` and `.cursor/skills/<skill>`)."
        ),
        impact=(
            "The agent harness loads two copies of the same skill into the prompt context, "
            "wasting tokens and causing ambiguous routing."
        ),
        suggested_fix=(
            "Keep the skill in the shared `.agents/skills/` path and remove the redundant "
            "harness-specific directory copy."
        ),
        commands=(
            "skillporter doctor --fix",
            "skillporter remove <skill> --harness cursor",
        ),
    ),
    "BROKEN": Explanation(
        code="BROKEN",
        category="diagnostics",
        title="Broken / Dangling Symlink in Harness Skill Directory",
        cause=(
            "A symlink inside a harness skill directory points to a file or directory that "
            "no longer exists (common inside Docker builds, CI checkouts, or `git worktree`)."
        ),
        impact=(
            "The skill silently fails to load in the affected agent harness."
        ),
        suggested_fix=(
            "Remove the dangling symlink and re-install the skill using portable `--strategy copy`."
        ),
        commands=(
            "skillporter doctor --fix",
            "skillporter sync --strategy copy --force",
        ),
    ),
    "MISSING": Explanation(
        code="MISSING",
        category="diagnostics",
        title="Skill Invisible / Missing in Active Harness",
        cause=(
            "The skill exists in one harness directory (e.g. `.claude/skills/`) but has not "
            "been installed into the directory scanned by another active harness (e.g. `.agents/skills/`)."
        ),
        impact=(
            "Developers using the second harness cannot see or invoke the skill."
        ),
        suggested_fix=(
            "Synchronize the workspace skills across all detected or configured harnesses."
        ),
        commands=(
            "skillporter sync",
            "skillporter doctor --fix",
        ),
    ),
    "LOCK_DRIFT": Explanation(
        code="LOCK_DRIFT",
        category="lockfile",
        title="On-Disk Skill Differs from Pinned skillporter.lock",
        cause=(
            "An installed skill directory was modified locally or is missing, so its SHA-256 "
            "tree hash no longer matches the digest pinned in `skillporter.lock`."
        ),
        impact=(
            "CI reproducibility is broken (`skillporter lock --check` exits 1)."
        ),
        suggested_fix=(
            "If the change was unintentional, roll back or sync from the manifest; if intentional, "
            "update the lockfile."
        ),
        commands=(
            "skillporter lock --check",
            "skillporter rollback <skill>",
            "skillporter lock",
        ),
    ),
    "CYCLE": Explanation(
        code="CYCLE",
        category="dependencies",
        title="Cyclic Skill Dependency Detected",
        cause=(
            "Two or more skills declare dependencies on each other in a loop (e.g. `skill-a -> skill-b -> skill-a`)."
        ),
        impact=(
            "Skillporter refuses to install or lock cyclic dependency graphs."
        ),
        suggested_fix=(
            "Break the cycle in `skillporter.yaml` or `SKILL.md` frontmatter `dependencies`."
        ),
        commands=(
            "skillporter graph",
            "skillporter validate .",
        ),
    ),
    "CONFLICT": Explanation(
        code="CONFLICT",
        category="dependencies",
        title="Incompatible Semver Dependency Version Constraints",
        cause=(
            "Two skills require incompatible semver ranges for the same dependency, or the "
            "available skill version does not satisfy the declared semver range."
        ),
        impact=(
            "Dependency resolution fails closed with exit code 1 to prevent installing an incompatible version."
        ),
        suggested_fix=(
            "Align the `version:` constraint in `skillporter.yaml` or update the dependency to a matching release."
        ),
        commands=(
            "skillporter graph",
            "skillporter update",
        ),
    ),
    "RISK_THRESHOLD": Explanation(
        code="RISK_THRESHOLD",
        category="security",
        title="Skill Risk Score Exceeds Configured security.max_risk_score",
        cause=(
            "The skill's 0-100 security risk score is higher than `security.max_risk_score` "
            "configured in `skillporter.yaml` (or `--max-risk-score`)."
        ),
        impact=(
            "`skillporter add` and `skillporter sync` fail closed with exit code 1."
        ),
        suggested_fix=(
            "Inspect the security findings and dry-run sandbox trace before deciding whether "
            "to remediate the skill or adjust the threshold."
        ),
        commands=(
            "skillporter scan <skill> --format json",
            "skillporter sandbox run <skill>",
        ),
    ),
    "sec-prompt-override": Explanation(
        code="sec-prompt-override",
        category="security",
        title="Prompt-Injection Instruction Override Detected",
        cause=(
            "Markdown content contains phrases like 'ignore all previous instructions' or "
            "'do not tell the user' designed to hijack agent behavior."
        ),
        impact=(
            "An agent loading this skill may disregard system safety boundaries or user instructions."
        ),
        suggested_fix=(
            "Remove imperative instruction-override directives from `SKILL.md` and reference files."
        ),
        commands=("skillporter scan <skill>",),
    ),
    "sec-symlink-escape": Explanation(
        code="sec-symlink-escape",
        category="security",
        title="Symlink Escapes Skill Root Directory",
        cause=(
            "A symlink inside the skill package resolves outside the skill directory (for example "
            "`-> /etc/shadow` or `-> ../../secret`)."
        ),
        impact=(
            "Copying or reading the skill could expose host files outside the repository. "
            "This is a structural escape and cannot be bypassed with `--allow-risky`."
        ),
        suggested_fix=(
            "Delete the escaping symlink and keep all referenced files inside the skill root."
        ),
        commands=("skillporter scan <skill>",),
    ),
    "sec-curl-pipe-sh": Explanation(
        code="sec-curl-pipe-sh",
        category="security",
        title="Unverified Remote Script Execution (curl | sh)",
        cause=(
            "A script or Markdown instruction pipes `curl` or `wget` output directly into `sh` or `bash`."
        ),
        impact=(
            "Executes arbitrary unpinned remote code on the developer machine or CI runner."
        ),
        suggested_fix=(
            "Download artifacts to a file, verify a pinned SHA-256 checksum, or vendor the script in `scripts/`."
        ),
        commands=("skillporter scan <skill>", "skillporter sandbox run <skill>"),
    ),
    "sec-private-key": Explanation(
        code="sec-private-key",
        category="security",
        title="Embedded Private Key Detected",
        cause="A PEM private key block (`-----BEGIN ... PRIVATE KEY-----`) is bundled in the skill.",
        impact="Distributes secret cryptographic keys to every developer and agent context.",
        suggested_fix=(
            "Remove the key file immediately, rotate the key, and read credentials from environment variables."
        ),
        commands=("skillporter scan <skill>",),
    ),
    "name-directory-mismatch": Explanation(
        code="name-directory-mismatch",
        category="validation",
        title="SKILL.md Frontmatter Name Does Not Match Directory Name",
        cause="The `name:` field in `SKILL.md` YAML frontmatter differs from the parent directory name.",
        impact="Strict harnesses reject or fail to index skills whose directory name mismatches `name:`.",
        suggested_fix="Rename the skill directory or update `name:` in `SKILL.md` so both match exactly.",
        commands=("skillporter validate .",),
    ),
    "no-frontmatter": Explanation(
        code="no-frontmatter",
        category="validation",
        title="Missing YAML Frontmatter in SKILL.md",
        cause=(
            "`SKILL.md` does not start with a `---` delimited YAML frontmatter block "
            "containing `name` and `description`."
        ),
        impact="Agent harnesses cannot discover when to trigger the skill.",
        suggested_fix=(
            "Add `---\\nname: <skill-name>\\ndescription: <what it does and when to use it>\\n---` at line 1."
        ),
        commands=("skillporter validate .",),
    ),
}


def explain_finding(query: str) -> Explanation:
    """Translate a code, keyword, or full finding message into an Explanation."""
    raw = query.strip()
    upper = raw.upper()
    lower = raw.lower()

    # 1. Exact key match
    if raw in EXPLANATIONS:
        return EXPLANATIONS[raw]
    if upper in EXPLANATIONS:
        return EXPLANATIONS[upper]
    if lower in EXPLANATIONS:
        return EXPLANATIONS[lower]

    # 2. Match known security codes or validation codes mentioned inside a pasted finding line
    for key, exp in EXPLANATIONS.items():
        if key.lower() in lower:
            return exp

    # 3. Heuristic matching on natural-language finding strings from `diagnose` / `doctor` / `lock`
    if "content drift" in lower or "drifted" in lower:
        return EXPLANATIONS["DRIFT"]
    if "broken symlink" in lower or "dangling" in lower:
        return EXPLANATIONS["BROKEN"]
    if "not visible to" in lower or "missing" in lower:
        return EXPLANATIONS["MISSING"]
    if "duplicate" in lower:
        return EXPLANATIONS["DUPLICATE"]
    if "lockfile" in lower or "skillporter.lock" in lower:
        return EXPLANATIONS["LOCK_DRIFT"]
    if "cyclic" in lower or "cycle" in lower:
        return EXPLANATIONS["CYCLE"]
    if "conflict" in lower or "semver" in lower:
        return EXPLANATIONS["CONFLICT"]
    if "risk_score" in lower or "max_risk_score" in lower or "threshold" in lower:
        return EXPLANATIONS["RISK_THRESHOLD"]

    # 4. Generic sec-* or frontmatter fallback from security._REMEDIATIONS
    from .security import _FINDING_CATEGORIES, _REMEDIATIONS

    if lower in _REMEDIATIONS:
        cat = _FINDING_CATEGORIES.get(lower, "security")
        return Explanation(
            code=lower,
            category=cat,
            title=f"Security Rule `{lower}`",
            cause=f"Static security scanner matched rule `{lower}` ({cat} category).",
            impact="Blocks installation under default security policy until remediated or reviewed.",
            suggested_fix=_REMEDIATIONS[lower],
            commands=("skillporter scan .", "skillporter sandbox run <skill>"),
        )

    return Explanation(
        code=raw or "UNKNOWN",
        category="general",
        title=f"Finding Explanation: {raw}",
        cause=(
            "Skillporter detected a workspace reachability, specification, lockfile, or security "
            f"anomaly matching `{raw}`."
        ),
        impact="May prevent skills from loading consistently or passing CI gates.",
        suggested_fix="Run `skillporter doctor` to inspect full workspace state and recommended repairs.",
        commands=(
            "skillporter doctor .",
            "skillporter diagnose .",
            "skillporter scan .",
        ),
    )
