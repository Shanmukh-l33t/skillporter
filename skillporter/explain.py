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
    "frontmatter-tab-indentation": Explanation(
        code="frontmatter-tab-indentation",
        category="validation",
        title="Tab Indentation in SKILL.md YAML Frontmatter",
        cause="YAML frontmatter contains literal tab characters (`\\t`), which strict YAML parsers reject.",
        impact="Harnesses fail to parse skill metadata and silently skip loading the skill.",
        suggested_fix="Replace tab indentation in `SKILL.md` frontmatter with spaces.",
        commands=("skillporter validate .",),
    ),
    "missing-name": Explanation(
        code="missing-name",
        category="validation",
        title="Missing Required 'name' Field in SKILL.md Frontmatter",
        cause="The `SKILL.md` frontmatter does not declare a `name:` field.",
        impact="Harnesses cannot address or register the skill.",
        suggested_fix=(
            "Set `name: <directory-name>` in `SKILL.md` frontmatter "
            "using lowercase letters, digits, and single hyphens."
        ),
        commands=("skillporter validate .",),
    ),
    "name-too-long": Explanation(
        code="name-too-long",
        category="validation",
        title="Skill Name Exceeds 64 Characters",
        cause="The `name:` value in `SKILL.md` exceeds the 64-character Agent Skills specification limit.",
        impact="Harnesses and registries reject oversized skill identifiers.",
        suggested_fix="Shorten both the directory name and `name:` frontmatter value to 64 characters or fewer.",
        commands=("skillporter validate .",),
    ),
    "name-invalid-chars": Explanation(
        code="name-invalid-chars",
        category="validation",
        title="Invalid Characters in Skill Name",
        cause=(
            "`name:` contains uppercase letters, underscores, spaces, "
            "leading/trailing hyphens, or consecutive hyphens."
        ),
        impact="Fails Agent Skills specification validation across strict harnesses.",
        suggested_fix="Use lowercase alphanumeric characters separated by single hyphens (e.g. `pdf-table-extractor`).",
        commands=("skillporter validate .",),
    ),
    "missing-description": Explanation(
        code="missing-description",
        category="validation",
        title="Missing Required 'description' Field in SKILL.md Frontmatter",
        cause="The `SKILL.md` frontmatter does not include a `description:` field.",
        impact=(
            "Agents rely on `description:` to decide when to activate a skill; "
            "without it, the skill never triggers."
        ),
        suggested_fix=(
            "Add a concise `description:` explaining what the skill does "
            "and when to activate (`Use when ...`)."
        ),
        commands=("skillporter validate .",),
    ),
    "description-too-long": Explanation(
        code="description-too-long",
        category="validation",
        title="Skill Description Exceeds 1,024 Characters",
        cause="The `description:` field exceeds the 1,024-character specification cap.",
        impact="Bloats always-loaded index context or gets truncated/rejected by harnesses.",
        suggested_fix="Keep `description:` under 1,024 characters and move detailed guidance into the `SKILL.md` body.",
        commands=("skillporter validate .",),
    ),
    "description-vague": Explanation(
        code="description-vague",
        category="validation",
        title="Skill Description Is Too Short for Reliable Routing",
        cause="`description:` is fewer than 20 characters and lacks concrete capability or trigger context.",
        impact="Causes missed activations or false-positive routing across agents.",
        suggested_fix="Expand `description:` to state both what the skill does and when to use it.",
        commands=("skillporter validate .",),
    ),
    "description-no-trigger": Explanation(
        code="description-no-trigger",
        category="validation",
        title="Skill Description Lacks Activation Trigger Clause",
        cause="`description:` describes the topic without stating when the agent should load it (e.g. `Use when ...`).",
        impact="Reduces activation precision across multi-skill environments.",
        suggested_fix="Include a clear `Use when <scenario>.` clause in `description:`.",
        commands=("skillporter validate .",),
    ),
    "compatibility-too-long": Explanation(
        code="compatibility-too-long",
        category="validation",
        title="Compatibility Field Exceeds 500 Characters",
        cause="The `compatibility:` frontmatter field is longer than 500 characters.",
        impact="Violates the Agent Skills frontmatter size constraints.",
        suggested_fix="Summarize runtime prerequisites in under 500 characters.",
        commands=("skillporter validate .",),
    ),
    "metadata-not-map": Explanation(
        code="metadata-not-map",
        category="validation",
        title="Frontmatter 'metadata' Is Not a Key-Value Map",
        cause="`metadata:` in `SKILL.md` is a scalar or list instead of a YAML mapping.",
        impact="Clients expecting `metadata.version` or `metadata.author` fail to parse metadata.",
        suggested_fix="Format `metadata:` as indented `key: \"value\"` pairs.",
        commands=("skillporter validate .",),
    ),
    "metadata-non-string": Explanation(
        code="metadata-non-string",
        category="validation",
        title="Non-String Value Inside Frontmatter 'metadata'",
        cause="A nested value inside `metadata:` is not a string.",
        impact="Strict Agent Skills clients require string-to-string metadata maps.",
        suggested_fix="Quote metadata values as strings (e.g. `version: \"1.0.0\"`).",
        commands=("skillporter validate .",),
    ),
    "allowed-tools-not-string": Explanation(
        code="allowed-tools-not-string",
        category="validation",
        title="Frontmatter 'allowed-tools' Must Be a Space-Separated String",
        cause="`allowed-tools:` was written as a YAML array instead of a space-delimited string.",
        impact="Claude Code and Agent Skills parsers reject or ignore malformed `allowed-tools`.",
        suggested_fix="Write `allowed-tools: Bash Read Edit` as a single space-separated string.",
        commands=("skillporter validate .",),
    ),
    "harness-specific-context-fork": Explanation(
        code="harness-specific-context-fork",
        category="compatibility",
        title="Harness-Specific 'context: fork' Directive",
        cause="`SKILL.md` uses `context: fork`, which runs the skill in an isolated subagent context.",
        impact="Supported by Claude Code and Hermes Agent; other harnesses ignore `context: fork` and load inline.",
        suggested_fix="Keep instructions safe to run inline when targeting harnesses without subagent forking.",
        commands=("skillporter harness inspect claude-code",),
    ),
    "unknown-frontmatter-field": Explanation(
        code="unknown-frontmatter-field",
        category="validation",
        title="Unrecognized Frontmatter Field in SKILL.md",
        cause="`SKILL.md` contains a frontmatter key outside standard Agent Skills fields.",
        impact="May indicate a typo (such as `desc:` instead of `description:`) or ignored vendor metadata.",
        suggested_fix="Verify field spelling or move custom attributes under `metadata:`.",
        commands=("skillporter validate .",),
    ),
    "empty-body": Explanation(
        code="empty-body",
        category="validation",
        title="Empty SKILL.md Markdown Body",
        cause="`SKILL.md` has frontmatter but no instructional body text.",
        impact="Activating the skill provides zero instructions to the agent.",
        suggested_fix="Add clear step-by-step instructions, constraints, and examples below the closing `---`.",
        commands=("skillporter validate .",),
    ),
    "body-too-large": Explanation(
        code="body-too-large",
        category="compatibility",
        title="SKILL.md Body Exceeds Recommended 5,000-Token Budget",
        cause="The `SKILL.md` body is larger than ~5,000 estimated tokens.",
        impact="Consumes excessive context window on activation and fails Cline's 5,000-token hard limit.",
        suggested_fix="Keep core workflow steps in `SKILL.md` and move detailed reference material into `references/`.",
        commands=("skillporter insights .", "skillporter validate ."),
    ),
    "deep-reference-path": Explanation(
        code="deep-reference-path",
        category="validation",
        title="Deeply Nested File Reference in SKILL.md",
        cause=(
            "A link in `SKILL.md` points more than one directory level deep "
            "inside `references/`, `scripts/`, or `assets/`."
        ),
        impact="Some harnesses only index or bundle shallow supporting directories.",
        suggested_fix="Keep supporting files one level deep (e.g. `references/api.md`).",
        commands=("skillporter validate .",),
    ),
    "ORPHANED": Explanation(
        code="ORPHANED",
        category="environment",
        title="Tracked Skill Missing on Disk",
        cause="A skill is recorded in `.skillporter/state.json` or `skillporter.lock` but its directory was deleted.",
        impact="Agents no longer receive the skill and CI lockfile checks fail.",
        suggested_fix="Re-synchronize from the manifest/backup or remove the stale record.",
        commands=("skillporter doctor --fix", "skillporter sync", "skillporter remove <skill>"),
    ),
    "OUT_OF_SYNC": Explanation(
        code="OUT_OF_SYNC",
        category="environment",
        title="Declared Skill Missing from One or More Configured Harnesses",
        cause="`skillporter.yaml` or state declares target harnesses where the skill is not yet installed.",
        impact="Selected agents cannot discover or load the skill.",
        suggested_fix="Run `skillporter sync` or `skillporter doctor --fix` to populate missing harness targets.",
        commands=("skillporter sync", "skillporter doctor --fix"),
    ),
    "UNMANAGED": Explanation(
        code="UNMANAGED",
        category="environment",
        title="On-Disk Skill Not Tracked by Skillporter",
        cause="A `SKILL.md` directory exists in a harness folder without an entry in `.skillporter/state.json`.",
        impact="Unmanaged skills lack SHA-256 baseline backups, update tracking, and managed removal protection.",
        suggested_fix="Adopt unmanaged skills into Skillporter tracking.",
        commands=("skillporter adopt --all",),
    ),
    "POLICY_VIOLATION": Explanation(
        code="POLICY_VIOLATION",
        category="security",
        title="Project Security Policy Violation",
        cause=(
            "A skill violates rules configured in `skillporter.policy.yaml` "
            "(source allowlist, risk cap, or banned capability)."
        ),
        impact="Installation, sync, update, or CI check fails closed.",
        suggested_fix="Review `skillporter policy check` output and remediate the skill or update policy rules.",
        commands=("skillporter policy check", "skillporter scan ."),
    ),
    "CAPABILITY_MISMATCH": Explanation(
        code="CAPABILITY_MISMATCH",
        category="security",
        title="Undeclared Sensitive Capability Detected in Skill",
        cause=(
            "Static analysis inferred capabilities (such as `network` or `shell_exec`) "
            "omitted from frontmatter `capabilities:`."
        ),
        impact="Indicates potential capability creep or supply-chain behavior change across versions.",
        suggested_fix="Inspect files exercising the capability and declare legitimate capabilities in `SKILL.md`.",
        commands=("skillporter lint .", "skillporter scan ."),
    ),
    "invalid-capability": Explanation(
        code="invalid-capability",
        category="validation",
        title="Unrecognized Capability Declaration in SKILL.md",
        cause="A value inside `capabilities:` does not match known capability identifiers.",
        impact="Typos in `capabilities:` fail to match inferred static capabilities and cause mismatch warnings.",
        suggested_fix=(
            "Use canonical capability names: `network`, `shell_exec`, `filesystem_read`, "
            "`filesystem_write`, `env_access`, `script_exec`, `subagent_fork`, `hooks`."
        ),
        commands=("skillporter lint . --strict",),
    ),
}


