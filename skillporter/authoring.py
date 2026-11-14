"""Skill Authoring, Deep Linting, Native Format Preview, and Activation Testing Engine.

Implements zero-dependency stdlib support for:
  * ``skillporter new``     — Scaffold spec-compliant skills with optional scripts, references & tests.
  * ``skillporter lint``    — Deep validation of metadata, local file references, scripts, and limits.
  * ``skillporter preview`` — Exact native & adapted output preview + capability-loss analysis per harness.
  * ``skillporter test``    — Deterministic ``skill.test.yaml`` activation & structural test runner,
                              plus optional user-authorized model evaluation.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import harnesses
from .atomic import atomic_write_text
from .capabilities import analyze_capabilities
from .diagnose import diagnose, select_harness_install_raw_path
from .formats import ADAPTED_FORMATS, assess_adaptation_limitations, render_adapted_skill
from .frontmatter import MAX_NAME, NAME_RE, Issue, SkillDoc, discover, parse_skill, validate
from .security import scan_skill

_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
_INLINE_PATH_RE = re.compile(r"(?:^|[\s`\"'(])((?:references|scripts|assets|templates)/[A-Za-z0-9_./-]+)")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "ask",
        "asks",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "file",
        "files",
        "for",
        "from",
        "help",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "make",
        "me",
        "my",
        "need",
        "of",
        "on",
        "or",
        "our",
        "please",
        "project",
        "run",
        "should",
        "some",
        "task",
        "that",
        "the",
        "their",
        "them",
        "these",
        "this",
        "to",
        "use",
        "used",
        "using",
        "user",
        "want",
        "when",
        "with",
        "work",
        "write",
        "you",
        "your",
    }
)


class AuthoringError(ValueError):
    """Raised when skill scaffolding, preview resolution, or test configuration fails."""


def _stem_word(word: str) -> str:
    w = word.lower().strip()
    if len(w) <= 3:
        return w
    for suffix in ("ing", "tion", "ions", "or", "er", "es", "s", "ed"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


def _extract_domain_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    out: set[str] = set()
    for w in words:
        if len(w) < 2 or w in _STOPWORDS:
            continue
        out.add(w)
        out.add(_stem_word(w))
    return out


def create_skill_scaffold(
    base_dir: Path,
    name: str,
    *,
    description: str = "",
    author: str = "developer",
    with_scripts: bool = False,
    with_references: bool = False,
    with_tests: bool = False,
    force: bool = False,
) -> dict[str, object]:
    """Create a spec-compliant skill directory with structured templates."""
    clean_name = name.strip()
    if not clean_name or len(clean_name) > MAX_NAME or not NAME_RE.match(clean_name):
        raise AuthoringError(
            f"invalid skill name {name!r}: must be 1-{MAX_NAME} lowercase "
            "alphanumeric chars separated by single hyphens"
        )

    skill_dir = (base_dir.expanduser().resolve() / clean_name).resolve()
    if skill_dir.exists() and not force:
        raise AuthoringError(f"destination {skill_dir} already exists (pass --force to overwrite)")

    skill_dir.mkdir(parents=True, exist_ok=True)
    words = [w for w in clean_name.split("-") if w]
    human_title = " ".join(w.capitalize() for w in words)
    topic_phrase = " ".join(words)

    eff_desc = description.strip()
    if not eff_desc:
        eff_desc = (
            f"Execute {topic_phrase} workflows consistently and safely across coding agents. "
            f"Use when the user asks about {topic_phrase} tasks or workflows."
        )
    elif not any(k in eff_desc.lower() for k in ("use when", "use this", "when the user", "when you", "trigger")):
        eff_desc = eff_desc.rstrip(".") + f". Use when working with {topic_phrase}."

    created_files: list[str] = []
    body_sections = [
        f"# {human_title}",
        "",
        "## When to Use",
        "",
        f"- Activate this skill for {topic_phrase} workflows.",
        "- Prefer deterministic checks and verify outputs before reporting completion.",
        "",
        "## Workflow",
        "",
        "1. Inspect the relevant workspace files and configuration first.",
        "2. Apply minimal, targeted changes following repository conventions.",
    ]

    if with_scripts:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path = scripts_dir / "helper.py"
        atomic_write_text(
            script_path,
            '"""Deterministic helper script for ' + clean_name + '."""\n\n'
            "from __future__ import annotations\n\n"
            "import sys\n\n\n"
            "def main() -> int:\n"
            f'    print("{clean_name}: helper check ok")\n'
            "    return 0\n\n\n"
            'if __name__ == "__main__":\n'
            "    raise SystemExit(main())\n",
        )
        created_files.append("scripts/helper.py")
        body_sections.append("3. Run `python3 scripts/helper.py` to verify deterministic preconditions.")
    else:
        body_sections.append("3. Run the project test suite to confirm all invariants hold.")

    if with_references:
        refs_dir = skill_dir / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        ref_path = refs_dir / "guide.md"
        atomic_write_text(
            ref_path,
            f"# {human_title} Reference Guide\n\nDetailed conventions, edge cases, and examples for `{clean_name}`.\n",
        )
        created_files.append("references/guide.md")
        body_sections.extend(
            [
                "",
                "## References",
                "",
                "- Read [Reference Guide](references/guide.md) when handling edge cases.",
            ]
        )

    body_sections.extend(
        [
            "",
            "## Constraints",
            "",
            "- Never modify files outside the requested project scope.",
            "- Report blockers plainly with concrete evidence.",
        ]
    )

    safe_desc = eff_desc.replace('"', "'")
    skill_md_text = (
        "---\n"
        f"name: {clean_name}\n"
        f'description: "{safe_desc}"\n'
        "license: MIT\n"
        "metadata:\n"
        f'  author: "{author}"\n'
        '  version: "0.1.0"\n'
        "---\n\n"
        + "\n".join(body_sections)
        + "\n"
    )
    atomic_write_text(skill_dir / "SKILL.md", skill_md_text)
    created_files.insert(0, "SKILL.md")

    if with_tests:
        domain_terms = [
            w for w in re.findall(r"[a-zA-Z0-9]+", f"{clean_name} {eff_desc}") if w.lower() not in _STOPWORDS
        ]
        sample_focus = " ".join(domain_terms[:3]) if domain_terms else topic_phrase
        test_yaml = (
            "# Activation and structural test suite for `skillporter test`\n"
            "should_trigger:\n"
            f"  - run {topic_phrase} workflow on this project\n"
            f"  - help me with {sample_focus}\n"
            "should_not:\n"
            "  - center a div using CSS grid layout\n"
            "  - configure BGP autonomous system peering\n"
            "max_tokens: 4500\n"
            "max_risk_score: 20\n"
            "required_files:\n"
            "  - SKILL.md\n"
        )
        atomic_write_text(skill_dir / "skill.test.yaml", test_yaml)
        created_files.append("skill.test.yaml")

    return {
        "name": clean_name,
        "skill_dir": str(skill_dir),
        "created_files": created_files,
    }


@dataclass
class SkillLintReport:
    """Comprehensive lint findings for a single skill directory."""

    name: str
    path: Path
    issues: list[Issue] = field(default_factory=list)
    risk_score: int = 0
    estimated_tokens: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")

    def passed(self, *, strict: bool = False) -> bool:
        if self.error_count > 0:
            return False
        return not (strict and self.warning_count > 0)

    def to_dict(self, *, strict: bool = False) -> dict[str, object]:
        return {
            "name": self.name,
            "path": str(self.path),
            "passed": self.passed(strict=strict),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "risk_score": self.risk_score,
            "estimated_tokens": self.estimated_tokens,
            "issues": [i.to_dict() for i in self.issues],
        }


def lint_skill_dir(skill_dir: Path, *, target_harnesses: list[str] | None = None) -> SkillLintReport:
    """Validate frontmatter, references, scripts, harness limits, and security for *skill_dir*."""
    skill_dir = skill_dir.resolve()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return SkillLintReport(
            name=skill_dir.name,
            path=skill_dir,
            issues=[Issue("error", "missing-skill-md", f"no SKILL.md found in {skill_dir}", category="spec")],
        )

    doc = parse_skill(skill_md)
    issues = list(validate(doc))
    raw_text = skill_md.read_text(encoding="utf-8", errors="replace")
    est_tokens = max(1, len(doc.body) // 4)

    if re.search(r"\b(?:TODO|TBD|FIXME|lorem ipsum)\b", doc.description, re.IGNORECASE):
        issues.append(
            Issue(
                "warning",
                "placeholder-description",
                "'description' contains placeholder markers (TODO/TBD/FIXME)",
                category="recommendation",
            )
        )

    # Extract local relative references from Markdown links and inline paths
    referenced_rel_paths: set[str] = set()
    for m in _MD_LINK_RE.finditer(doc.body):
        raw_ref = m.group(1).split("#", 1)[0].split("?", 1)[0].strip()
        if not raw_ref or raw_ref.startswith(("http://", "https://", "mailto:", "/")):
            continue
        referenced_rel_paths.add(raw_ref)

    for m in _INLINE_PATH_RE.finditer(doc.body):
        raw_inline = m.group(1).rstrip(".,;:)`'\"")
        if raw_inline and "*" not in raw_inline and "<" not in raw_inline:
            referenced_rel_paths.add(raw_inline)

    for rel_ref in sorted(referenced_rel_paths):
        norm = rel_ref.replace("\\", "/")
        parts = [p for p in norm.split("/") if p and p != "."]
        if ".." in parts:
            issues.append(
                Issue(
                    "error",
                    "unsafe-reference-escape",
                    f"reference {rel_ref!r} traverses outside the skill root via '..'",
                    category="spec",
                )
            )
            continue
        cand = (skill_dir / norm).resolve()
        if not cand.exists():
            issues.append(
                Issue(
                    "error",
                    "missing-reference-file",
                    f"referenced file {rel_ref!r} does not exist inside {skill_dir.name}/",
                    category="spec",
                )
            )

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        for spath in sorted(scripts_dir.rglob("*")):
            if not spath.is_file() or spath.name.startswith("."):
                continue
            rel_s = spath.relative_to(skill_dir).as_posix()
            if rel_s not in raw_text and spath.name not in raw_text:
                issues.append(
                    Issue(
                        "warning",
                        "unreferenced-script",
                        f"bundled script {rel_s!r} is never mentioned in SKILL.md",
                        category="recommendation",
                    )
                )

    srep = scan_skill(skill_dir, offline=True)
    for sf in srep.findings:
        if sf.severity in ("CRITICAL", "HIGH"):
            issues.append(
                Issue(
                    "error",
                    sf.code,
                    f"{sf.file}:{sf.line}: {sf.message}" if sf.line else f"{sf.file}: {sf.message}",
                    category="spec",
                )
            )
        elif sf.severity == "MEDIUM":
            issues.append(
                Issue(
                    "warning",
                    sf.code,
                    f"{sf.file}:{sf.line}: {sf.message}" if sf.line else f"{sf.file}: {sf.message}",
                    category="recommendation",
                )
            )

    cap_rep = analyze_capabilities(skill_dir)
    if cap_rep.invalid_declared:
        issues.append(
            Issue(
                "warning",
                "invalid-capability",
                f"unrecognized capability identifier(s) in SKILL.md: {', '.join(cap_rep.invalid_declared)}",
                category="spec",
            )
        )
    if cap_rep.undeclared:
        issues.append(
            Issue(
                "warning",
                "capability-mismatch",
                f"inferred capability {', '.join(cap_rep.undeclared)} is not declared in SKILL.md `capabilities:`",
                category="spec",
            )
        )

    if target_harnesses:
        for hid in target_harnesses:
            h = harnesses.get(hid)
            if est_tokens > h.capabilities.max_body_tokens:
                issues.append(
                    Issue(
                        "warning",
                        "harness-token-budget-exceeded",
                        (
                            f"body (~{est_tokens} tokens) exceeds {h.name} "
                            f"recommended limit ({h.capabilities.max_body_tokens})"
                        ),
                        category="harness-compatibility",
                    )
                )

    return SkillLintReport(
        name=doc.name or skill_dir.name,
        path=skill_dir,
        issues=issues,
        risk_score=srep.risk_score,
        estimated_tokens=est_tokens,
    )


def resolve_skill_dir_for_inspection(target: str, root: Path, *, scope: str = "project") -> Path:
    """Locate a skill directory by path or by installed/discovered skill name."""
    raw = target.strip()
    cand = Path(raw).expanduser()
    if not cand.is_absolute():
        cand_ws = (root / cand).resolve()
        cand_cwd = (Path.cwd() / cand).resolve()
        cand = cand_ws if cand_ws.exists() else cand_cwd
    else:
        cand = cand.resolve()

    if cand.is_file() and cand.name == "SKILL.md":
        return cand.parent
    if (cand / "SKILL.md").is_file():
        return cand

    diag = diagnose(root, scope=scope)
    if raw in diag.skill_copies and diag.skill_copies[raw]:
        return diag.skill_copies[raw][0]
    for smd in discover(root):
        doc = parse_skill(smd)
        if smd.parent.name == raw or doc.name == raw:
            return smd.parent.resolve()

    raise AuthoringError(
        f"cannot locate skill {target!r} as a directory or installed skill under {root} (run `skillporter list`)"
    )


def preview_skill_for_harness(
    skill_dir: Path,
    harness_id: str,
    *,
    scope: str = "project",
    adapt_format_override: str | None = None,
) -> dict[str, object]:
    """Generate an exact delivery preview and capability-loss report for *harness_id*."""
    skill_dir = skill_dir.resolve()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise AuthoringError(f"{skill_dir} does not contain SKILL.md")

    h = harnesses.get(harness_id)
    doc = parse_skill(skill_md)
    raw_content = skill_md.read_text(encoding="utf-8", errors="replace")
    sname = doc.name or skill_dir.name
    primary_raw = select_harness_install_raw_path(h, scope)
    native_dest = f"{primary_raw}/{sname}/SKILL.md" if primary_raw else "(unsupported in this scope)"
    body_tokens = max(1, len(doc.body) // 4)

    info_lost: list[str] = []
    if not primary_raw:
        info_lost.append(f"{h.name} has no {scope}-scope installation directory")
    if doc.frontmatter.get("context") == "fork" and not h.capabilities.context_fork:
        info_lost.append(
            f"{h.name} does not support 'context: fork'; skill instructions load inline in main agent context"
        )
    if doc.frontmatter.get("allowed-tools") and not h.capabilities.allowed_tools:
        info_lost.append(f"{h.name} ignores 'allowed-tools' pre-approval metadata")
    if doc.frontmatter.get("hooks") and not h.capabilities.hooks:
        info_lost.append(f"{h.name} ignores 'hooks' lifecycle metadata")
    if body_tokens > h.capabilities.max_body_tokens:
        info_lost.append(
            f"SKILL.md body (~{body_tokens} tokens) exceeds {h.name} limit ({h.capabilities.max_body_tokens} tokens)"
        )

    eff_adapt_fmt = adapt_format_override or h.capabilities.adapted_format
    adapted_preview: dict[str, object] | None = None
    if eff_adapt_fmt and eff_adapt_fmt in ADAPTED_FORMATS:
        rel_adapt, rendered_adapt = render_adapted_skill(doc, eff_adapt_fmt)
        adapt_lims = assess_adaptation_limitations(doc, skill_dir, eff_adapt_fmt)
        if h.support_status == "ADAPTED":
            info_lost.append(
                f"{h.name} is an ADAPTED target: core CLI requires {rel_adapt} "
                "or explicit read flags rather than auto-discovering SKILL.md"
            )
            for alim in adapt_lims:
                if alim not in info_lost:
                    info_lost.append(alim)
        adapted_preview = {
            "format": eff_adapt_fmt,
            "path": rel_adapt,
            "content": rendered_adapt,
            "limitations": adapt_lims,
        }

    return {
        "skill": sname,
        "source_dir": str(skill_dir),
        "harness": h.name,
        "display_name": h.label,
        "scope": scope,
        "support_status": h.support_status,
        "verification_level": h.verification_level,
        "native_target_path": native_dest,
        "native_content": raw_content,
        "estimated_body_tokens": body_tokens,
        "adapted_preview": adapted_preview,
        "information_lost": info_lost,
        "limitations": list(h.limitations),
    }


def _parse_skill_test_yaml(text: str) -> dict[str, object]:
    """Parse ``skill.test.yaml`` without external YAML dependencies."""
    stripped = text.strip()
    if stripped.startswith("{"):
        raw = json.loads(stripped)
        return raw if isinstance(raw, dict) else {}

    data: dict[str, object] = {
        "should_trigger": [],
        "should_not": [],
        "required_files": [],
    }
    current_list_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        sline = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and ":" in sline:
            k, _, v = sline.partition(":")
            key = k.strip()
            val = v.strip().strip("\"'")
            if key in ("should_trigger", "should_not", "required_files"):
                if val.startswith("[") and val.endswith("]"):
                    items = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
                    data[key] = items
                    current_list_key = None
                else:
                    data.setdefault(key, [])
                    current_list_key = key
            elif key in ("max_tokens", "max_risk_score") and val.isdigit():
                data[key] = int(val)
                current_list_key = None
            else:
                data[key] = val
                current_list_key = None
        elif current_list_key and sline.startswith("- "):
            item_val = sline[2:].strip().strip("\"'")
            if item_val:
                target_list = data.setdefault(current_list_key, [])
                if isinstance(target_list, list):
                    target_list.append(item_val)
    return data


def _deterministic_prompt_triggers(doc: SkillDoc, prompt: str) -> tuple[bool, list[str], list[str]]:
    """Evaluate deterministically whether *prompt* aligns with *doc*'s routing metadata."""
    name_parts = [p for p in re.findall(r"[a-zA-Z0-9]+", (doc.name or doc.directory_name).lower()) if len(p) >= 2]
    filtered_parts = [p for p in name_parts if p not in _STOPWORDS]
    name_stems = set(filtered_parts) | {_stem_word(p) for p in filtered_parts}

    triggers_raw = doc.frontmatter.get("triggers", "")
    trig_str = " ".join(triggers_raw) if isinstance(triggers_raw, list) else str(triggers_raw)
    headings = " ".join(
        line.lstrip("#").strip() for line in doc.body.splitlines() if line.strip().startswith("#")
    )
    skill_vocab = _extract_domain_tokens(f"{doc.name} {doc.description} {trig_str} {headings}")
    prompt_tokens = _extract_domain_tokens(prompt)

    matched = sorted(prompt_tokens & skill_vocab)
    missing = sorted(prompt_tokens - skill_vocab)
    matched_primary = prompt_tokens & name_stems

    if matched_primary:
        return True, matched, missing
    if len(matched) >= 2:
        return True, matched, missing
    if prompt_tokens and (len(matched) / max(1, len(prompt_tokens))) >= 0.5:
        return True, matched, missing
    return False, matched, missing


