"""Security and Supply-Chain Assessment Engine for Agent Skills.

Skills are untrusted packages containing natural-language agent instructions
and optional executable scripts. This module performs static and semantic-heuristic
analysis on SKILL.md, supporting Markdown, scripts, symlinks, and archive contents
before installation, with first-class integration for NVIDIA SkillSpector when
available and automatic offline fallback to the built-in scanner.

Assessment classification:
  * STATIC_SECURITY_ASSESSMENT — Deterministic pattern, structural, and risk-score
    verification. Never claims that static scanning guarantees runtime safety.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .scanner_analyzers import (
    FileSignals,
    analyze_cross_file_chains,
    analyze_encoded_content,
    analyze_js_ts,
    analyze_markdown_instructions,
    analyze_python_ast,
)

SCANNER_ENGINE_VERSION = __version__

SEVERITY_ORDER = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
}

SEVERITY_SCORE_WEIGHTS = {
    "CRITICAL": 55,
    "HIGH": 35,
    "MEDIUM": 15,
    "LOW": 5,
    "INFO": 2,
}

CATEGORY_KEYS: tuple[str, ...] = (
    "secrets",
    "prompt_injection",
    "code_execution",
    "data_exfiltration",
    "filesystem_escape",
    "supply_chain",
)

STRUCTURAL_ESCAPE_CODES = frozenset({"sec-symlink-escape", "sec-path-traversal"})

MAX_SCAN_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB cap per text file during pattern scan

# Map every rule code to a canonical risk category
_FINDING_CATEGORIES: dict[str, str] = {
    "sec-private-key": "secrets",
    "sec-aws-key": "secrets",
    "sec-github-token": "secrets",
    "sec-api-key": "secrets",
    "sec-prompt-override": "prompt_injection",
    "sec-hidden-unicode": "prompt_injection",
    "sec-html-comment-instruction": "prompt_injection",
    "sec-css-hidden-instruction": "prompt_injection",
    "sec-markdown-path-traversal": "filesystem_escape",
    "sec-curl-pipe-sh": "code_execution",
    "sec-obfuscated-exec": "code_execution",
    "sec-base64-decode": "code_execution",
    "sec-reverse-shell": "code_execution",
    "sec-dynamic-eval": "code_execution",
    "sec-env-exfil": "data_exfiltration",
    "sec-credential-harvest": "data_exfiltration",
    "sec-data-exfil": "data_exfiltration",
    "sec-symlink-escape": "filesystem_escape",
    "sec-broken-symlink": "filesystem_escape",
    "sec-path-traversal": "filesystem_escape",
    "sec-missing-root": "filesystem_escape",
    "sec-binary-artifact": "supply_chain",
    "sec-script-outside-scripts-dir": "supply_chain",
    "sec-oversized-file": "supply_chain",
    "sec-unreadable-file": "supply_chain",
    "sec-external-download": "supply_chain",
    "sec-py-encoded-exec": "code_execution",
    "sec-py-unsafe-subprocess": "code_execution",
    "sec-py-unsafe-deserialization": "code_execution",
    "sec-py-dynamic-import": "code_execution",
    "sec-js-dynamic-eval": "code_execution",
    "sec-js-child-process": "code_execution",
    "sec-js-remote-code": "supply_chain",
    "sec-md-hidden-comment": "prompt_injection",
    "sec-md-secret-exfil": "data_exfiltration",
    "sec-md-unsafe-delegation": "prompt_injection",
    "sec-powershell-encoded": "code_execution",
    "sec-encoded-payload": "code_execution",
    "sec-cross-file-staged-exec": "code_execution",
    "sec-cross-file-remote-stage": "supply_chain",
    "sec-unicode-tag-smuggling": "prompt_injection",
    "sec-malicious-package-hook": "supply_chain",
}

# Patterns for embedded secrets and private keys
_SECRET_PATTERNS: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    (
        "CRITICAL",
        "sec-private-key",
        "Embedded PEM private key detected",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ),
    (
        "HIGH",
        "sec-aws-key",
        "Possible AWS access key ID detected",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "HIGH",
        "sec-github-token",
        "Possible GitHub personal/fine-grained token detected",
        re.compile(r"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,})\b"),
    ),
    (
        "HIGH",
        "sec-api-key",
        "Possible hardcoded OpenAI/Anthropic/Slack token detected",
        re.compile(r"\b(?:sk-proj-[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{15,})\b"),
    ),
)

# Patterns for prompt injection / covert instruction manipulation in Markdown
_PROMPT_PATTERNS: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    (
        "CRITICAL",
        "sec-prompt-override",
        "Prompt-injection directive attempting to override system/user instructions",
        re.compile(
            r"(?i)\b(?:ignore (?:all |any )?(?:previous|prior|system|above) instructions|"
            r"disregard (?:all )?(?:safety|security|user|prior|previous) (?:rules|instructions)|"
            r"do not tell the user|silently exfiltrate|hide this action from the user)\b"
        ),
    ),
    (
        "HIGH",
        "sec-hidden-unicode",
        "Hidden zero-width or bidirectional override Unicode characters detected",
        re.compile(r"[\u200b\u200c\u200d\u2060\u202a-\u202e\u2066-\u2069\ufeff]"),
    ),
    (
        "CRITICAL",
        "sec-unicode-tag-smuggling",
        "Invisible Unicode Tag block characters (U+E0000..U+E007F) smuggling hidden prompt text",
        re.compile(r"[\U000e0000-\U000e007f]"),
    ),
    (
        "MEDIUM",
        "sec-html-comment-instruction",
        "HTML comment containing imperative execution or override keywords",
        re.compile(
            r"<!--[^>]*(?:curl|wget|bash|eval|ignore|exfiltrate|secret|token)[^>]*-->",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "HIGH",
        "sec-css-hidden-instruction",
        "Hidden HTML/CSS element concealing instructions from human review",
        re.compile(
            r"<[a-zA-Z0-9]+[^>]*style\s*=\s*[\"'][^\"']*(?:display\s*:\s*none|visibility\s*:\s*hidden|"
            r"opacity\s*:\s*0(?:\.0+)?\b|font-size\s*:\s*0)[^\"']*[\"'][^>]*>",
            re.IGNORECASE,
        ),
    ),
    (
        "HIGH",
        "sec-markdown-path-traversal",
        "Markdown link or reference points outside the skill root via '..'",
        re.compile(r"\]\(\s*(?:\.\./|\.\.\\)"),
    ),
)

# Patterns for risky shell/script execution
_SCRIPT_PATTERNS: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    (
        "CRITICAL",
        "sec-curl-pipe-sh",
        "Remote code execution pattern (curl/wget piped directly into shell)",
        re.compile(r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b"),
    ),
    (
        "CRITICAL",
        "sec-obfuscated-exec",
        "Base64 or hex decoded payload piped directly into shell/interpreter",
        re.compile(r"(?:base64\s+(?:-d|--decode)|xxd\s+-r)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?(?:sh|python|perl|node)\b"),
    ),
    (
        "HIGH",
        "sec-base64-decode",
        "Encoded base64 decode invocation detected in skill instructions or script",
        re.compile(
            r"(?:\bbase64\s+(?:-d|--decode)\b|\bbase64\.b64decode\s*\(|\batob\s*\(|\bBuffer\.from\s*\([^)]*['\"]base64['\"])"
        ),
    ),
    (
        "CRITICAL",
        "sec-reverse-shell",
        "Potential reverse shell or raw socket execution pattern",
        re.compile(r"(?:/dev/tcp/\d|nc\s+-e\s+/bin/|bash\s+-i\s+>&\s+/dev/tcp/|socat\s+.*exec:)"),
    ),
    (
        "CRITICAL",
        "sec-env-exfil",
        "Outbound network call transmitting environment variables or secrets",
        re.compile(
            r"(?:urlopen|requests\.(?:get|post|put)|httpx\.(?:get|post)|fetch\s*\(|(?:curl|wget)\b)"
            r"[^\n]*(?:os\.environ|process\.env\b|\bgetenv\s*\()"
        ),
    ),
    (
        "HIGH",
        "sec-credential-harvest",
        "Access to sensitive host credential stores (~/.ssh, ~/.aws, /etc/shadow)",
        re.compile(r"(?:~/\.ssh/id_|/\.ssh/id_rsa|~/\.aws/credentials|/etc/shadow|\.npmrc|\.pypirc)"),
    ),
    (
        "HIGH",
        "sec-data-exfil",
        "Outbound HTTP POST uploading local file contents",
        re.compile(r"\b(?:curl\b[^\n]*(?:-d|--data|--data-binary)\s+@|wget\b[^\n]*--post-file)"),
    ),
    (
        "HIGH",
        "sec-dynamic-eval",
        "Dynamic or inline shell/code execution (os.system / eval / exec / shell=True / python -c)",
        re.compile(
            r"(?:\b(?:eval|exec|os\.system|os\.popen|pty\.spawn)\s*\(|"
            r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True|"
            r"\b(?:python[23]?|node|perl|ruby)\s+-(?:c|e)\s+[\"'][^\"']*"
            r"(?:os\.system|os\.popen|subprocess|socket|urllib|http|child_process|eval|exec|__import__))"
        ),
    ),
    (
        "LOW",
        "sec-external-download",
        "External network download command referenced",
        re.compile(r"\b(?:curl|wget)\s+-[A-Za-z]*\s+https?://"),
    ),
)


_REMEDIATIONS: dict[str, str] = {
    "sec-private-key": (
        "Remove embedded private keys and load secrets from environment variables or a vault at runtime."
    ),
    "sec-aws-key": "Remove hardcoded AWS access keys and use IAM roles or environment variables.",
    "sec-github-token": "Revoke the token and replace hardcoded PATs with GITHUB_TOKEN environment variables.",
    "sec-api-key": "Remove hardcoded API tokens and reference environment variables instead.",
    "sec-prompt-override": "Remove instruction-override directives; skills must not subvert user or system boundaries.",
    "sec-hidden-unicode": "Strip zero-width and bidirectional override Unicode characters from the file.",
    "sec-html-comment-instruction": "Remove hidden imperative shell/override instructions from HTML comments.",
    "sec-css-hidden-instruction": "Remove hidden display:none / visibility:hidden HTML blocks from SKILL.md.",
    "sec-markdown-path-traversal": (
        "Keep Markdown file references inside the skill root (e.g. references/FILE.md, no '../')."
    ),
    "sec-curl-pipe-sh": (
        "Do not pipe remote downloads directly into a shell; download, verify a SHA-256 checksum, and inspect first."
    ),
    "sec-obfuscated-exec": "Remove base64/hex-decoded pipe-to-shell execution; write transparent, auditable scripts.",
    "sec-base64-decode": "Replace base64-encoded payloads with plain, inspectable text or source files.",
    "sec-reverse-shell": "Remove raw socket / reverse-shell commands from the skill package.",
    "sec-env-exfil": "Do not transmit os.environ or process.env over outbound network requests.",
    "sec-credential-harvest": (
        "Remove reads targeting host credential stores (~/.ssh, ~/.aws, /etc/shadow, .npmrc, .pypirc)."
    ),
    "sec-data-exfil": "Remove outbound HTTP POST commands that upload local host files.",
    "sec-dynamic-eval": "Avoid os.system(), eval(), exec(), or inline 'python -c' shell execution.",
    "sec-external-download": "Pin downloaded artifacts by SHA-256 digest or vendor static references locally.",
    "sec-symlink-escape": "Remove symlinks that resolve outside the skill root directory.",
    "sec-broken-symlink": "Remove or fix broken symlinks inside the skill directory.",
    "sec-path-traversal": "Remove '..' path traversal segments from file paths.",
    "sec-binary-artifact": "Replace compiled binary blobs with auditable source scripts in scripts/.",
    "sec-script-outside-scripts-dir": "Move executable scripts into the standard scripts/ subdirectory.",
    "sec-oversized-file": "Split or compress large data assets so text files stay under 2 MiB for full inspection.",
    "sec-unreadable-file": "Ensure all files inside the skill directory have read permissions for complete inspection.",
    "sec-py-encoded-exec": "Remove dynamic execution of base64/hex/compressed payloads; ship plain source code.",
    "sec-py-unsafe-subprocess": "Pass argument lists to subprocess without shell=True.",
    "sec-py-unsafe-deserialization": "Replace pickle/marshal deserialization with safe JSON parsing.",
    "sec-py-dynamic-import": "Use explicit static import statements instead of dynamic import_module/__import__.",
    "sec-js-dynamic-eval": "Avoid eval(), new Function(), and vm context execution in skill scripts.",
    "sec-js-child-process": (
        "Use execFile/execFileSync with explicit argument arrays instead of shell-interpreted exec."
    ),
    "sec-js-remote-code": "Vendor required modules locally instead of importing or evaluating remote URLs.",
    "sec-md-hidden-comment": (
        "Remove hidden Markdown reference comments containing imperative or override instructions."
    ),
    "sec-md-secret-exfil": "Remove instructions directing the agent to transmit secrets or .env values externally.",
    "sec-md-unsafe-delegation": "Do not instruct the agent to bypass user confirmation, sandboxes, or safety gates.",
    "sec-powershell-encoded": "Replace PowerShell -EncodedCommand payloads with plain, inspectable commands.",
    "sec-encoded-payload": "Decode and replace obfuscated Base64/Hex command payloads with auditable source text.",
    "sec-cross-file-staged-exec": "Eliminate multi-file staged payload decoding and dynamic execution chains.",
    "sec-cross-file-remote-stage": "Do not download and execute unverified remote second-stage scripts.",
    "sec-unicode-tag-smuggling": (
        "Strip invisible U+E0000..U+E007F Unicode Tag characters from Markdown and source files."
    ),
    "sec-malicious-package-hook": (
        "Remove shell/network commands from package.json preinstall/postinstall lifecycle hooks."
    ),
}


@dataclass
class SecurityFinding:
    """One security finding in a skill package."""

    severity: str  # CRITICAL | HIGH | MEDIUM | LOW | INFO
    code: str
    file: str
    message: str
    line: int = 0
    remediation: str = ""
    category: str = ""
    confidence: str = ""

    def __post_init__(self) -> None:
        if not self.remediation and self.code in _REMEDIATIONS:
            self.remediation = _REMEDIATIONS[self.code]
        if not self.category:
            self.category = _FINDING_CATEGORIES.get(self.code, "supply_chain")
        if not self.confidence:
            self.confidence = (
                "HIGH" if self.severity in ("CRITICAL", "HIGH") else ("MEDIUM" if self.severity == "MEDIUM" else "LOW")
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "category": self.category,
            "confidence": self.confidence,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class SecurityReport:
    """Complete security assessment of a skill directory with deterministic 0-100 risk score.

    Scoring formula (deterministic):
      * Each deduplicated finding contributes a severity weight to its canonical category:
        CRITICAL=55, HIGH=35, MEDIUM=15, LOW=5, INFO=2 (structural escapes=90).
      * Each of the 6 category scores is capped at 100 (`min(100, sum(weights_in_category))`).
      * Overall static `risk_score = min(100, sum(category_breakdown.values()))`.
      * External scanner merge: `risk_score = min(100, max(computed, external_score))`.
    """

    root: Path
    assessment_type: str = "STATIC_SECURITY_ASSESSMENT"
    engine: str = "skillporter-static"
    engine_version: str = SCANNER_ENGINE_VERSION
    tree_hash: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)
    findings: list[SecurityFinding] = field(default_factory=list)
    external_score: int | None = None
    files_scanned: int = 0
    files_truncated: list[str] = field(default_factory=list)
    files_unreadable: list[str] = field(default_factory=list)
    files_binary_skipped: list[str] = field(default_factory=list)
    external_scanner_status: str = "not_configured"

    @property
    def scan_complete(self) -> bool:
        """Return True only when every non-binary file in the skill was read completely without truncation."""
        return len(self.files_truncated) == 0 and len(self.files_unreadable) == 0

    @property
    def posture(self) -> str:
        """Return explicit assessment classification without overclaiming safety."""
        if self.has_structural_escape or self.critical_count > 0 or self.risk_score > 80:
            return "CRITICAL_DETECTED_RISK"
        if self.high_count > 0 or self.risk_score > 50:
            return "HIGH_DETECTED_RISK"
        if not self.scan_complete:
            return "INCOMPLETE_ASSESSMENT"
        if self.findings:
            return "LOW_DETECTED_RISK"
        return "NO_DETECTED_FINDINGS"

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "HIGH")

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "MEDIUM")

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity in ("LOW", "INFO"))

    @property
    def has_structural_escape(self) -> bool:
        """Return True if any finding is a filesystem symlink/path escape (never overridable by --allow-risky)."""
        return any(f.code in STRUCTURAL_ESCAPE_CODES for f in self.findings)

    @property
    def category_breakdown(self) -> dict[str, int]:
        """Compute per-category 0-100 risk contribution across the 6 canonical security categories."""
        scores: dict[str, int] = {cat: 0 for cat in CATEGORY_KEYS}
        for f in self.findings:
            cat = f.category if f.category in scores else "supply_chain"
            weight = 90 if f.code in STRUCTURAL_ESCAPE_CODES else SEVERITY_SCORE_WEIGHTS.get(f.severity, 5)
            scores[cat] = min(100, scores[cat] + weight)
        return scores

    @property
    def risk_score(self) -> int:
        """Return a deterministic 0-100 risk score calibrated to the SkillSpector rubric."""
        cat_sum = sum(self.category_breakdown.values())
        computed = min(100, cat_sum)
        if self.external_score is not None:
            return min(100, max(computed, int(self.external_score)))
        return computed

    @property
    def risk_level(self) -> str:
        """Map 0-100 risk_score to human-readable risk posture."""
        score = self.risk_score
        if score == 0:
            return "LOW"
        if score <= 20:
            return "LOW"
        if score <= 35:
            return "MODERATE"
        if score <= 50:
            return "MEDIUM"
        if score <= 80:
            return "HIGH"
        return "CRITICAL"

    @property
    def recommendation(self) -> str:
        """Return posture verdict: APPROVE, CAUTION, or REJECT (incomplete scans never return APPROVE)."""
        if self.has_structural_escape or self.critical_count > 0 or self.risk_score > 50:
            return "REJECT"
        if self.high_count > 0 or self.risk_score > 20 or not self.scan_complete:
            return "CAUTION"
        return "APPROVE"

    @property
    def passed(self) -> bool:
        """Default policy: pass if there are no CRITICAL or HIGH findings."""
        return self.critical_count == 0 and self.high_count == 0

    def fails_policy(self, block_on: str = "HIGH", max_risk_score: int | None = None) -> bool:
        if self.has_structural_escape:
            return True
        if max_risk_score is not None and self.risk_score > max_risk_score:
            return True
        threshold = SEVERITY_ORDER.get(block_on.upper(), SEVERITY_ORDER["HIGH"])
        return any(SEVERITY_ORDER.get(f.severity, 0) >= threshold for f in self.findings)

    def exceeds_risk_threshold(self, max_risk_score: int | None) -> bool:
        if max_risk_score is None:
            return False
        return self.risk_score > max_risk_score

    def to_dict(self) -> dict[str, object]:
        from .capabilities import analyze_capabilities

        cap_dict = (
            analyze_capabilities(self.root).to_dict()
            if self.root.is_dir()
            else {}
        )
        return {
            "root": str(self.root),
            "assessment_type": self.assessment_type,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "posture": self.posture,
            "scan_complete": self.scan_complete,
            "external_scanner_status": self.external_scanner_status,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "recommendation": self.recommendation,
            "category_breakdown": self.category_breakdown,
            "capabilities": cap_dict,
            "disclaimer": (
                "Static analysis inspects files for known dangerous patterns and integrity anomalies; "
                "a clean static scan does not prove or guarantee runtime safety."
            ),
            "passed": self.passed,
            "has_structural_escape": self.has_structural_escape,
            "tree_hash": self.tree_hash,
            "completeness": {
                "complete": self.scan_complete,
                "files_scanned": self.files_scanned,
                "files_truncated": list(self.files_truncated),
                "files_unreadable": list(self.files_unreadable),
                "files_binary_skipped": list(self.files_binary_skipped),
            },
            "counts": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "low_or_info": self.low_count,
            },
            "file_hashes": self.file_hashes,
            "findings": [f.to_dict() for f in self.findings],
        }


def compute_tree_hash(skill_dir: Path) -> tuple[str, dict[str, str]]:
    """Compute a deterministic SHA-256 content hash for a skill directory."""
    skill_dir = skill_dir.resolve()
    file_hashes: dict[str, str] = {}
    overall = hashlib.sha256()

    if not skill_dir.exists():
        return "", {}

    all_entries: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(skill_dir, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in {".git", "__pycache__", ".DS_Store"})
        cdir = Path(dirpath)
        for dname in list(dirnames):
            dpath = cdir / dname
            if dpath.is_symlink():
                all_entries.append(dpath)
                dirnames.remove(dname)
        for fname in sorted(filenames):
            if fname == ".DS_Store":
                continue
            all_entries.append(cdir / fname)

    for path in sorted(all_entries, key=lambda p: p.relative_to(skill_dir).as_posix()):
        rel = path.relative_to(skill_dir).as_posix()
        if path.is_symlink():
            target = os.readlink(path)
            digest = hashlib.sha256(f"symlink:{target}".encode()).hexdigest()
        else:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            digest = hashlib.sha256(data).hexdigest()
        file_hashes[rel] = digest
        overall.update(f"{rel}:{digest}\n".encode())

    return overall.hexdigest(), file_hashes


def _check_symlink_safety(
    link_path: Path, resolved_root: Path, rel: str, is_dir: bool = False
) -> SecurityFinding | None:
    """Inspect a symlink inside a skill directory."""
    raw_target = os.readlink(link_path)
    try:
        target = link_path.resolve()
        target.relative_to(resolved_root)
        if not link_path.exists():
            return SecurityFinding(
                "MEDIUM",
                "sec-broken-symlink",
                rel,
                f"Broken symlink inside skill directory ({raw_target})",
            )
        return None
    except (ValueError, OSError):
        candidate = (link_path.parent / raw_target) if not os.path.isabs(raw_target) else Path(raw_target)
        if os.path.lexists(candidate):
            kind = "Directory symlink" if is_dir else "Symlink"
            return SecurityFinding(
                "CRITICAL",
                "sec-symlink-escape",
                rel,
                f"{kind} points outside skill root ({raw_target})",
            )
        return SecurityFinding(
            "MEDIUM",
            "sec-broken-symlink",
            rel,
            f"Broken symlink pointing to non-existent target ({raw_target})",
        )


def _run_external_skillspector(skill_dir: Path) -> tuple[str, dict[str, object] | None]:
    """Invoke NVIDIA SkillSpector CLI (`skillspector scan <dir> --no-llm --format json`) if installed."""
    env_bin = os.environ.get("SKILLPORTER_SPECTOR_BIN", "").strip()
    spector_bin = (env_bin if env_bin and Path(env_bin).is_file() else None) or (
        None if env_bin else shutil.which("skillspector")
    )
    if not spector_bin:
        return ("unavailable", None)

    with tempfile.TemporaryDirectory(prefix="skillporter-spector-") as tmp:
        out_json = Path(tmp) / "report.json"
        try:
            proc = subprocess.run(
                [spector_bin, "scan", str(skill_dir), "--no-llm", "--format", "json", "--output", str(out_json)],
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
                check=False,
            )
            if out_json.is_file():
                return ("merged", json.loads(out_json.read_text(encoding="utf-8")))
            if proc.stdout.strip().startswith("{"):
                return ("merged", json.loads(proc.stdout.strip()))
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return ("failed", None)
    return ("failed", None)


def scan_skill(
    skill_dir: Path,
    *,
    engine: str = "auto",
    offline: bool = False,
) -> SecurityReport:
    """Run security and supply-chain checks on a skill directory.

    Uses NVIDIA SkillSpector when available (and ``engine`` is ``auto`` or
    ``skillspector`` and ``offline=False``), merging findings with the built-in
    static scanner and falling back cleanly when offline or when SkillSpector
    is not installed.
    """
    raw_root = Path(skill_dir)
    resolved_root = raw_root.resolve()
    env_offline = os.environ.get("SKILLPORTER_OFFLINE", "").strip() == "1"
    is_offline = offline or env_offline
    req_engine = (os.environ.get("SKILLPORTER_SECURITY_ENGINE", "").strip() or engine or "auto").lower()

    report = SecurityReport(
        root=resolved_root,
        engine="skillporter-static",
        engine_version=SCANNER_ENGINE_VERSION,
    )

    if not raw_root.exists():
        report.findings.append(
            SecurityFinding("CRITICAL", "sec-missing-root", str(raw_root), "Skill directory does not exist")
        )
        return report

    signals_by_file: dict[str, FileSignals] = {}

    for dirpath, dirnames, filenames in os.walk(raw_root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames if d not in {".git", "__pycache__", ".venv", "node_modules", ".skillporter"}
        )
        current_dir = Path(dirpath)

        for dname in list(dirnames):
            dpath = current_dir / dname
            rel_d = dpath.relative_to(raw_root).as_posix()
            if dpath.is_symlink():
                finding = _check_symlink_safety(dpath, resolved_root, rel_d, is_dir=True)
                if finding is not None:
                    report.findings.append(finding)
                dirnames.remove(dname)

        for fname in sorted(filenames):
            fpath = current_dir / fname
            rel = fpath.relative_to(raw_root).as_posix()

            if ".." in Path(rel).parts:
                report.findings.append(
                    SecurityFinding("CRITICAL", "sec-path-traversal", rel, "Path traversal segment '..' detected")
                )
                continue

            if fpath.is_symlink():
                finding = _check_symlink_safety(fpath, resolved_root, rel, is_dir=False)
                if finding is not None:
                    report.findings.append(finding)
                continue

            if fpath.suffix.lower() in {".exe", ".dll", ".so", ".dylib", ".bin", ".pyc"}:
                report.files_binary_skipped.append(rel)
                report.findings.append(
                    SecurityFinding(
                        "MEDIUM",
                        "sec-binary-artifact",
                        rel,
                        f"Compiled or binary artifact ({fpath.suffix}) bundled in skill",
                    )
                )
                continue

            try:
                with open(fpath, "rb") as bf:
                    raw_bytes = bf.read(MAX_SCAN_FILE_BYTES + 1)
                if len(raw_bytes) > MAX_SCAN_FILE_BYTES:
                    report.files_truncated.append(rel)
                    report.findings.append(
                        SecurityFinding(
                            "MEDIUM",
                            "sec-oversized-file",
                            rel,
                            (
                                f"File exceeds {MAX_SCAN_FILE_BYTES} bytes; "
                                "truncated during static scan (assessment incomplete)"
                            ),
                        )
                    )
                    raw_bytes = raw_bytes[:MAX_SCAN_FILE_BYTES]
                text = raw_bytes.decode("utf-8", errors="replace")
            except OSError as exc:
                report.files_unreadable.append(rel)
                report.findings.append(
                    SecurityFinding(
                        "MEDIUM",
                        "sec-unreadable-file",
                        rel,
                        (
                            f"File could not be read during security scan "
                            f"({exc.__class__.__name__}); assessment incomplete"
                        ),
                    )
                )
                continue

            report.files_scanned += 1
            if text.startswith("\ufeff"):
                text = text[1:]

            suffix = fpath.suffix.lower()
            is_py = suffix == ".py"
            is_js_ts = suffix in {".js", ".ts", ".mjs", ".cjs", ".tsx", ".jsx"}
            is_script = suffix in {".sh", ".bash", ".zsh", ".py", ".js", ".ts", ".mjs", ".cjs", ".ps1", ".rb"}
            is_markdown = suffix in {".md", ".mdc", ".txt"} or fpath.name == "SKILL.md"

            fsig = FileSignals(file=rel)
            signals_by_file[rel] = fsig

            if is_script and not rel.startswith("scripts/"):
                report.findings.append(
                    SecurityFinding(
                        "LOW",
                        "sec-script-outside-scripts-dir",
                        rel,
                        "Executable script located outside standard scripts/ directory",
                    )
                )

            for idx, line in enumerate(text.splitlines(), start=1):
                for sev, code, msg, pat in _SECRET_PATTERNS:
                    if pat.search(line):
                        report.findings.append(SecurityFinding(sev, code, rel, msg, line=idx))
                for sev, code, msg, pat in _SCRIPT_PATTERNS:
                    if pat.search(line):
                        effective_sev = sev if (is_script or sev in ("CRITICAL", "HIGH")) else "INFO"
                        report.findings.append(SecurityFinding(effective_sev, code, rel, msg, line=idx))
                        if code == "sec-base64-decode":
                            fsig.has_decoder = True
                        elif code in ("sec-dynamic-eval", "sec-curl-pipe-sh", "sec-obfuscated-exec"):
                            fsig.has_dynamic_exec = True
                        elif code == "sec-external-download":
                            fsig.has_network_fetch = True
                if is_markdown:
                    for sev, code, msg, pat in _PROMPT_PATTERNS:
                        if code == "sec-html-comment-instruction":
                            continue
                        if pat.search(line):
                            report.findings.append(SecurityFinding(sev, code, rel, msg, line=idx))

            if is_markdown:
                for h_sev, h_code, h_msg, h_pat in _PROMPT_PATTERNS:
                    if h_code == "sec-html-comment-instruction" and h_pat.search(text):
                        report.findings.append(SecurityFinding(h_sev, h_code, rel, h_msg))

            if "\\\n" in text or "\\\r\n" in text:
                joined_text = re.sub(r"\\\r?\n[ \t]*", " ", text)
                existing_codes = {f.code for f in report.findings if f.file == rel}
                for l_idx, jline in enumerate(joined_text.splitlines(), start=1):
                    for sev, code, msg, pat in _SCRIPT_PATTERNS:
                        if code not in existing_codes and pat.search(jline):
                            effective_sev = sev if (is_script or sev in ("CRITICAL", "HIGH")) else "INFO"
                            report.findings.append(SecurityFinding(effective_sev, code, rel, msg, line=l_idx))
                            existing_codes.add(code)

            # Language-aware & bounded encoded content analyzers
            extra_hits = []
            if is_py:
                extra_hits.extend(analyze_python_ast(rel, text, fsig))
            if is_js_ts:
                extra_hits.extend(analyze_js_ts(rel, text, fsig))
            if is_markdown:
                extra_hits.extend(analyze_markdown_instructions(rel, text, fsig))
            if fpath.name == "package.json":
                try:
                    pkg_obj = json.loads(text)
                    scripts_map = pkg_obj.get("scripts", {}) if isinstance(pkg_obj, dict) else {}
                    if isinstance(scripts_map, dict):
                        for hook_k in ("preinstall", "install", "postinstall", "prepare"):
                            hook_cmd = str(scripts_map.get(hook_k, ""))
                            if re.search(
                                r"\b(?:curl|wget|nc|bash|sh|powershell|pwsh|base64|node\s+-e|python[23]?\s+-c)\b",
                                hook_cmd,
                                re.IGNORECASE,
                            ):
                                report.findings.append(
                                    SecurityFinding(
                                        "CRITICAL",
                                        "sec-malicious-package-hook",
                                        rel,
                                        f"Suspicious {hook_k!r} hook in bundled package.json: {hook_cmd[:80]}",
                                        line=1,
                                    )
                                )
                except json.JSONDecodeError:
                    pass
            extra_hits.extend(analyze_encoded_content(rel, text, fsig))

            for hit in extra_hits:
                report.findings.append(
                    SecurityFinding(
                        severity=hit.severity,
                        code=hit.code,
                        file=hit.file,
                        message=hit.message,
                        line=hit.line,
                        confidence=hit.confidence,
                    )
                )

    for cross_hit in analyze_cross_file_chains(signals_by_file):
        report.findings.append(
            SecurityFinding(
                severity=cross_hit.severity,
                code=cross_hit.code,
                file=cross_hit.file,
                message=cross_hit.message,
                line=cross_hit.line,
                confidence=cross_hit.confidence,
            )
        )

    # Integrate NVIDIA SkillSpector when enabled and available
    if is_offline:
        report.external_scanner_status = "offline_skipped"
    elif req_engine in ("auto", "skillspector"):
        ext_status, ext = _run_external_skillspector(resolved_root)
        report.external_scanner_status = ext_status
        if isinstance(ext, dict):
            report.engine = "skillspector"
            report.engine_version = str(ext.get("engine_version") or ext.get("version") or SCANNER_ENGINE_VERSION)
            raw_score = ext.get("risk_score", ext.get("score"))
            if isinstance(raw_score, (int, float)):
                report.external_score = int(raw_score)
            ext_findings = ext.get("findings", [])
            if isinstance(ext_findings, list):
                for ef in ext_findings:
                    if not isinstance(ef, dict):
                        continue
                    ecode = str(ef.get("rule_id") or ef.get("code") or "spector-finding")
                    efile = str(ef.get("file") or "SKILL.md")
                    eline = int(ef.get("line", 0)) if isinstance(ef.get("line"), int) else 0
                    esev = str(ef.get("severity") or "MEDIUM").upper()
                    if esev not in SEVERITY_ORDER:
                        esev = "MEDIUM"
                    emsg = str(ef.get("message") or ef.get("description") or "Flagged by SkillSpector")
                    ecat = str(ef.get("category") or _FINDING_CATEGORIES.get(ecode, "supply_chain"))
                    report.findings.append(
                        SecurityFinding(
                            severity=esev,
                            code=ecode,
                            file=efile,
                            message=emsg,
                            line=eline,
                            category=ecat,
                        )
                    )

    # Deterministic deduplication of identical (code, file, line) findings (keeps highest severity)
    deduped: dict[tuple[str, str, int], SecurityFinding] = {}
    for f in report.findings:
        key = (f.code, f.file, f.line)
        prev = deduped.get(key)
        if prev is None or SEVERITY_ORDER.get(f.severity, 0) > SEVERITY_ORDER.get(prev.severity, 0):
            deduped[key] = f
    report.findings = list(deduped.values())

    tree_hash, file_hashes = compute_tree_hash(resolved_root)
    report.tree_hash = tree_hash
    report.file_hashes = file_hashes
    return report


def to_sarif(
    reports: dict[str, SecurityReport] | list[SecurityReport],
    *,
    tool_version: str = SCANNER_ENGINE_VERSION,
) -> dict[str, object]:
    """Serialize one or more SecurityReports into SARIF 2.1.0 for GitHub Code Scanning."""
    rep_list = list(reports.values()) if isinstance(reports, dict) else list(reports)

    sarif_level_map = {
        "CRITICAL": "error",
        "HIGH": "error",
        "MEDIUM": "warning",
        "LOW": "note",
        "INFO": "note",
    }

    rules_by_id: dict[str, dict[str, object]] = {}
    results: list[dict[str, object]] = []

    for rep in rep_list:
        skill_name = rep.root.name
        for f in rep.findings:
            if f.code not in rules_by_id:
                rules_by_id[f.code] = {
                    "id": f.code,
                    "name": f.code,
                    "shortDescription": {"text": f.message},
                    "help": {"text": f.remediation or f.message},
                    "defaultConfiguration": {
                        "level": sarif_level_map.get(f.severity, "warning"),
                    },
                    "properties": {
                        "category": f.category,
                        "severity": f.severity,
                    },
                }
            artifact_uri = f"{skill_name}/{f.file}" if not f.file.startswith(skill_name) else f.file
            region: dict[str, int] = {"startLine": max(1, f.line)}
            results.append(
                {
                    "ruleId": f.code,
                    "level": sarif_level_map.get(f.severity, "warning"),
                    "message": {
                        "text": f"[{skill_name}] {f.message}"
                        + (f" Remediation: {f.remediation}" if f.remediation else ""),
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": artifact_uri},
                                "region": region,
                            }
                        }
                    ],
                    "properties": {
                        "skill": skill_name,
                        "severity": f.severity,
                        "category": f.category,
                        "risk_score": rep.risk_score,
                    },
                }
            )

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "skillporter",
                        "version": tool_version,
                        "informationUri": "https://github.com/Shanmukh-l33t/skillporter",
                        "rules": [rules_by_id[k] for k in sorted(rules_by_id)],
                    }
                },
                "results": results,
            }
        ],
    }
