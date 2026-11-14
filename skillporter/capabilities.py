"""Skill Capability Declaration & Static Capability Inference Model.

Compares:
  1. Author-declared capabilities in ``SKILL.md`` frontmatter (``capabilities:``)
  2. Statically inferred capabilities across ``SKILL.md`` and bundled scripts
  3. Harness runtime enforcement reality (advisory vs. enforced).

Never claims that a frontmatter manifest enforces sandboxing unless the target
runtime independently enforces isolation.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import parse_skill

KNOWN_CAPABILITIES: tuple[str, ...] = (
    "network",
    "shell_exec",
    "filesystem_read",
    "filesystem_write",
    "env_access",
    "script_exec",
    "subagent_fork",
    "hooks",
)

SENSITIVE_CAPABILITIES = frozenset(
    {"network", "shell_exec", "filesystem_write", "env_access", "script_exec"}
)

_SHELL_SCRIPT_NET_RE = re.compile(
    r"\b(?:curl|wget|nc|ncat|socat|ssh|scp|rsync|urlopen|urlretrieve|requests\.(?:get|post|put|delete|request)|"
    r"httpx\.(?:get|post|Client|AsyncClient)|fetch\s*\(|axios\.(?:get|post))\b"
)
_SHELL_SCRIPT_EXEC_RE = re.compile(
    r"\b(?:subprocess\.(?:run|Popen|call|check_call|check_output)|os\.(?:system|popen|exec\w*|spawn\w*)|"
    r"child_process\.(?:exec|execSync|spawn|spawnSync)|eval\s*\(|exec\s*\()\b"
)
_SHELL_SCRIPT_WRITE_RE = re.compile(
    r"(?:\b(?:write_text|write_bytes|writeFileSync|writeFile|unlink|rmtree|makedirs)\s*\(|"
    r"(?:^|[^0-9>])>>?\s*(?!/dev/null)[^\s;|&]+)"
)
_SHELL_SCRIPT_ENV_RE = re.compile(
    r"(?:\bos\.environ\b|\bos\.getenv\s*\(|\bprocess\.env\b|\$\{?[A-Z][A-Z0-9_]*_(?:KEY|TOKEN|SECRET)\}?)"
)


_CAPABILITY_ALIASES: dict[str, str] = {
    "net": "network",
    "http": "network",
    "shell": "shell_exec",
    "exec": "shell_exec",
    "fs_read": "filesystem_read",
    "file_read": "filesystem_read",
    "fs_write": "filesystem_write",
    "file_write": "filesystem_write",
    "env": "env_access",
    "scripts": "script_exec",
    "script": "script_exec",
}


def normalize_capability_name(raw: str) -> str:
    """Normalize hyphenated or aliased capability tokens to canonical identifiers."""
    clean = raw.strip().lower().replace("-", "_")
    return _CAPABILITY_ALIASES.get(clean, clean)


@dataclass
class CapabilityAssessment:
    """Comparison of declared vs. statically inferred capabilities for a skill."""

    has_declaration: bool = False
    declared: list[str] = field(default_factory=list)
    explicitly_denied: list[str] = field(default_factory=list)
    invalid_declared: list[str] = field(default_factory=list)
    inferred: list[str] = field(default_factory=list)
    undeclared: list[str] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    enforced_by_harness: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "has_declaration": self.has_declaration,
            "declared": self.declared,
            "explicitly_denied": self.explicitly_denied,
            "invalid_declared": self.invalid_declared,
            "inferred": self.inferred,
            "undeclared": self.undeclared,
            "evidence": self.evidence,
            "enforced_by_harness": self.enforced_by_harness,
            "enforcement_note": (
                "Capability declarations are statically audited by Skillporter; "
                "most agent harnesses do not enforce per-skill capability sandboxes at runtime."
            ),
        }


def _parse_declared_capabilities(
    frontmatter: dict[str, object],
) -> tuple[bool, set[str], set[str], list[str]]:
    if "capabilities" not in frontmatter:
        meta = frontmatter.get("metadata")
        if isinstance(meta, dict) and "capabilities" in meta:
            raw_m = str(meta["capabilities"]).strip()
            if not raw_m or raw_m.lower() == "none":
                return True, set(), set(), []
            dec_m: set[str] = set()
            inv_m: list[str] = []
            for x in raw_m.split(","):
                if x.strip():
                    norm = normalize_capability_name(x)
                    if norm in KNOWN_CAPABILITIES:
                        dec_m.add(norm)
                    else:
                        inv_m.append(x.strip())
            return True, dec_m, set(), inv_m
        return False, set(), set(), []

    raw = frontmatter.get("capabilities")
    declared: set[str] = set()
    denied: set[str] = set()
    invalid: list[str] = []

    def _record_tok(raw_tok: object, is_denied: bool = False) -> None:
        s = str(raw_tok).strip()
        if not s or s.lower() == "none":
            return
        norm = normalize_capability_name(s)
        if norm not in KNOWN_CAPABILITIES:
            invalid.append(s)
        elif is_denied:
            denied.add(norm)
        else:
            declared.add(norm)

    if isinstance(raw, list):
        for item in raw:
            _record_tok(item)
        return True, declared, denied, invalid
    if isinstance(raw, dict):
        for k, v in raw.items():
            sval = str(v).strip().lower()
            if sval in ("false", "0", "no", "denied", "off"):
                _record_tok(k, is_denied=True)
            elif sval in ("true", "1", "yes", "required", "on"):
                _record_tok(k, is_denied=False)
            else:
                invalid.append(f"{k}:{v}")
        return True, declared, denied, invalid
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s.lower() in ("none", "[]"):
            return True, set(), set(), []
        for part in s.split(","):
            if part.strip():
                _record_tok(part)
        return True, declared, denied, invalid
    invalid.append(str(raw))
    return True, declared, denied, invalid


def _record_ev(ev_map: dict[str, list[str]], cap: str, ref: str) -> None:
    items = ev_map.setdefault(cap, [])
    if ref not in items and len(items) < 8:
        items.append(ref)


def _infer_python_ast_caps(rel: str, text: str, ev_map: dict[str, list[str]]) -> None:
    try:
        tree = ast.parse(text, filename=rel)
    except (SyntaxError, ValueError, RecursionError):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        ln = getattr(node, "lineno", 1)
        ref = f"{rel}:{ln}"
        fname = ""
        if isinstance(node.func, ast.Name):
            fname = node.func.id
        elif isinstance(node.func, ast.Attribute):
            base = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
            fname = f"{base}.{node.func.attr}" if base else node.func.attr

        if any(t in fname for t in ("urlopen", "urlretrieve", "Request", "requests.", "httpx.", "socket")):
            _record_ev(ev_map, "network", ref)
        if any(t in fname for t in ("subprocess.", "os.system", "os.popen", "os.exec", "pty.spawn")):
            _record_ev(ev_map, "shell_exec", ref)
        if fname in ("os.getenv", "getenv") or fname.startswith("os.environ"):
            _record_ev(ev_map, "env_access", ref)
        if fname.endswith(("read_text", "read_bytes")):
            _record_ev(ev_map, "filesystem_read", ref)
        if fname.endswith(("write_text", "write_bytes", "unlink", "rmtree", "mkdir", "makedirs")):
            _record_ev(ev_map, "filesystem_write", ref)
        if fname == "open":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                mode = node.args[1].value
                if any(m in mode for m in ("w", "a", "x", "+")):
                    _record_ev(ev_map, "filesystem_write", ref)
                else:
                    _record_ev(ev_map, "filesystem_read", ref)
            else:
                _record_ev(ev_map, "filesystem_read", ref)


def analyze_capabilities(skill_dir: Path) -> CapabilityAssessment:
    """Compare declared vs. statically inferred capabilities for *skill_dir*."""
    skill_dir = Path(skill_dir).resolve()
    if not skill_dir.is_dir():
        return CapabilityAssessment()

    skill_md = skill_dir / "SKILL.md"
    has_decl = False
    declared_set: set[str] = set()
    denied_set: set[str] = set()
    invalid_list: list[str] = []
    ev_map: dict[str, list[str]] = {}

    if skill_md.is_file():
        doc = parse_skill(skill_md)
        has_decl, declared_set, denied_set, invalid_list = _parse_declared_capabilities(doc.frontmatter)
        if doc.frontmatter.get("context") == "fork":
            _record_ev(ev_map, "subagent_fork", "SKILL.md:1")
        if doc.frontmatter.get("hooks"):
            _record_ev(ev_map, "hooks", "SKILL.md:1")

    for dirpath, dirnames, filenames in os.walk(skill_dir, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames if d not in {".git", "__pycache__", ".venv", "node_modules", ".skillporter"}
        )
        cdir = Path(dirpath)
        for fname in sorted(filenames):
            fpath = cdir / fname
            if fpath.is_symlink() or not fpath.is_file():
                continue
            rel = fpath.relative_to(skill_dir).as_posix()
            suf = fpath.suffix.lower()
            script_exts = {".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".mjs", ".ps1"}
            is_script = rel.startswith("scripts/") or suf in script_exts
            if is_script:
                _record_ev(ev_map, "script_exec", rel)

            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if suf == ".py":
                _infer_python_ast_caps(rel, text, ev_map)

            for idx, line in enumerate(text.splitlines(), start=1):
                s = line.strip()
                if not s or s.startswith("# "):
                    continue
                ref = f"{rel}:{idx}"
                if is_script:
                    if _SHELL_SCRIPT_NET_RE.search(s):
                        _record_ev(ev_map, "network", ref)
                    is_shell_line = suf in {".sh", ".bash"} and idx > 1 and not s.startswith("#")
                    if _SHELL_SCRIPT_EXEC_RE.search(s) or is_shell_line:
                        _record_ev(ev_map, "shell_exec", ref)
                    if _SHELL_SCRIPT_WRITE_RE.search(s):
                        _record_ev(ev_map, "filesystem_write", ref)
                    if _SHELL_SCRIPT_ENV_RE.search(s):
                        _record_ev(ev_map, "env_access", ref)
                else:
                    # In Markdown, only flag explicit command invocations (curl/wget)
                    if re.search(r"\b(?:curl|wget)\s+(-[A-Za-z]+\s+)*https?://", s):
                        _record_ev(ev_map, "network", ref)

    inferred = sorted(ev_map.keys())
    undeclared: list[str] = []
    for cap in inferred:
        if cap in denied_set or (has_decl and cap in SENSITIVE_CAPABILITIES and cap not in declared_set):
            undeclared.append(cap)

    return CapabilityAssessment(
        has_declaration=has_decl,
        declared=sorted(declared_set),
        explicitly_denied=sorted(denied_set),
        invalid_declared=invalid_list,
        inferred=inferred,
        undeclared=sorted(set(undeclared)),
        evidence=ev_map,
        enforced_by_harness=False,
    )
