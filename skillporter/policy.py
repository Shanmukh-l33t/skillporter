"""Project Security Policy Engine (`skillporter.policy.yaml`).

Enforces consistent project-level governance across `add`, `install`, `sync`,
`update`, `import`, `ci-report`, and `skillporter policy check`:
  * `approved_sources`: glob allowlist for skill sources
  * `restricted_sources`: glob denylist for skill sources
  * `max_risk_score`: 0-100 static risk score ceiling
  * `block_severity`: minimum finding severity to block (CRITICAL, HIGH, MEDIUM, LOW)
  * `banned_capabilities`: capabilities forbidden in workspace skills (e.g. network, shell_exec)
  * `require_declared_capabilities`: fail on undeclared inferred capabilities
  * `allowed_harnesses`: restrict which harnesses may receive skills in this repository
  * `require_pinned_refs`: forbid unpinned mutable remote refs.
"""

from __future__ import annotations

import fnmatch
import json
import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from . import harnesses
from .atomic import atomic_write_text
from .capabilities import analyze_capabilities, normalize_capability_name
from .security import SEVERITY_ORDER, SecurityReport, scan_skill

POLICY_FILENAME = "skillporter.policy.yaml"


@dataclass
class PolicyConfig:
    """Parsed `skillporter.policy.yaml` rules."""

    approved_sources: list[str] = field(default_factory=list)
    restricted_sources: list[str] = field(default_factory=list)
    max_risk_score: int | None = None
    block_severity: str = "HIGH"
    banned_capabilities: list[str] = field(default_factory=list)
    require_declared_capabilities: bool = False
    allowed_harnesses: list[str] = field(default_factory=list)
    require_pinned_refs: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "approved_sources": list(self.approved_sources),
            "restricted_sources": list(self.restricted_sources),
            "max_risk_score": self.max_risk_score,
            "block_severity": self.block_severity,
            "banned_capabilities": list(self.banned_capabilities),
            "require_declared_capabilities": self.require_declared_capabilities,
            "allowed_harnesses": list(self.allowed_harnesses),
            "require_pinned_refs": self.require_pinned_refs,
        }

    def to_yaml(self) -> str:
        lines = ["# Skillporter Project Security Policy"]
        lines.append(f"block_severity: {self.block_severity}")
        if self.max_risk_score is not None:
            lines.append(f"max_risk_score: {self.max_risk_score}")
        lines.append(f"require_declared_capabilities: {'true' if self.require_declared_capabilities else 'false'}")
        lines.append(f"require_pinned_refs: {'true' if self.require_pinned_refs else 'false'}")

        def _emit_list(key: str, items: list[str]) -> None:
            if not items:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in items:
                    lines.append(f"  - {item}")

        _emit_list("approved_sources", self.approved_sources)
        _emit_list("restricted_sources", self.restricted_sources)
        _emit_list("banned_capabilities", self.banned_capabilities)
        _emit_list("allowed_harnesses", self.allowed_harnesses)
        return "\n".join(lines) + "\n"


