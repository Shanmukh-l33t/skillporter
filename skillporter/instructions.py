"""Multi-Agent Instruction Discovery, Consolidation, Bidirectional Sync & Active Context Engine.

Solves instruction fragmentation across AI coding agents (CLAUDE.md, AGENTS.md,
GEMINI.md, .cursor/rules/*.mdc, .github/copilot-instructions.md, .windsurfrules,
.clinerules, .roorules, CONVENTIONS.md, .continuerules, .goosehints) without
forcing project conventions into SKILL.md packages.

Safety invariants:
  * Read-only discovery and analysis by default (`consolidate` modifies nothing without `--apply`).
  * Automatic timestamped backup of all original instruction files under
    `.skillporter/backups/instructions/<backup_id>/` prior to writing.
  * SHA-256 tracking of generated outputs in `.skillporter/instructions/state.json`
    so manual edits to agent files are detected and never silently overwritten.
  * Bidirectional `--reconcile` imports manual additions back into canonical.md.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import harnesses
from .atomic import atomic_write_text, workspace_lock
from .diagnose import diagnose
from .frontmatter import parse_skill, split_frontmatter
from .state import state_dir

MANAGED_MARKER_PREFIX = "<!-- skillporter-managed-instructions:"

_STATIC_INSTRUCTION_SPECS: tuple[tuple[str, tuple[str, ...], str, int], ...] = (
    ("CLAUDE.md", ("claude-code",), "project-root", 10),
    (".claude/CLAUDE.md", ("claude-code",), "project-dir", 20),
    (
        "AGENTS.md",
        ("codex", "cursor", "opencode", "zed", "openhands", "goose", "gemini-cli"),
        "cross-agent-root",
        10,
    ),
    ("GEMINI.md", ("gemini-cli",), "project-root", 15),
    (".gemini/GEMINI.md", ("gemini-cli",), "project-dir", 20),
    (".cursorrules", ("cursor",), "legacy-root", 30),
    (".github/copilot-instructions.md", ("github-copilot",), "project-dir", 10),
    (".windsurfrules", ("windsurf",), "project-root", 20),
    (".clinerules", ("cline",), "project-root", 15),
    (".roorules", ("roo-code",), "project-root", 15),
    ("CONVENTIONS.md", ("aider",), "project-root", 15),
    (".continuerules", ("continue",), "project-root", 20),
    (".goosehints", ("goose",), "project-root", 15),
)

_GLOB_INSTRUCTION_SPECS: tuple[tuple[str, str, tuple[str, ...], str, int], ...] = (
    (".cursor/rules", "*.mdc", ("cursor",), "scoped-rule", 15),
    (".cursor/rules", "*.md", ("cursor",), "scoped-rule", 15),
    (".github/instructions", "*.instructions.md", ("github-copilot",), "scoped-rule", 15),
    (".windsurf/rules", "*.md", ("windsurf",), "scoped-rule", 15),
    (".clinerules", "*.md", ("cline",), "scoped-rule", 15),
    (".roo/rules", "*.md", ("roo-code",), "scoped-rule", 15),
    (".continue/rules", "*.md", ("continue",), "scoped-rule", 15),
)

_AGENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "claude-code": ("claude", "subagent", "claudecode"),
    "cursor": ("cursor", ".mdc", "alwaysapply", "composer"),
    "github-copilot": ("copilot", "github copilot"),
    "windsurf": ("windsurf", "cascade"),
    "aider": ("aider", "/add", "/architect"),
    "gemini-cli": ("gemini cli", "gemini.md"),
    "cline": ("cline",),
    "roo-code": ("roo code", "roocode"),
    "codex": ("codex",),
}

_EXCLUSIVE_TOOL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("JavaScript package manager", ("pnpm", "npm", "yarn", "bun")),
    ("Python environment/package manager", ("uv", "poetry", "pipenv", "conda")),
    ("JavaScript test runner", ("vitest", "jest")),
    ("E2E browser test runner", ("playwright", "cypress")),
    ("Python test runner", ("pytest", "unittest")),
    ("Indentation style", ("tabs", "spaces")),
)

_NEGATION_RE = re.compile(r"\b(?:never|do\s+not|don't|forbid|forbidden|avoid|instead\s+of|not\s+use)\b", re.IGNORECASE)
_AFFIRMATIVE_RE = re.compile(r"\b(?:always|must|prefer|use|run|standardize\s+on)\b", re.IGNORECASE)
_BACKTICK_PATH_RE = re.compile(
    r"`((?:src|app|lib|packages|scripts|tests|cmd|internal|config|backend|frontend)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`"
)


class InstructionError(RuntimeError):
    """Raised when an instruction consolidation or reconciliation operation cannot proceed safely."""


@dataclass
class DiscoveredInstructionFile:
    """Metadata and extracted directives from one agent instruction file."""

    rel_path: str
    abs_path: Path
    harnesses: list[str]
    scope_kind: str
    precedence: int
    managed: bool
    sha256: str
    estimated_tokens: int
    directives: list[str] = field(default_factory=list)
    preserved_blocks: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)
    is_path_scoped: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.rel_path,
            "harnesses": self.harnesses,
            "scope_kind": self.scope_kind,
            "precedence": self.precedence,
            "managed": self.managed,
            "is_path_scoped": self.is_path_scoped,
            "sha256": self.sha256[:16],
            "estimated_tokens": self.estimated_tokens,
            "directive_count": len(self.directives),
            "unclassified_count": len(self.unclassified),
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_directive_key(line: str) -> str:
    clean = re.sub(r"[`*_]", "", line.strip().lower())
    clean = re.sub(r"^[-*+]\s+|^\d+\.\s+", "", clean)
    clean = re.sub(r"\s+", " ", clean).rstrip(".;:")
    return clean


def extract_directives_and_blocks(text: str) -> tuple[list[str], list[str], list[str]]:
    """Extract directives, preserved blocks, and unclassified lines from instruction content.

    Returns ``(directives, blocks, unclassified)``:
      * ``directives``: top-level bullets (nested child items stay attached to their parent
        with original indentation), ``>`` blockquotes, and paragraph lines of 15+ characters.
      * ``blocks``: fenced code blocks (``` and ~~~) and Markdown tables, verbatim.
      * ``unclassified``: non-empty lines that fit none of the above (e.g. ``Node >= 24``).
        Callers MUST keep these in generated files and report them; nothing is silently dropped.

    Headings (``#``) are structural and excluded; their text remains in the consolidation backup.
    """
    _, body = split_frontmatter(text)
    in_code_block = False
    code_lines: list[str] = []
    code_fence = ""
    table_lines: list[str] = []
    directives: list[str] = []
    blocks: list[str] = []
    unclassified: list[str] = []
    current: list[str] = []  # [parent_content, *raw child lines] for the open top-level bullet

    def flush_list() -> None:
        if current:
            directives.append("\n".join(current))
            current.clear()

    def flush_table() -> None:
        if table_lines:
            blocks.append("\n".join(table_lines))
            table_lines.clear()

    for raw in body.splitlines():
        s = raw.strip()
        if in_code_block:
            code_lines.append(raw)
            if s.startswith(code_fence):
                blocks.append("\n".join(code_lines))
                code_lines = []
                in_code_block = False
                code_fence = ""
            continue
        if not s:
            continue
        if s.startswith(("```", "~~~")):
            flush_table()
            flush_list()
            in_code_block = True
            code_fence = s[:3]
            code_lines = [raw]
            continue
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 2:
            flush_list()
            table_lines.append(raw)
            continue
        flush_table()
        if s.startswith("#"):
            flush_list()
            continue
        m_bullet = re.match(r"^(?:[-*+]|\d+\.)\s+(.+)$", s)
        if m_bullet:
            indent = len(raw) - len(raw.lstrip())
            if current and indent > 0:
                current.append(raw.rstrip())  # nested child: keep verbatim indentation
            else:
                flush_list()
                current.append(m_bullet.group(1).strip())
            continue
        flush_list()
        if s.startswith(">"):
            directives.append(s.lstrip(">").strip())
        elif s.startswith("<!--"):
            continue
        elif len(s) >= 15 and not s.endswith(":"):
            directives.append(s)
        else:
            unclassified.append(s)

    if in_code_block and code_lines:  # unterminated fence: keep content rather than dropping it
        blocks.append("\n".join(code_lines))
    flush_table()
    flush_list()
    return directives, blocks, unclassified


def extract_directives(text: str) -> list[str]:
    """Extract atomic instruction bullets and imperative lines from Markdown/MDC content."""
    dirs, _blocks, _unclassified = extract_directives_and_blocks(text)
    return dirs


def _is_scoped_rule_file(rel_path: str, text: str) -> bool:
    """Return True if *rel_path* is a path/glob-scoped rule that must not be flattened into global rules."""
    if rel_path.endswith(("project-instructions.mdc", "project-instructions.md")):
        return False
    fm, _ = split_frontmatter(text)
    if rel_path.startswith(".cursor/rules/"):
        globs = fm.get("globs")
        always = str(fm.get("alwaysApply", "")).strip().lower()
        if globs and str(globs).strip() not in ("", "*", "**", "[]"):
            return True
        if always == "false":
            return True
    if rel_path.startswith(".github/instructions/"):
        apply_to = str(fm.get("applyTo", "")).strip()
        if apply_to and apply_to not in ("*", "**"):
            return True
    return False


def discover_instruction_files(root: Path) -> list[DiscoveredInstructionFile]:
    """Discover all agent instruction and rule files in *root*."""
    root = root.resolve()
    found: dict[str, DiscoveredInstructionFile] = {}

    for rel_p, h_tuple, kind, prec in _STATIC_INSTRUCTION_SPECS:
        cand = root / rel_p
        if cand.is_file() and not cand.is_symlink():
            text = cand.read_text(encoding="utf-8", errors="replace")
            dirs, blks, uncls = extract_directives_and_blocks(text)
            found[rel_p] = DiscoveredInstructionFile(
                rel_path=rel_p,
                abs_path=cand,
                harnesses=list(h_tuple),
                scope_kind=kind,
                precedence=prec,
                managed=(MANAGED_MARKER_PREFIX in text),
                sha256=_sha256_text(text),
                estimated_tokens=max(1, len(text) // 4),
                directives=dirs,
                preserved_blocks=blks,
                unclassified=uncls,
                is_path_scoped=False,
            )

    for rel_dir, pat, h_tuple, kind, prec in _GLOB_INSTRUCTION_SPECS:
        dpath = root / rel_dir
        if not dpath.is_dir():
            continue
        for cand in sorted(dpath.glob(pat)):
            if not cand.is_file() or cand.is_symlink():
                continue
            rel_p = cand.relative_to(root).as_posix()
            if rel_p in found:
                continue
            text = cand.read_text(encoding="utf-8", errors="replace")
            dirs, blks, uncls = extract_directives_and_blocks(text)
            found[rel_p] = DiscoveredInstructionFile(
                rel_path=rel_p,
                abs_path=cand,
                harnesses=list(h_tuple),
                scope_kind=kind,
                precedence=prec,
                managed=(MANAGED_MARKER_PREFIX in text),
                sha256=_sha256_text(text),
                estimated_tokens=max(1, len(text) // 4),
                directives=dirs,
                preserved_blocks=blks,
                unclassified=uncls,
                is_path_scoped=_is_scoped_rule_file(rel_p, text),
            )

    return [found[k] for k in sorted(found)]


def _classify_agent_specific(directive: str, file_harnesses: list[str]) -> str | None:
    low = directive.lower()
    for hname, keywords in _AGENT_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return hname
    if len(file_harnesses) == 1 and any(tok in low for tok in ("glob:", "applyto:", "mode-specific")):
        return file_harnesses[0]
    return None


def _detect_conflicts(files: list[DiscoveredInstructionFile]) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str, str]] = set()

    # 1. Mutually exclusive tool preferences across files
    for group_label, choices in _EXCLUSIVE_TOOL_GROUPS:
        affirmative_by_tool: dict[str, list[tuple[str, str]]] = {}
        for f in files:
            for d in f.directives:
                low = d.lower()
                if not _AFFIRMATIVE_RE.search(low):
                    continue
                for tool in choices:
                    if re.search(rf"\b{re.escape(tool)}\b", low):
                        # Ignore negated mentions like "never use npm"
                        neg_near = re.search(
                            rf"\b(?:never|not|avoid|instead of)\s+(?:use\s+|using\s+|run\s+)?{re.escape(tool)}\b",
                            low,
                        )
                        if not neg_near:
                            affirmative_by_tool.setdefault(tool, []).append((f.rel_path, d))
        if len(affirmative_by_tool) >= 2:
            tools_found = sorted(affirmative_by_tool)
            t1, t2 = tools_found[0], tools_found[1]
            f1, d1 = affirmative_by_tool[t1][0]
            f2, d2 = affirmative_by_tool[t2][0]
            key = (group_label, min(f1, f2), max(f1, f2))
            if key not in seen_pairs:
                seen_pairs.add(key)
                conflicts.append(
                    {
                        "category": group_label,
                        "summary": f"Conflicting {group_label}: {f1} specifies '{t1}' vs {f2} specifies '{t2}'",
                        "file_a": f1,
                        "directive_a": d1,
                        "file_b": f2,
                        "directive_b": d2,
                    }
                )

    # 2. Polarity negation conflicts via O(N) inverted token index (negated vs affirmative)
    stop_toks = {"always", "never", "prefer", "before", "should", "must", "avoid"}
    negated_items: list[tuple[str, str, set[str]]] = []
    affirmative_by_tok: dict[str, list[int]] = {}
    affirmative_items: list[tuple[str, str, set[str]]] = []

    for f in files:
        for d in f.directives:
            toks = {w for w in re.findall(r"[a-z0-9]{4,}", d.lower()) if w not in stop_toks}
            if len(toks) < 3:
                continue
            if _NEGATION_RE.search(d):
                negated_items.append((f.rel_path, d, toks))
            else:
                a_idx = len(affirmative_items)
                affirmative_items.append((f.rel_path, d, toks))
                for tok in toks:
                    affirmative_by_tok.setdefault(tok, []).append(a_idx)

    for f1, d1, toks1 in negated_items:
        cand_counts: dict[int, int] = {}
        for tok in toks1:
            for a_idx in affirmative_by_tok.get(tok, ()):
                cand_counts[a_idx] = cand_counts.get(a_idx, 0) + 1
        for a_idx, overlap_n in cand_counts.items():
            if overlap_n < 3:
                continue
            f2, d2, toks2 = affirmative_items[a_idx]
            if f1 == f2:
                continue
            shared_toks = sorted(toks1 & toks2)
            key = ("polarity:" + ",".join(shared_toks[:3]), min(f1, f2), max(f1, f2))
            if key not in seen_pairs:
                seen_pairs.add(key)
                conflicts.append(
                    {
                        "category": "contradictory-directive",
                        "summary": (
                            f"Contradictory polarity on ({', '.join(shared_toks[:3])}) "
                            f"between {f1} and {f2}"
                        ),
                        "file_a": f1,
                        "directive_a": d1,
                        "file_b": f2,
                        "directive_b": d2,
                    }
                )

    return conflicts


def _detect_outdated_references(root: Path, files: list[DiscoveredInstructionFile]) -> list[dict[str, str]]:
    outdated: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for f in files:
        for d in f.directives:
            for m in _BACKTICK_PATH_RE.finditer(d):
                ref = m.group(1)
                if "*" in ref or "<" in ref:
                    continue
                if not (root / ref).exists() and (f.rel_path, ref) not in seen:
                    seen.add((f.rel_path, ref))
                    outdated.append(
                        {
                            "file": f.rel_path,
                            "reference": ref,
                            "directive": d,
                            "reason": f"referenced path '{ref}' does not exist in workspace",
                        }
                    )
    return outdated


def _instructions_dir(root: Path) -> Path:
    return state_dir(root.resolve()) / "instructions"


def _instructions_state_file(root: Path) -> Path:
    return _instructions_dir(root) / "state.json"


def _load_instructions_state(root: Path) -> dict[str, object]:
    sf = _instructions_state_file(root)
    if not sf.is_file():
        return {}
    try:
        raw = json.loads(sf.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def detect_manual_instruction_modifications(root: Path) -> list[dict[str, object]]:
    """Detect managed agent instruction files modified manually since last consolidation."""
    root = root.resolve()
    st = _load_instructions_state(root)
    managed_files = st.get("managed_files", {})
    if not isinstance(managed_files, dict) or not managed_files:
        return []

    canonical_path = _instructions_dir(root) / "canonical.md"
    canonical_directives = (
        extract_directives(canonical_path.read_text(encoding="utf-8")) if canonical_path.is_file() else []
    )
    canonical_keys = {_normalize_directive_key(d): d for d in canonical_directives}

    modifications: list[dict[str, object]] = []
    for rel_p, meta in sorted(managed_files.items()):
        if not isinstance(meta, dict):
            continue
        expected_sha = str(meta.get("sha256", ""))
        fpath = root / rel_p
        if not fpath.is_file():
            modifications.append(
                {
                    "file": rel_p,
                    "status": "deleted",
                    "added_directives": [],
                    "removed_directives": list(canonical_directives),
                }
            )
            continue
        current_text = fpath.read_text(encoding="utf-8", errors="replace")
        current_sha = _sha256_text(current_text)
        if expected_sha and current_sha != expected_sha:
            cur_dirs = extract_directives(current_text)
            cur_keys = {_normalize_directive_key(d): d for d in cur_dirs}
            harness_id = str(meta.get("harness", ""))
            agent_override_file = _instructions_dir(root) / "agents" / f"{harness_id}.md"
            if agent_override_file.is_file():
                override_dirs = extract_directives(agent_override_file.read_text(encoding="utf-8"))
                agent_keys = {_normalize_directive_key(d): d for d in override_dirs}
            else:
                agent_keys = {}
            expected_all_keys = {**canonical_keys, **agent_keys}
            added = [d for k, d in cur_keys.items() if k not in expected_all_keys]
            removed = [d for k, d in expected_all_keys.items() if k not in cur_keys]
            modifications.append(
                {
                    "file": rel_p,
                    "harness": harness_id,
                    "status": "modified",
                    "expected_sha256": expected_sha[:16],
                    "actual_sha256": current_sha[:16],
                    "added_directives": added,
                    "removed_directives": removed,
                }
            )
    return modifications


def render_native_instruction_target(
    harness_id: str,
    shared_directives: list[str],
    agent_directives: list[str],
    *,
    preferred_rel_path: str = "",
    preserved_blocks: list[str] | None = None,
    unclassified_lines: list[str] | None = None,
) -> tuple[str, str]:
    """Render consolidated shared + agent-specific instructions into a harness's native file format."""
    prov = f"{MANAGED_MARKER_PREFIX} source=.skillporter/instructions/canonical.md harness={harness_id} -->"
    shared_lines = (
        "\n".join(f"- {d}" for d in shared_directives)
        if shared_directives
        else "- Follow repository standards."
    )
    blocks_section = ""
    if preserved_blocks:
        blocks_section = "\n\n## Commands & Reference Blocks\n\n" + "\n\n".join(preserved_blocks)
    if unclassified_lines:
        blocks_section += "\n\n## Preserved Unclassified Lines\n\n" + "\n".join(unclassified_lines)
    agent_section = ""
    if agent_directives:
        agent_bullets = "\n".join(f"- {d}" for d in agent_directives)
        agent_section = f"\n\n## Agent-Specific Guidelines ({harness_id})\n\n{agent_bullets}"

    if preferred_rel_path:
        rel_out = preferred_rel_path
    elif harness_id == "claude-code":
        rel_out = "CLAUDE.md"
    elif harness_id in ("codex", "opencode", "zed", "openhands"):
        rel_out = "AGENTS.md"
    elif harness_id == "gemini-cli":
        rel_out = "GEMINI.md"
    elif harness_id == "github-copilot":
        rel_out = ".github/copilot-instructions.md"
    elif harness_id == "cursor":
        rel_out = ".cursor/rules/project-instructions.mdc"
    elif harness_id == "windsurf":
        rel_out = ".windsurf/rules/project-instructions.md"
    elif harness_id == "aider":
        rel_out = "CONVENTIONS.md"
    elif harness_id == "cline":
        rel_out = ".clinerules"
    elif harness_id == "roo-code":
        rel_out = ".roorules"
    elif harness_id == "continue":
        rel_out = ".continue/rules/project-instructions.md"
    elif harness_id == "goose":
        rel_out = ".goosehints"
    else:
        rel_out = "AGENTS.md"

    if rel_out.endswith(".mdc"):
        content = (
            "---\n"
            'description: "Consolidated project engineering instructions"\n'
            "globs:\n"
            "alwaysApply: true\n"
            "---\n\n"
            f"{prov}\n\n"
            "# Project Instructions\n\n"
            f"{shared_lines}{blocks_section}{agent_section}\n"
        )
    else:
        content = f"{prov}\n\n# Project Instructions\n\n{shared_lines}{blocks_section}{agent_section}\n"
    return rel_out, content


def analyze_instructions(root: Path, *, target_harnesses: list[str] | None = None) -> dict[str, object]:
    """Analyze all workspace instruction files without modifying disk state."""
    root = root.resolve()
    files = discover_instruction_files(root)
    key_occurrences: dict[str, int] = {}
    ordered_shared: list[str] = []
    seen_shared_keys: set[str] = set()
    agent_specific: dict[str, list[str]] = {}
    seen_agent_keys: dict[str, set[str]] = {}
    preserved_blocks: list[str] = []
    seen_block_hashes: set[str] = set()
    unclassified_sections: list[dict[str, str]] = []
    unclassified_lines: list[str] = []
    seen_unclassified: set[str] = set()

    for f in files:
        if f.is_path_scoped:
            continue
        for ul in f.unclassified:
            unclassified_sections.append({"file": f.rel_path, "text": ul})
            if ul not in seen_unclassified:
                seen_unclassified.add(ul)
                unclassified_lines.append(ul)
        for blk in f.preserved_blocks:
            bh = _sha256_text(blk.strip())
            if bh not in seen_block_hashes:
                seen_block_hashes.add(bh)
                preserved_blocks.append(blk)
        for d in f.directives:
            k = _normalize_directive_key(d)
            if not k:
                continue
            key_occurrences[k] = key_occurrences.get(k, 0) + 1
            spec_agent = _classify_agent_specific(d, f.harnesses)
            if spec_agent:
                aset = seen_agent_keys.setdefault(spec_agent, set())
                if k not in aset:
                    aset.add(k)
                    agent_specific.setdefault(spec_agent, []).append(d)
            elif k not in seen_shared_keys:
                seen_shared_keys.add(k)
                ordered_shared.append(d)

    unscoped_files = [f for f in files if not f.is_path_scoped]
    total_occ = sum(len(f.directives) for f in unscoped_files)
    dup_occ = sum(cnt for cnt in key_occurrences.values() if cnt > 1)
    overlap_pct = round((dup_occ / total_occ) * 100.0, 1) if total_occ > 0 else 0.0

    conflicts = _detect_conflicts(files)
    outdated = _detect_outdated_references(root, files)
    manual_mods = detect_manual_instruction_modifications(root)

    # Determine target outputs to preview/generate (never overwrite path-scoped rule files!)
    file_targets: list[tuple[str, str]] = []
    if target_harnesses:
        for h in target_harnesses:
            cname = harnesses.get(h).name
            rel_p, _ = render_native_instruction_target(
                cname,
                ordered_shared,
                agent_specific.get(cname, []),
                preserved_blocks=preserved_blocks,
                unclassified_lines=unclassified_lines,
            )
            if all(rp != rel_p for rp, _ in file_targets):
                file_targets.append((rel_p, cname))
    else:
        for f in unscoped_files:
            primary_h = f.harnesses[0] if f.harnesses else "codex"
            file_targets.append((f.rel_path, primary_h))

    proposed_outputs: dict[str, str] = {}
    for rel_p, hname in file_targets:
        _, rendered = render_native_instruction_target(
            hname,
            ordered_shared,
            agent_specific.get(hname, []),
            preferred_rel_path=rel_p,
            preserved_blocks=preserved_blocks,
            unclassified_lines=unclassified_lines,
        )
        proposed_outputs[rel_p] = rendered

    all_agents = sorted({h for f in files for h in f.harnesses})
    return {
        "root": str(root),
        "discovered_files": [f.to_dict() for f in files],
        "preserved_scoped_files": [f.rel_path for f in files if f.is_path_scoped],
        "agents_covered": all_agents,
        "overlap_percentage": overlap_pct,
        "shared_instructions": ordered_shared,
        "preserved_blocks": preserved_blocks,
        "unclassified_sections": unclassified_sections,
        "unclassified_lines": unclassified_lines,
        "agent_specific_instructions": agent_specific,
        "conflicts": conflicts,
        "outdated_instructions": outdated,
        "manual_modifications": manual_mods,
        "proposed_canonical_path": ".skillporter/instructions/canonical.md",
        "proposed_outputs": proposed_outputs,
    }


def apply_consolidation(
    root: Path,
    *,
    target_harnesses: list[str] | None = None,
    force: bool = False,
    reconcile: bool = False,
) -> dict[str, object]:
    """Safely back up originals, write canonical instructions, and emit native agent files."""
    root = root.resolve()
    with workspace_lock(root):
        manual_mods = detect_manual_instruction_modifications(root)
        if manual_mods and not force and not reconcile:
            mod_files = ", ".join(str(m["file"]) for m in manual_mods)
            raise InstructionError(
                f"manual modifications detected in managed instruction file(s): {mod_files}; "
                "pass --reconcile to merge edits into canonical.md, or --force to overwrite"
            )

        analysis = analyze_instructions(root, target_harnesses=target_harnesses)
        conflicts_found: list[dict[str, str]] = list(analysis["conflicts"])  # type: ignore[arg-type]
        if conflicts_found and not force:
            first_c = conflicts_found[0]["summary"]
            raise InstructionError(
                f"refusing to apply contradictory instructions ({len(conflicts_found)} conflict(s), "
                f"e.g. {first_c}); resolve conflicts in source files first or pass --force"
            )

        shared_list: list[str] = list(analysis["shared_instructions"])  # type: ignore[arg-type]
        preserved_blks: list[str] = list(analysis.get("preserved_blocks", []))  # type: ignore[arg-type]
        uncls_lines: list[str] = list(analysis.get("unclassified_lines", []))  # type: ignore[arg-type]
        agent_map: dict[str, list[str]] = {
            k: list(v) for k, v in analysis["agent_specific_instructions"].items()  # type: ignore[union-attr]
        }

        if reconcile and manual_mods:
            existing_keys = {_normalize_directive_key(d) for d in shared_list}
            for m in manual_mods:
                for added_d in m.get("added_directives", []):  # type: ignore[union-attr]
                    nk = _normalize_directive_key(str(added_d))
                    if nk and nk not in existing_keys:
                        existing_keys.add(nk)
                        shared_list.append(str(added_d))

        files = discover_instruction_files(root)
        if not files and not shared_list:
            raise InstructionError(f"no instruction files discovered under {root} to consolidate")

        # 1. Back up existing files before first write (or before every overwrite)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        st_prev = _load_instructions_state(root)
        initial_backup_dir_str = str(st_prev.get("initial_backup_dir", ""))
        backup_root = state_dir(root) / "backups" / "instructions" / f"{ts}-{uuid.uuid4().hex[:8]}"
        backed_up: list[str] = []
        for f in files:
            bdest = backup_root / f.rel_path
            bdest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f.abs_path, bdest)
            backed_up.append(f.rel_path)

        if not initial_backup_dir_str or not Path(initial_backup_dir_str).is_dir():
            initial_backup_dir_str = str(backup_root)

        # 2. Write canonical source of truth
        idir = _instructions_dir(root)
        idir.mkdir(parents=True, exist_ok=True)
        canonical_md = "# Canonical Project Instructions\n\n" + "\n".join(f"- {d}" for d in shared_list) + "\n"
        if preserved_blks:
            canonical_md += "\n## Commands & Reference Blocks\n\n" + "\n\n".join(preserved_blks) + "\n"
        if uncls_lines:
            canonical_md += "\n## Preserved Unclassified Lines\n\n" + "\n".join(uncls_lines) + "\n"
        atomic_write_text(idir / "canonical.md", canonical_md)

        for hname, alist in sorted(agent_map.items()):
            if alist:
                apath = idir / "agents" / f"{hname}.md"
                atomic_write_text(apath, f"# {hname} Instructions\n\n" + "\n".join(f"- {d}" for d in alist) + "\n")

        # 3. Render and write target agent files
        managed_records: dict[str, dict[str, str]] = {}
        written_files: list[str] = []
        proposed = analysis["proposed_outputs"]
        target_keys = list(proposed.keys()) if isinstance(proposed, dict) else []
        for rel_p in target_keys:
            matched_f = next((f for f in files if f.rel_path == rel_p), None)
            h_id = matched_f.harnesses[0] if (matched_f and matched_f.harnesses) else "codex"
            if target_harnesses:
                for th in target_harnesses:
                    cname = harnesses.get(th).name
                    rp_cand, _ = render_native_instruction_target(
                        cname,
                        shared_list,
                        agent_map.get(cname, []),
                        preserved_blocks=preserved_blks,
                        unclassified_lines=uncls_lines,
                    )
                    if rp_cand == rel_p:
                        h_id = cname
                        break
            _, out_content = render_native_instruction_target(
                h_id,
                shared_list,
                agent_map.get(h_id, []),
                preferred_rel_path=rel_p,
                preserved_blocks=preserved_blks,
                unclassified_lines=uncls_lines,
            )
            dest_p = root / rel_p
            atomic_write_text(dest_p, out_content)
            managed_records[rel_p] = {
                "harness": h_id,
                "sha256": _sha256_text(out_content),
            }
            written_files.append(rel_p)

        state_payload = {
            "schema_version": 1,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "initial_backup_dir": initial_backup_dir_str,
            "latest_backup_dir": str(backup_root),
            "managed_files": managed_records,
        }
        atomic_write_text(_instructions_state_file(root), json.dumps(state_payload, indent=2) + "\n")

        return {
            "applied": True,
            "reconciled": reconcile,
            "canonical_path": str(idir / "canonical.md"),
            "backup_dir": str(backup_root),
            "backed_up_files": backed_up,
            "written_files": written_files,
            "shared_count": len(shared_list),
            "conflicts": analysis["conflicts"],
        }


def rollback_consolidation(root: Path) -> dict[str, object]:
    """Restore pre-consolidation original instruction files from backup."""
    root = root.resolve()
    with workspace_lock(root):
        st = _load_instructions_state(root)
        bdir_str = str(st.get("initial_backup_dir") or st.get("latest_backup_dir") or "")
        if not bdir_str or not Path(bdir_str).is_dir():
            raise InstructionError("no instruction consolidation backup available to roll back")
        bdir = Path(bdir_str)
        restored: list[str] = []
        for fpath in sorted(bdir.rglob("*")):
            if not fpath.is_file():
                continue
            rel_p = fpath.relative_to(bdir).as_posix()
            dest = root / rel_p
            atomic_write_text(dest, fpath.read_text(encoding="utf-8", errors="replace"))
            restored.append(rel_p)

        idir = _instructions_dir(root)
        if idir.is_dir():
            shutil.rmtree(idir, ignore_errors=True)
        return {"rolled_back": True, "backup_dir": str(bdir), "restored_files": restored}


def inspect_harness_context(root: Path, harness_id: str, *, scope: str = "project") -> dict[str, object]:
    """Show exact active instructions, ignored foreign files, reachable skills, and token cost for *harness_id*."""
    root = root.resolve()
    h = harnesses.get(harness_id)
    all_inst = discover_instruction_files(root)
    active_inst = []
    ignored_inst = []
    for f in all_inst:
        entry = {
            "path": f.rel_path,
            "scope_kind": f.scope_kind,
            "precedence": f.precedence,
            "estimated_tokens": f.estimated_tokens,
            "managed": f.managed,
        }
        if h.name in f.harnesses:
            active_inst.append(entry)
        else:
            entry["owners"] = f.harnesses
            ignored_inst.append(entry)

    active_inst.sort(key=lambda x: int(x["precedence"]))  # type: ignore[arg-type]

    diag = diagnose(root, only=[h.name], scope=scope)
    rep = diag.reports[h.name]
    active_skills = []
    skill_index_tokens = 0
    skill_body_tokens_total = 0
    for sname in sorted(rep.reachable_skills):
        copies = diag.skill_copies.get(sname, [])
        if copies and (copies[0] / "SKILL.md").is_file():
            doc = parse_skill(copies[0] / "SKILL.md")
            idx_tok = max(1, len(f"{doc.name}: {doc.description}") // 4)
            body_tok = max(1, len(doc.body) // 4)
        else:
            idx_tok, body_tok = 15, 0
        skill_index_tokens += idx_tok
        skill_body_tokens_total += body_tok
        active_skills.append(
            {
                "name": sname,
                "index_tokens": idx_tok,
                "on_activation_body_tokens": body_tok,
                "duplicate": sname in rep.duplicate_skills,
                "drifted": sname in rep.drifted_skills,
            }
        )

    inst_tokens = sum(int(x["estimated_tokens"]) for x in active_inst)  # type: ignore[arg-type]
    always_loaded_tokens = inst_tokens + skill_index_tokens
    return {
        "harness": h.name,
        "display_name": h.label,
        "support_status": h.support_status,
        "active_instructions": active_inst,
        "ignored_instructions": ignored_inst,
        "active_skills": active_skills,
        "token_summary": {
            "instruction_files_tokens": inst_tokens,
            "skill_index_tokens": skill_index_tokens,
            "always_loaded_startup_tokens": always_loaded_tokens,
            "max_on_activation_skill_tokens": skill_body_tokens_total,
            "measurement": "estimated (4 chars/token heuristic)",
        },
    }