class UnknownFindingCodeError(KeyError):
    """Raised when `explain` is called with an unrecognized error or finding code."""

    def __init__(self, query: str, suggestions: list[str] | None = None) -> None:
        self.query = query
        self.suggestions = suggestions or []
        hint = f" (did you mean: {', '.join(self.suggestions)}?)" if self.suggestions else ""
        super().__init__(
            f"unknown finding or error code {query!r}{hint}; "
            "run `skillporter explain --list` to view all supported codes"
        )


def list_known_explanations() -> list[Explanation]:
    """Return every supported Explanation in deterministic code order."""
    from .security import _FINDING_CATEGORIES, _REMEDIATIONS

    merged: dict[str, Explanation] = dict(EXPLANATIONS)
    for code, rem in sorted(_REMEDIATIONS.items()):
        if code not in merged:
            cat = _FINDING_CATEGORIES.get(code, "security")
            merged[code] = Explanation(
                code=code,
                category=cat,
                title=f"Security Rule `{code}`",
                cause=f"Static security scanner matched rule `{code}` ({cat} category).",
                impact="Blocks installation under default security policy until remediated or reviewed.",
                suggested_fix=rem,
                commands=("skillporter scan .", "skillporter sandbox run <skill>"),
            )
    return [merged[k] for k in sorted(merged, key=lambda x: (x.lower(), x))]