def parse_policy(text: str) -> PolicyConfig:
    """Parse `skillporter.policy.yaml` without external YAML dependencies."""
    stripped = text.strip()
    if stripped.startswith("{"):
        raw = json.loads(stripped)
        mr = raw.get("max_risk_score")
        return PolicyConfig(
            approved_sources=[str(x) for x in raw.get("approved_sources", [])],
            restricted_sources=[str(x) for x in raw.get("restricted_sources", [])],
            max_risk_score=int(mr) if isinstance(mr, (int, float)) else None,
            block_severity=str(raw.get("block_severity", "HIGH")).upper(),
            banned_capabilities=[str(x).lower() for x in raw.get("banned_capabilities", [])],
            require_declared_capabilities=bool(raw.get("require_declared_capabilities", False)),
            allowed_harnesses=[str(x) for x in raw.get("allowed_harnesses", [])],
            require_pinned_refs=bool(raw.get("require_pinned_refs", False)),
        )

    cfg = PolicyConfig()
    active_list_name: str | None = None
    list_fields = {
        "approved_sources": cfg.approved_sources,
        "restricted_sources": cfg.restricted_sources,
        "banned_capabilities": cfg.banned_capabilities,
        "allowed_harnesses": cfg.allowed_harnesses,
    }

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
            active_list_name = None
            if key in list_fields:
                target = list_fields[key]
                if val.startswith("[") and val.endswith("]"):
                    inner = val[1:-1].strip()
                    if inner:
                        for item in inner.split(","):
                            clean = item.strip().strip("\"'")
                            if clean:
                                target.append(clean.lower() if key == "banned_capabilities" else clean)
                elif val == "":
                    active_list_name = key
                elif val != "[]":
                    target.append(val.lower() if key == "banned_capabilities" else val)
            elif key == "max_risk_score" and val.isdigit():
                cfg.max_risk_score = int(val)
            elif key == "block_severity" and val:
                cfg.block_severity = val.upper()
            elif key == "require_declared_capabilities":
                cfg.require_declared_capabilities = val.lower() in ("true", "1", "yes")
            elif key == "require_pinned_refs":
                cfg.require_pinned_refs = val.lower() in ("true", "1", "yes")
        elif active_list_name and sline.startswith("- "):
            item_val = sline[2:].strip().strip("\"'")
            if item_val:
                target = list_fields[active_list_name]
                target.append(item_val.lower() if active_list_name == "banned_capabilities" else item_val)

    return cfg


def load_policy(root: Path) -> PolicyConfig | None:
    p = Path(root).resolve() / POLICY_FILENAME
    if not p.is_file():
        return None
    return parse_policy(p.read_text(encoding="utf-8"))


def save_policy(root: Path, policy: PolicyConfig) -> Path:
    p = Path(root).resolve() / POLICY_FILENAME
    atomic_write_text(p, policy.to_yaml())
    return p


def _normalize_source_for_matching(raw_cand: str) -> str:
    """Normalize local relative/traversal paths and GitHub URLs before glob matching."""
    s = raw_cand.strip().replace("\\", "/")
    if not s:
        return ""
    if s.startswith(("https://", "http://", "git@", "github:", "registry:")):
        # Reject '..' path traversal segments inside URLs/shorthands
        parts = [p for p in s.split("/") if p]
        if ".." in parts:
            return ""
        return s.rstrip("/")
    try:
        p = Path(raw_cand).expanduser()
        if p.exists():
            return p.resolve().as_posix()
    except OSError:
        pass
    parts_raw = [p for p in s.split("/") if p and p != "."]
    if ".." in parts_raw:
        normed = posixpath.normpath(s)
        if ".." in normed.split("/"):
            return ""
        return normed
    return posixpath.normpath(s)


def _source_matches_any(source_candidates: list[str], patterns: list[str], *, is_allowlist: bool = False) -> bool:
    norm_cands: list[str] = []
    for raw_c in source_candidates:
        nc = _normalize_source_for_matching(raw_c)
        if nc and nc not in norm_cands:
            norm_cands.append(nc)
        # Also allow `owner/repo` pattern matching when canonical is `https://github.com/owner/repo.git`
        if nc.startswith("https://github.com/"):
            tail = nc[len("https://github.com/") :].removesuffix(".git").split("#", 1)[0]
            if tail and ".." not in tail.split("/") and tail not in norm_cands:
                norm_cands.append(tail)

    if not norm_cands:
        return False

    # For allowlists, if a canonical resolved local path is present (last candidate),
    # never let an uncanonicalized alias bypass it if all local paths disagree.
    check_cands = norm_cands
    if is_allowlist:
        abs_locals = [c for c in norm_cands if c.startswith("/") or (len(c) > 1 and c[1] == ":")]
        has_remote = any(c.startswith(("https://", "http://", "git@", "github:", "registry:")) for c in norm_cands)
        if abs_locals and not has_remote:
            check_cands = abs_locals

    for pat in patterns:
        norm_pat = (
            _normalize_source_for_matching(pat)
            if pat.startswith(("/", ".", "~"))
            else pat.strip().replace("\\", "/")
        )
        if pat.strip().endswith("/*") and not norm_pat.endswith("/*"):
            norm_pat = norm_pat.rstrip("/") + "/*"
        for cand in check_cands:
            if fnmatch.fnmatch(cand, norm_pat) or cand == norm_pat.rstrip("/*"):
                return True
            if norm_pat.endswith("/*") and cand.startswith(norm_pat[:-1]):
                return True
    return False


