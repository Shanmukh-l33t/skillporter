"""Human-Readable Skill Update Review Engine (`skillporter update --check`).

Compares an installed skill tree against an upstream candidate tree across:
  * Added, removed, and modified files (instructions vs. scripts)
  * Capability transitions (e.g. NEW: network in scripts/convert.sh:2)
  * Static security risk score delta and newly introduced findings.
"""

from __future__ import annotations

from pathlib import Path

from .capabilities import analyze_capabilities
from .frontmatter import parse_skill
from .security import compute_tree_hash, scan_skill


def _extract_version(skill_dir: Path, fallback: str = "1.0.0") -> str:
    smd = skill_dir / "SKILL.md"
    if not smd.is_file():
        return fallback
    doc = parse_skill(smd)
    if doc.frontmatter.get("version"):
        return str(doc.frontmatter["version"])
    meta = doc.frontmatter.get("metadata")
    if isinstance(meta, dict) and meta.get("version"):
        return str(meta["version"])
    return fallback


def review_skill_update(
    skill_name: str,
    installed_dir: Path,
    candidate_dir: Path,
    *,
    current_version: str = "",
    upstream_version: str = "",
    current_commit: str = "",
    upstream_commit: str = "",
) -> dict[str, object]:
    """Generate a structured, human-readable diff between *installed_dir* and *candidate_dir*."""
    cur_hash, cur_files = compute_tree_hash(installed_dir)
    new_hash, new_files = compute_tree_hash(candidate_dir)

    cur_ver = current_version or _extract_version(installed_dir)
    new_ver = upstream_version or _extract_version(candidate_dir, fallback=cur_ver)

    cur_set = set(cur_files)
    new_set = set(new_files)
    added_files = sorted(new_set - cur_set)
    removed_files = sorted(cur_set - new_set)
    modified_all = sorted(f for f in (cur_set & new_set) if cur_files[f] != new_files[f])

    modified_instructions = [f for f in modified_all if f.endswith((".md", ".mdc", ".txt"))]
    modified_scripts = [f for f in modified_all if f.startswith("scripts/") or f.endswith((".py", ".sh", ".js", ".ts"))]

    cur_caps = analyze_capabilities(installed_dir)
    new_caps = analyze_capabilities(candidate_dir)
    added_caps = sorted(set(new_caps.inferred) - set(cur_caps.inferred))
    removed_caps = sorted(set(cur_caps.inferred) - set(new_caps.inferred))

    cur_sec = scan_skill(installed_dir, offline=True)
    new_sec = scan_skill(candidate_dir, offline=True)
    cur_sig = {(f.code, f.file, f.line, f.message) for f in cur_sec.findings}
    introduced_objs = [f for f in new_sec.findings if (f.code, f.file, f.line, f.message) not in cur_sig]
    introduced_findings = [f.to_dict() for f in introduced_objs]
    resolved_findings = sorted(
        {f.code for f in cur_sec.findings} - {f.code for f in new_sec.findings}
    )

    highlights: list[str] = []
    for f_new in introduced_objs:
        loc_s = f"{f_new.file}:{f_new.line}" if f_new.line else f_new.file
        highlights.append(f"SECURITY [{f_new.severity}]: {f_new.code} in {loc_s} ({f_new.message})")
    for cap in added_caps:
        ev = new_caps.evidence.get(cap, [])
        where = f" in {ev[0]}" if ev else ""
        highlights.append(f"NEW capability '{cap}'{where}")
    for cap in removed_caps:
        highlights.append(f"REMOVED capability '{cap}'")
    for af in added_files:
        highlights.append(f"NEW file: {af}")
    for rf in removed_files:
        highlights.append(f"REMOVED file: {rf}")
    for mi in modified_instructions:
        highlights.append(f"MODIFIED instructions: {mi}")
    for ms in modified_scripts:
        highlights.append(f"MODIFIED script: {ms}")
    if new_sec.risk_score != cur_sec.risk_score:
        highlights.append(
            f"RISK SCORE: {cur_sec.risk_score}/100 -> {new_sec.risk_score}/100 ({new_sec.recommendation})"
        )

    return {
        "skill": skill_name,
        "has_changes": cur_hash != new_hash,
        "current_version": cur_ver,
        "upstream_version": new_ver,
        "current_commit": current_commit[:12] if current_commit else "",
        "upstream_commit": upstream_commit[:12] if upstream_commit else "",
        "current_hash": cur_hash[:12],
        "upstream_hash": new_hash[:12],
        "added_files": added_files,
        "removed_files": removed_files,
        "modified_instructions": modified_instructions,
        "modified_scripts": modified_scripts,
        "new_capabilities": added_caps,
        "removed_capabilities": removed_caps,
        "capability_evidence": {k: new_caps.evidence.get(k, []) for k in added_caps},
        "current_risk_score": cur_sec.risk_score,
        "upstream_risk_score": new_sec.risk_score,
        "upstream_recommendation": new_sec.recommendation,
        "introduced_findings": introduced_findings,
        "resolved_findings": resolved_findings,
        "highlights": highlights,
    }