def _model_prompt_triggers(model_spec: str, doc: SkillDoc, prompt: str) -> bool:
    """Invoke a user-configured LLM endpoint to evaluate whether *prompt* activates *doc*."""
    provider, _, model_name = model_spec.partition(":")
    prov = provider.strip().lower()
    mname = model_name.strip() or model_spec.strip()

    system_msg = (
        "You are evaluating AI agent skill activation routing. "
        "Reply with exact JSON: {\"activate\": true} or {\"activate\": false}."
    )
    user_msg = (
        f"Skill name: {doc.name}\n"
        f"Skill description: {doc.description}\n"
        f"User prompt: {prompt}\n"
        "Should this skill activate for this prompt?"
    )

    if prov in ("openai", "") or "gpt" in mname:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise AuthoringError("OPENAI_API_KEY is required in environment for --model openai:<model>")
        base_url = os.environ.get("SKILLPORTER_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        payload = json.dumps(
            {
                "model": mname,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310  # nosec B310
                body = json.loads(resp.read(1 << 20).decode("utf-8"))
            txt = str(body["choices"][0]["message"]["content"]).lower()
            return '"activate": true' in txt or '"activate":true' in txt or txt.strip() == "true"
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AuthoringError(f"model evaluation request failed: {exc}") from exc

    if prov == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise AuthoringError("ANTHROPIC_API_KEY is required in environment for --model anthropic:<model>")
        payload = json.dumps(
            {
                "model": mname,
                "max_tokens": 64,
                "system": system_msg,
                "messages": [{"role": "user", "content": user_msg}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310  # nosec B310
                body = json.loads(resp.read(1 << 20).decode("utf-8"))
            txt = str(body["content"][0]["text"]).lower()
            return '"activate": true' in txt or '"activate":true' in txt or txt.strip() == "true"
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AuthoringError(f"Anthropic evaluation request failed: {exc}") from exc

    raise AuthoringError(
        f"unsupported --model provider {prov!r}; use 'openai:<model>' or 'anthropic:<model>'"
    )


def run_skill_tests(
    target_path: Path,
    *,
    model: str = "",
    authorize_remote: bool = False,
) -> dict[str, object]:
    """Run structural and activation tests defined in ``skill.test.yaml``."""
    target_path = target_path.expanduser().resolve()
    if target_path.is_file() and target_path.name == "skill.test.yaml":
        test_files = [target_path]
    elif (target_path / "skill.test.yaml").is_file():
        test_files = [target_path / "skill.test.yaml"]
    elif target_path.is_dir():
        test_files = sorted(target_path.rglob("skill.test.yaml"))
    else:
        raise AuthoringError(f"path {target_path} does not exist")

    if model and not authorize_remote:
        raise AuthoringError(
            "model-based evaluation transmits skill descriptions and test prompts to an external API; "
            "pass --yes-send to authorize external API usage"
        )

    eval_mode = "model_assisted" if model else "deterministic_lexical"

    # If no skill.test.yaml exists yet, run structural validation on discovered skills
    if not test_files:
        skill_mds = [target_path / "SKILL.md"] if (target_path / "SKILL.md").is_file() else discover(target_path)
        if not skill_mds:
            raise AuthoringError(f"no skill.test.yaml or SKILL.md found under {target_path}")
        suites = []
        all_passed = True
        for smd in skill_mds:
            lint_rep = lint_skill_dir(smd.parent)
            ok = lint_rep.error_count == 0
            if not ok:
                all_passed = False
            suites.append(
                {
                    "skill": lint_rep.name,
                    "skill_dir": str(smd.parent),
                    "test_file": None,
                    "passed": ok,
                    "structural_errors": [str(i) for i in lint_rep.issues if i.level == "error"],
                    "expected_activations": [],
                    "missed_activations": [],
                    "false_positives": [],
                    "true_negatives": [],
                }
            )
        return {
            "passed": all_passed,
            "evaluation_mode": "structural_only",
            "disclaimer": (
                "No skill.test.yaml found; ran structural validation only. "
                "Add skill.test.yaml (or `skillporter new <name> --with-tests`) to test prompt triggers."
            ),
            "suites": suites,
        }

    suites = []
    overall_passed = True
    for tfile in test_files:
        sdir = tfile.parent
        skill_md = sdir / "SKILL.md"
        if not skill_md.is_file():
            overall_passed = False
            suites.append(
                {
                    "skill": sdir.name,
                    "skill_dir": str(sdir),
                    "test_file": str(tfile),
                    "passed": False,
                    "structural_errors": [f"missing SKILL.md in {sdir}"],
                    "expected_activations": [],
                    "missed_activations": [],
                    "false_positives": [],
                    "true_negatives": [],
                }
            )
            continue

        spec = _parse_skill_test_yaml(tfile.read_text(encoding="utf-8"))
        doc = parse_skill(skill_md)
        lint_rep = lint_skill_dir(sdir)
        structural_errors = [str(i) for i in lint_rep.issues if i.level == "error"]

        max_tok = spec.get("max_tokens")
        if isinstance(max_tok, int) and lint_rep.estimated_tokens > max_tok:
            structural_errors.append(
                f"estimated body tokens ({lint_rep.estimated_tokens}) exceed max_tokens ({max_tok})"
            )
        max_risk = spec.get("max_risk_score")
        if isinstance(max_risk, int) and lint_rep.risk_score > max_risk:
            structural_errors.append(f"security risk_score ({lint_rep.risk_score}) exceeds max_risk_score ({max_risk})")

        req_files = spec.get("required_files", [])
        if isinstance(req_files, list):
            for rf in req_files:
                if not (sdir / str(rf)).exists():
                    structural_errors.append(f"required file {rf!r} missing in {sdir.name}")

        raw_st = spec.get("should_trigger")
        raw_sn = spec.get("should_not")
        should_trigger = [str(x) for x in raw_st] if isinstance(raw_st, list) else []
        should_not = [str(x) for x in raw_sn] if isinstance(raw_sn, list) else []

        expected_hits: list[str] = []
        missed_hits: list[dict[str, object]] = []
        false_positives: list[dict[str, object]] = []
        true_negatives: list[str] = []

        for prompt in should_trigger:
            if model:
                activated = _model_prompt_triggers(model, doc, prompt)
                matched, missing = [], []
            else:
                activated, matched, missing = _deterministic_prompt_triggers(doc, prompt)
            if activated:
                expected_hits.append(prompt)
            else:
                missed_hits.append({"prompt": prompt, "matched_terms": matched, "unmatched_terms": missing})

        for prompt in should_not:
            if model:
                activated = _model_prompt_triggers(model, doc, prompt)
                matched = []
            else:
                activated, matched, _ = _deterministic_prompt_triggers(doc, prompt)
            if activated:
                false_positives.append({"prompt": prompt, "overlapping_terms": matched})
            else:
                true_negatives.append(prompt)

        suite_ok = not structural_errors and not missed_hits and not false_positives
        if not suite_ok:
            overall_passed = False

        suites.append(
            {
                "skill": doc.name or sdir.name,
                "skill_dir": str(sdir),
                "test_file": str(tfile),
                "passed": suite_ok,
                "structural_errors": structural_errors,
                "expected_activations": expected_hits,
                "missed_activations": missed_hits,
                "false_positives": false_positives,
                "true_negatives": true_negatives,
            }
        )

    return {
        "passed": overall_passed,
        "evaluation_mode": eval_mode,
        "disclaimer": (
            "Sample activation tests evaluate description trigger coverage and structural invariants; "
            "passing sample tests does not guarantee activation in every live LLM conversation."
        ),
        "suites": suites,
    }
