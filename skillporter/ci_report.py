"""CI/CD & GitHub App Pull Request Diagnostic Report Generator (`skillporter ci-report`).

Produces an actionable Markdown comment and structured JSON summary suitable for
GitHub Pull Request comments (via the Skillporter GitHub App or GitHub Actions):
  * Reachability matrix across target harnesses
  * SHA-256 content drift & broken symlinks
  * Duplicate loading warnings
  * Security scan verdict & 0-100 risk scores per skill
  * Lockfile staleness (`skillporter lock --check` parity)
  * Copy-pasteable remediation commands.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from . import __version__, harnesses
from .diagnose import diagnose
from .manifest import LOCKFILE_FILENAME, LockfileError, load_lockfile, load_manifest
from .security import compute_tree_hash, scan_skill


def check_lockfile_staleness(root: Path, *, scope: str = "project") -> list[str]:
    """Verify that `skillporter.lock` exists and matches all discovered skills and manifest entries."""
    root = Path(root).resolve()
    lock_path = root / LOCKFILE_FILENAME
    if not lock_path.is_file():
        return [f"missing lockfile: {LOCKFILE_FILENAME} does not exist (run `skillporter lock`)"]

    try:
        lock = load_lockfile(root)
    except LockfileError as exc:
        return [str(exc)]
    manifest = load_manifest(root)
    diag = diagnose(root, scope=scope)
    problems: list[str] = []

    if manifest and manifest.skills:
        for spec in manifest.skills:
            if spec.name not in lock.skills:
                problems.append(
                    f"unpinned manifest skill: {spec.name!r} is in skillporter.yaml "
                    f"but missing from {LOCKFILE_FILENAME}"
                )

    for sname, copies in sorted(diag.skill_copies.items()):
        if sname not in lock.skills:
            problems.append(f"unlocked skill on disk: {sname!r} is not recorded in {LOCKFILE_FILENAME}")
            continue
        locked = lock.skills[sname]
        for cdir in copies:
            rel_c = cdir.relative_to(root).as_posix() if cdir.is_relative_to(root) else str(cdir)
            actual_hash, _ = compute_tree_hash(cdir)
            if locked.tree_hash and actual_hash != locked.tree_hash:
                problems.append(
                    f"lockfile drift on {sname!r} ({rel_c}): locked {locked.tree_hash[:12]} != disk {actual_hash[:12]}"
                )

    for sname, locked in sorted(lock.skills.items()):
        if sname not in diag.skill_copies:
            problems.append(f"missing locked skill on disk: {sname!r} (locked at {locked.tree_hash[:12]})")

    return problems


def generate_ci_report(root: Path, *, scope: str = "project") -> tuple[int, str, dict[str, object]]:
    """Build a comprehensive PR report (exit_code, markdown, json_payload)."""
    root = Path(root).resolve()
    diag = diagnose(root, scope=scope)
    manifest = load_manifest(root)
    max_risk = manifest.max_risk_score if manifest else None

    lock_issues: list[str] = []
    if (root / LOCKFILE_FILENAME).is_file() or manifest is not None:
        lock_issues = check_lockfile_staleness(root, scope=scope)

    sec_summaries: dict[str, dict[str, object]] = {}
    sec_blocked = False
    for sname, copies in sorted(diag.skill_copies.items()):
        cdir = copies[0]
        rep = scan_skill(cdir)
        exceeds = rep.exceeds_risk_threshold(max_risk)
        if not rep.passed or rep.has_structural_escape or exceeds:
            sec_blocked = True
        sec_summaries[sname] = {
            "risk_score": rep.risk_score,
            "risk_level": rep.risk_level,
            "recommendation": rep.recommendation,
            "passed": rep.passed and not exceeds,
            "engine": rep.engine,
            "findings_count": len(rep.findings),
            "tree_hash": rep.tree_hash[:12] if rep.tree_hash else "",
        }

    has_problems = bool(diag.findings or lock_issues or sec_blocked)
    exit_code = 1 if has_problems else 0
    verdict = "FAILED (Action Required)" if has_problems else "PASSED (All Skills Healthy)"

    active_harnesses = sorted(
        set(harnesses.CORE_HARNESS_NAMES)
        | ({h for h in (manifest.harnesses if manifest else []) if h in diag.reports})
    )

    md_lines = [
        "<!-- skillporter-pr-report -->",
        f"## 🛡️ Skillporter CI Report — `{verdict}`",
        "",
        f"**Version:** `skillporter v{__version__}` · **Skills Checked:** `{len(diag.skill_names)}` · "
        f"**Harnesses:** `{', '.join(active_harnesses)}`",
        "",
    ]

    if diag.skill_names:
        md_lines.extend(
            [
                "### 1. Reachability, Security Risk & Lock Status",
                "",
                "| Skill | " + " | ".join(active_harnesses) + " | Risk Score | Security | SHA-256 |",
                "|---|" + "|".join(["---"] * len(active_harnesses)) + "|---:|---|---|",
            ]
        )
        for sname in sorted(diag.skill_names):
            cells = [f"`{diag.reports[h].cell_state(sname)}`" for h in active_harnesses]
            sec_info = sec_summaries.get(sname, {})
            rscore = sec_info.get("risk_score", 0)
            rrec = sec_info.get("recommendation", "APPROVE")
            thash = sec_info.get("tree_hash", "n/a")
            md_lines.append(
                f"| **`{sname}`** | "
                + " | ".join(cells)
                + f" | `{rscore}/100` | `{rrec}` | `{thash}` |"
            )
        md_lines.append("")

    if diag.findings or lock_issues or sec_blocked:
        md_lines.append("### 2. Findings & Blockers")
        md_lines.append("")
        for f in diag.findings:
            md_lines.append(f"- **Diagnostic:** {f}")
        for li in lock_issues:
            md_lines.append(f"- **Lockfile:** {li}")
        for sname, sinfo in sec_summaries.items():
            if not sinfo["passed"]:
                md_lines.append(
                    f"- **Security:** `{sname}` scored `{sinfo['risk_score']}/100` (`{sinfo['recommendation']}`)"
                )
        md_lines.extend(
            [
                "",
                "### 3. Suggested Remediation",
                "",
                "```bash",
                "skillporter doctor --fix",
                "skillporter sync --force",
                "skillporter lock",
                "```",
            ]
        )
    else:
        md_lines.append(
            "✅ **Zero drift, zero broken symlinks, all skills pass security thresholds and match `skillporter.lock`.**"
        )

    markdown = "\n".join(md_lines) + "\n"
    payload = {
        "healthy": not has_problems,
        "verdict": verdict,
        "skills": diag.skill_names,
        "harnesses": active_harnesses,
        "diagnostic_findings": diag.findings,
        "drifted": diag.drifted,
        "duplicates": diag.duplicates,
        "lockfile_issues": lock_issues,
        "security": sec_summaries,
        "markdown": markdown,
    }
    return exit_code, markdown, payload


def post_github_pr_comment(repo: str, pr_number: int, markdown: str, token: str | None = None) -> dict[str, object]:
    """Post or update the Skillporter PR report comment via the GitHub REST API."""
    tok = (token or os.environ.get("GITHUB_TOKEN", "")).strip()
    if not tok:
        raise RuntimeError("GITHUB_TOKEN is required to post a PR comment")
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    body = json.dumps({"body": markdown}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": f"skillporter/{__version__}",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return json.loads(resp.read(1 << 20).decode("utf-8"))
