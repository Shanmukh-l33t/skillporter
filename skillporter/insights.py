"""Skill Context Cost & Local Opt-In Usage Insights Engine (`skillporter insights`).

Distinguishes strictly between:
  1. Estimated context consumption (`4 chars/token` deterministic heuristic across
     always-loaded frontmatter index, on-activation SKILL.md bodies, and agent
     instruction files).
  2. Actual local usage events (`usage.jsonl` recorded only when explicitly triggered
     by the developer or a configured local agent hook — never fabricated).
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .diagnose import diagnose
from .frontmatter import MAX_BODY_TOKENS_WARN, parse_skill
from .install import validate_skill_name_segment
from .instructions import _normalize_directive_key, discover_instruction_files
from .state import state_dir

LARGE_INSTRUCTION_TOKENS = 2500


def usage_log_file(root: Path, *, scope: str = "project") -> Path:
    return state_dir(Path(root).resolve(), scope=scope) / "usage.jsonl"


def record_skill_usage_event(
    root: Path,
    skill_name: str,
    *,
    harness: str = "",
    scope: str = "project",
) -> Path:
    """Append an explicit, local-only opt-in skill activation event to `usage.jsonl`."""
    clean_name = validate_skill_name_segment(skill_name)
    ufile = usage_log_file(root, scope=scope)
    ufile.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "skill": clean_name,
        "harness": harness,
    }
    with open(ufile, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    return ufile


def load_skill_usage_stats(root: Path, *, scope: str = "project") -> tuple[bool, dict[str, dict[str, object]]]:
    """Return `(tracking_active, {skill_name: {'count': int, 'last_used': str}})`."""
    ufile = usage_log_file(root, scope=scope)
    if not ufile.is_file():
        return False, {}
    stats: dict[str, dict[str, object]] = {}
    any_valid = False
    try:
        for raw_line in ufile.read_text(encoding="utf-8").splitlines():
            s = raw_line.strip()
            if not s:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                obj = json.loads(s)
                if isinstance(obj, dict) and obj.get("skill"):
                    any_valid = True
                    sname = str(obj["skill"])
                    ts = str(obj.get("timestamp", ""))
                    rec = stats.setdefault(sname, {"count": 0, "last_used": ""})
                    rec["count"] = int(rec["count"]) + 1  # type: ignore[arg-type]
                    if ts > str(rec["last_used"]):
                        rec["last_used"] = ts
    except OSError:
        return False, {}
    return any_valid, stats


def compute_workspace_insights(root: Path, *, scope: str = "project") -> dict[str, object]:
    """Compute context overhead, duplicates, instruction overlap, and local usage insights."""
    root = Path(root).resolve()
    diag = diagnose(root, scope=scope)
    tracking_active, usage_stats = load_skill_usage_stats(root, scope=scope)

    skills_summary: dict[str, dict[str, object]] = {}
    total_skill_body_tokens = 0
    total_skill_index_tokens = 0
    large_skills: list[str] = []
    unused_skills: list[str] = []
    optimizations: list[str] = []

    for sname in sorted(diag.skill_names):
        copies = diag.skill_copies.get(sname, [])
        if not copies or not (copies[0] / "SKILL.md").is_file():
            continue
        smd = copies[0] / "SKILL.md"
        doc = parse_skill(smd)
        raw_txt = smd.read_text(encoding="utf-8", errors="replace")
        idx_tokens = max(1, len(f"{doc.name}: {doc.description}") // 4)
        body_tokens = max(1, len(doc.body) // 4)
        full_tokens = max(1, len(raw_txt) // 4)

        total_skill_index_tokens += idx_tokens
        total_skill_body_tokens += body_tokens

        loaded_in = sorted(h for h, rep in diag.reports.items() if rep.loads(sname))
        dup_in = sorted(h for h, dmap in diag.duplicates.items() if sname in dmap)
        is_large = body_tokens > MAX_BODY_TOKENS_WARN
        if is_large:
            large_skills.append(sname)
            optimizations.append(
                f"Skill {sname!r} consumes ~{body_tokens} body tokens (recommended <{MAX_BODY_TOKENS_WARN}); "
                "move reference material into references/ to reduce context window overhead."
            )
        if dup_in:
            optimizations.append(
                f"Skill {sname!r} loads twice in {', '.join(dup_in)}; run `skillporter doctor --fix` "
                "or remove redundant harness-specific copies."
            )

        ustat = usage_stats.get(sname)
        ucount = int(ustat["count"]) if ustat else (0 if tracking_active else None)  # type: ignore[arg-type]
        last_used = str(ustat["last_used"]) if ustat else None
        if tracking_active and ucount == 0:
            unused_skills.append(sname)

        skills_summary[sname] = {
            "name": sname,
            "estimated_tokens": full_tokens,
            "index_tokens": idx_tokens,
            "body_tokens": body_tokens,
            "harnesses": loaded_in,
            "duplicate_harnesses": dup_in,
            "oversized": is_large,
            "usage_count": ucount,
            "last_used": last_used,
        }

    if unused_skills:
        optimizations.append(
            f"{len(unused_skills)} skill(s) ({', '.join(unused_skills[:5])}) have 0 recorded local activations; "
            "consider moving rarely used skills into a named profile (`skillporter profile save`)."
        )

    inst_files = []
    total_instruction_tokens = 0
    large_instruction_files: list[str] = []
    overlap_pct = 0.0
    if scope == "project":
        discovered_inst = discover_instruction_files(root)
        key_occ: dict[str, int] = {}
        unscoped_cnt = 0
        for f in discovered_inst:
            total_instruction_tokens += f.estimated_tokens
            inst_files.append(f.to_dict())
            if not f.is_path_scoped:
                for d in f.directives:
                    nk = _normalize_directive_key(d)
                    if nk:
                        unscoped_cnt += 1
                        key_occ[nk] = key_occ.get(nk, 0) + 1
            if f.estimated_tokens > LARGE_INSTRUCTION_TOKENS:
                large_instruction_files.append(f.rel_path)
                optimizations.append(
                    f"Instruction file {f.rel_path!r} consumes ~{f.estimated_tokens} always-loaded tokens; "
                    "extract task-specific workflows into on-demand skills."
                )
        dup_occ = sum(c for c in key_occ.values() if c > 1)
        overlap_pct = round((dup_occ / unscoped_cnt) * 100.0, 1) if unscoped_cnt > 0 else 0.0
        if overlap_pct >= 25.0 and len(discovered_inst) >= 2:
            optimizations.append(
                f"Instruction files have {overlap_pct}% duplicated directives across {len(discovered_inst)} files; "
                "run `skillporter consolidate` to maintain a single canonical source."
            )

    return {
        "root": str(root),
        "scope": scope,
        "token_measurement": "estimated (4 chars/token deterministic heuristic)",
        "usage_tracking_active": tracking_active,
        "usage_data_source": (
            str(usage_log_file(root, scope=scope))
            if tracking_active
            else "none (opt-in local usage.jsonl not yet active; agents do not expose invocation counts by default)"
        ),
        "total_estimated_skill_tokens": total_skill_body_tokens + total_skill_index_tokens,
        "always_loaded_skill_index_tokens": total_skill_index_tokens,
        "total_instruction_tokens": total_instruction_tokens,
        "instruction_overlap_percentage": overlap_pct,
        "skills": skills_summary,
        "instruction_files": inst_files,
        "large_skills": large_skills,
        "large_instruction_files": large_instruction_files,
        "unused_skills": unused_skills,
        "optimization_opportunities": optimizations,
    }