def explain_finding(query: str) -> Explanation:
    """Translate a known code or full diagnostic finding message into an Explanation."""
    import difflib

    from .security import _FINDING_CATEGORIES, _REMEDIATIONS

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

    # 2. Multi-word pasted finding messages from `diagnose` / `doctor` / `lock` / `scan`
    is_sentence = " " in raw or ":" in raw
    if is_sentence:
        for key, exp in EXPLANATIONS.items():
            if len(key) >= 4 and key.lower() in lower:
                return exp
        for sec_code in _REMEDIATIONS:
            if sec_code in lower:
                return explain_finding(sec_code)
        if "content drift" in lower or "drifted" in lower:
            return EXPLANATIONS["DRIFT"]
        if "broken symlink" in lower or "dangling" in lower:
            return EXPLANATIONS["BROKEN"]
        if "not visible to" in lower:
            return EXPLANATIONS["MISSING"]
        if "duplicate" in lower:
            return EXPLANATIONS["DUPLICATE"]
        if "lockfile" in lower or "skillporter.lock" in lower:
            return EXPLANATIONS["LOCK_DRIFT"]
        if "cyclic" in lower or "cycle" in lower:
            return EXPLANATIONS["CYCLE"]
        if "version conflict" in lower or "semver" in lower:
            return EXPLANATIONS["CONFLICT"]
        if "risk_score" in lower or "max_risk_score" in lower:
            return EXPLANATIONS["RISK_THRESHOLD"]

    all_codes = [e.code for e in list_known_explanations()]
    lower_to_canonical = {c.lower(): c for c in all_codes}
    close_lower = difflib.get_close_matches(lower, list(lower_to_canonical.keys()), n=3, cutoff=0.6)
    suggestions = [lower_to_canonical[c] for c in close_lower]
    raise UnknownFindingCodeError(raw, suggestions)
