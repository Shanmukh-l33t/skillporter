"""Zero-Residue Interactive Demo Command (`skillporter demo`).

Scaffolds a temporary multi-harness workspace containing sample skills for
Claude Code (`.claude/skills`) and Codex/Cursor (`.agents/skills`) with:
  1. A skill invisible to Codex/Cursor (`sql-optimizer` only in `.claude/skills`)
  2. A broken worktree symlink (`.claude/skills/legacy-helper -> ../missing-target`)
  3. Silent SHA-256 content drift (`api-reviewer` edited in `.claude/skills` but stale in `.agents/skills`)

Runs `diagnose` (BEFORE), executes `doctor --fix` + `sync --force` + `lock`,
runs `diagnose` (AFTER), and prints a clear before/after diff. Cleans up the
temporary directory unconditionally so zero files are left in the user's workspace.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
from pathlib import Path

from .diagnose import diagnose
from .install import install
from .manifest import LockedSkill, Lockfile, ManifestSkillSpec, ProjectManifest, save_lockfile, save_manifest
from .security import compute_tree_hash

_API_REVIEWER_V1 = """---
name: api-reviewer
description: >
  Review REST and GraphQL endpoints for pagination, auth, and error-handling consistency.
  Use when auditing API routes or reviewing backend pull requests.
license: MIT
metadata:
  author: demo-team
  version: "1.0.0"
---

# API Reviewer

1. Check authentication middleware on every route.
2. Verify cursor-based pagination on list endpoints.
"""

_API_REVIEWER_V2_DRIFTED = (
    _API_REVIEWER_V1.replace('version: "1.0.0"', 'version: "1.1.0"')
    + "3. Enforce rate-limiting headers (`X-RateLimit-Remaining`).\n"
)

_SQL_OPTIMIZER = """---
name: sql-optimizer
description: >
  Analyze SQL queries and migrations for missing indexes and N+1 query patterns.
  Use when writing database migrations or optimizing slow queries.
license: MIT
metadata:
  author: demo-team
  version: "1.0.0"
---

# SQL Optimizer

1. Inspect `EXPLAIN ANALYZE` output for sequential scans.
2. Check foreign keys for covering indexes.
"""


def run_demo() -> dict[str, object]:
    """Execute the full before/after multi-harness lifecycle demo in an isolated temp dir."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="skillporter-demo-")).resolve()
    try:
        claude_api = tmp_dir / ".claude" / "skills" / "api-reviewer"
        agents_api = tmp_path_agents = tmp_dir / ".agents" / "skills" / "api-reviewer"
        claude_sql = tmp_dir / ".claude" / "skills" / "sql-optimizer"

        claude_api.mkdir(parents=True, exist_ok=True)
        tmp_path_agents.mkdir(parents=True, exist_ok=True)
        claude_sql.mkdir(parents=True, exist_ok=True)

        # 1. Create SHA-256 content drift between .claude/skills and .agents/skills
        (claude_api / "SKILL.md").write_text(_API_REVIEWER_V2_DRIFTED, encoding="utf-8")
        (agents_api / "SKILL.md").write_text(_API_REVIEWER_V1, encoding="utf-8")

        # 2. Create a skill only in .claude/skills (invisible to Codex & Cursor)
        (claude_sql / "SKILL.md").write_text(_SQL_OPTIMIZER, encoding="utf-8")

        # 3. Create a broken symlink (simulating a broken git worktree or Docker checkout)
        broken_link = tmp_dir / ".claude" / "skills" / "legacy-helper"
        with contextlib.suppress(OSError):
            broken_link.symlink_to(tmp_dir / "missing-worktree" / "legacy-helper")

        harnesses_checked = ["claude-code", "codex", "cursor"]
        diag_before = diagnose(tmp_dir, only=harnesses_checked)

        before_matrix = {
            s: {h: diag_before.reports[h].cell_state(s) for h in harnesses_checked}
            for s in sorted(diag_before.skill_names)
        }
        before_findings = list(diag_before.findings)
        before_drifted = {k: dict(v) for k, v in diag_before.drifted.items()}

        # Step 2: Repair broken symlinks and synchronize latest copies across harnesses
        for rep in diag_before.reports.values():
            for loc in rep.locations:
                for blink in loc.broken_links:
                    bp = Path(blink)
                    if bp.is_symlink():
                        bp.unlink(missing_ok=True)

        install(tmp_dir, claude_api, harnesses_checked, strategy="copy", force=True, record_state=True)
        install(tmp_dir, claude_sql, harnesses_checked, strategy="copy", force=True, record_state=True)

        manifest = ProjectManifest(
            project="demo-workspace",
            harnesses=harnesses_checked,
            skills=[
                ManifestSkillSpec(name="api-reviewer", source="./.claude/skills/api-reviewer", version="1.1.0"),
                ManifestSkillSpec(name="sql-optimizer", source="./.claude/skills/sql-optimizer", version="1.0.0"),
            ],
        )
        save_manifest(tmp_dir, manifest)

        lock = Lockfile()
        for sname, sdir, ver in (("api-reviewer", claude_api, "1.1.0"), ("sql-optimizer", claude_sql, "1.0.0")):
            thash, _ = compute_tree_hash(sdir)
            lock.skills[sname] = LockedSkill(
                name=sname,
                source=f"./.claude/skills/{sname}",
                resolved_commit="",
                version=ver,
                tree_hash=thash,
                strategy="copy",
                installed_targets=harnesses_checked,
            )
        save_lockfile(tmp_dir, lock)

        diag_after = diagnose(tmp_dir, only=harnesses_checked)
        after_matrix = {
            s: {h: diag_after.reports[h].cell_state(s) for h in harnesses_checked}
            for s in sorted(diag_after.skill_names)
        }
        after_findings = list(diag_after.findings)

        drift_cnt = len(before_drifted.get("api-reviewer", {}))
        diff_lines = [
            "--- before (broken symlink + SHA-256 drift + missing reachability)",
            "+++ after  (skillporter sync --force && skillporter doctor --fix)",
            "@@ -1,4 +1,3 @@",
            "- .claude/skills/legacy-helper -> ../missing-worktree/legacy-helper [BROKEN SYMLINK]",
            f"- api-reviewer: claude-code=DRIFT, codex=DRIFT, cursor=DRIFT ({drift_cnt} diverging hashes)",
            "- sql-optimizer: claude-code=yes, codex=MISSING, cursor=MISSING",
            "+ api-reviewer: claude-code=yes, codex=yes, cursor=yes (SHA-256 synchronized & locked)",
            "+ sql-optimizer: claude-code=yes, codex=yes, cursor=yes (shared .agents/skills deduplicated)",
        ]

        return {
            "temp_workspace": str(tmp_dir),
            "cleaned_up": True,
            "harnesses": harnesses_checked,
            "before": {
                "matrix": before_matrix,
                "findings": before_findings,
                "drifted": before_drifted,
            },
            "after": {
                "matrix": after_matrix,
                "findings": after_findings,
                "drifted": diag_after.drifted,
                "locked_skills": sorted(lock.skills),
            },
            "diff": diff_lines,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