def evaluate_policy(
    policy: PolicyConfig | None,
    *,
    skill_dirs: list[Path],
    source_candidates: list[str] | None = None,
    resolved_commit: str = "",
    ref: str = "",
    target_harnesses: list[str] | None = None,
    sec_reports: dict[str, SecurityReport] | None = None,
) -> list[str]:
    """Return a list of policy violation descriptions (empty when compliant)."""
    if policy is None:
        return []

    violations: list[str] = []
    srcs = [s for s in (source_candidates or []) if s]

    if policy.allowed_harnesses and target_harnesses:
        allowed_canonical = set()
        for ah in policy.allowed_harnesses:
            try:
                allowed_canonical.add(harnesses.get(ah).name)
            except KeyError:
                allowed_canonical.add(ah.strip().lower())
        for th in target_harnesses:
            cname = harnesses.get(th).name if th in harnesses.HARNESSES else th
            if cname not in allowed_canonical:
                violations.append(
                    f"policy: harness {cname!r} is not in allowed_harnesses ({sorted(allowed_canonical)})"
                )

    if srcs and policy.restricted_sources and _source_matches_any(srcs, policy.restricted_sources, is_allowlist=False):
        violations.append(f"policy: source {srcs[0]!r} matches restricted_sources in {POLICY_FILENAME}")

    if srcs and policy.approved_sources and not _source_matches_any(srcs, policy.approved_sources, is_allowlist=True):
        violations.append(
            f"policy: source {srcs[0]!r} is not permitted by approved_sources in {POLICY_FILENAME}"
        )

    if policy.require_pinned_refs and srcs:
        is_remote = any(s.startswith(("https://", "http://", "git@", "github:", "registry:")) for s in srcs)
        if is_remote and not resolved_commit and not ref:
            violations.append(f"policy: remote source {srcs[0]!r} requires a pinned commit or tag ref")

    sev_threshold = SEVERITY_ORDER.get(policy.block_severity.upper(), SEVERITY_ORDER["HIGH"])
    banned_caps = {normalize_capability_name(c) for c in policy.banned_capabilities if c.strip()}

    for sdir in skill_dirs:
        sname = sdir.name
        srep = (sec_reports or {}).get(sname) or scan_skill(sdir, offline=True)
        if policy.max_risk_score is not None and srep.risk_score > policy.max_risk_score:
            violations.append(
                f"policy: {sname!r} risk_score {srep.risk_score}/100 "
                f"exceeds policy max_risk_score ({policy.max_risk_score})"
            )
        blocking_findings = [
            f.code for f in srep.findings if SEVERITY_ORDER.get(f.severity, 0) >= sev_threshold
        ]
        if blocking_findings:
            codes_str = ", ".join(sorted(set(blocking_findings)))
            violations.append(f"policy: {sname!r} triggered {policy.block_severity}+ finding(s): {codes_str}")

        cap_rep = analyze_capabilities(sdir)
        triggered_banned = sorted(set(cap_rep.inferred) & banned_caps)
        if triggered_banned:
            violations.append(
                f"policy: {sname!r} uses banned capability {', '.join(triggered_banned)} "
                f"(configured in {POLICY_FILENAME})"
            )
        if policy.require_declared_capabilities and (not cap_rep.has_declaration or cap_rep.undeclared):
            detail = (
                f"undeclared: {', '.join(cap_rep.undeclared)}"
                if cap_rep.has_declaration
                else "missing `capabilities:` frontmatter"
            )
            violations.append(f"policy: {sname!r} failed require_declared_capabilities ({detail})")

    return violations
