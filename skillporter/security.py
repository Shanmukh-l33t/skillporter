"""Static Security and Supply-Chain Assessment Engine for Agent Skills.

Skills are untrusted packages containing natural-language agent instructions
and optional executable scripts. This module performs static analysis on
SKILL.md, supporting Markdown, scripts, symlinks, and archive contents before
installation.

Assessment classification:
  * STATIC_SECURITY_ASSESSMENT — Heuristic/pattern and structural verification.
    Never claims that static scanning guarantees runtime safety.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SEVERITY_ORDER = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
}

STRUCTURAL_ESCAPE_CODES = frozenset({"sec-symlink-escape", "sec-path-traversal"})

MAX_SCAN_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB cap per text file during pattern scan

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
        re.compile(
            r"(?:base64\s+(?:-d|--decode)|xxd\s+-r)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?(?:sh|python|perl|node)\b"
        ),
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
    "sec-symlink-escape": "Remove symlinks that resolve outside the skill root directory.",
    "sec-broken-symlink": "Remove or fix broken symlinks inside the skill directory.",
    "sec-path-traversal": "Remove '..' path traversal segments from file paths.",
    "sec-binary-artifact": "Replace compiled binary blobs with auditable source scripts in scripts/.",
    "sec-script-outside-scripts-dir": "Move executable scripts into the standard scripts/ subdirectory.",
    "sec-oversized-file": "Split or compress large data assets so text files stay under 2 MiB.",
}


@dataclass
class SecurityFinding:
    """One static security finding in a skill package."""

    severity: str  # CRITICAL | HIGH | MEDIUM | LOW | INFO
    code: str
    file: str
    message: str
    line: int = 0
    remediation: str = ""

    def __post_init__(self) -> None:
        if not self.remediation and self.code in _REMEDIATIONS:
            self.remediation = _REMEDIATIONS[self.code]

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class SecurityReport:
    """Complete static security assessment of a skill directory."""

    root: Path
    assessment_type: str = "STATIC_SECURITY_ASSESSMENT"
    tree_hash: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)
    findings: list[SecurityFinding] = field(default_factory=list)

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
    def passed(self) -> bool:
        """Default policy: pass if there are no CRITICAL or HIGH findings."""
        return self.critical_count == 0 and self.high_count == 0

    def fails_policy(self, block_on: str = "HIGH") -> bool:
        threshold = SEVERITY_ORDER.get(block_on.upper(), SEVERITY_ORDER["HIGH"])
        return any(SEVERITY_ORDER.get(f.severity, 0) >= threshold for f in self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "assessment_type": self.assessment_type,
            "disclaimer": (
                "Static analysis inspects files for known dangerous patterns and integrity anomalies; "
                "it does not guarantee runtime safety."
            ),
            "passed": self.passed,
            "has_structural_escape": self.has_structural_escape,
            "tree_hash": self.tree_hash,
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
    """Inspect a symlink inside a skill directory.

    * If it points outside *resolved_root* AND the target exists on the host
      (e.g. ``/etc/shadow``, ``/root/.ssh``, ``../secret.txt``), return CRITICAL ``sec-symlink-escape``.
    * If it is a dangling/broken link to a non-existent path, return MEDIUM ``sec-broken-symlink``.
    """
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


def scan_skill(skill_dir: Path) -> SecurityReport:
    """Run static security and supply-chain checks on a skill directory."""
    raw_root = Path(skill_dir)
    resolved_root = raw_root.resolve()
    report = SecurityReport(root=resolved_root)

    if not raw_root.exists():
        report.findings.append(
            SecurityFinding("CRITICAL", "sec-missing-root", str(raw_root), "Skill directory does not exist")
        )
        return report

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
                    report.findings.append(
                        SecurityFinding(
                            "LOW",
                            "sec-oversized-file",
                            rel,
                            f"File exceeds {MAX_SCAN_FILE_BYTES} bytes; truncated during static pattern scan",
                        )
                    )
                    raw_bytes = raw_bytes[:MAX_SCAN_FILE_BYTES]
                text = raw_bytes.decode("utf-8", errors="replace")
            except OSError:
                continue

            if text.startswith("\ufeff"):
                text = text[1:]

            is_script = fpath.suffix.lower() in {".sh", ".bash", ".zsh", ".py", ".js", ".ts", ".mjs", ".ps1", ".rb"}
            is_markdown = fpath.suffix.lower() in {".md", ".mdc", ".txt"} or fpath.name == "SKILL.md"

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
                if is_markdown:
                    for sev, code, msg, pat in _PROMPT_PATTERNS:
                        if code == "sec-html-comment-instruction":
                            continue
                        if pat.search(line):
                            report.findings.append(SecurityFinding(sev, code, rel, msg, line=idx))

            if is_markdown:
                html_pat = _PROMPT_PATTERNS[2][3]
                if html_pat.search(text):
                    report.findings.append(
                        SecurityFinding(
                            _PROMPT_PATTERNS[2][0],
                            _PROMPT_PATTERNS[2][1],
                            rel,
                            _PROMPT_PATTERNS[2][2],
                        )
                    )

            if "\\\n" in text or "\\\r\n" in text:
                joined_text = re.sub(r"\\\r?\n[ \t]*", " ", text)
                existing_codes = {f.code for f in report.findings if f.file == rel}
                for l_idx, jline in enumerate(joined_text.splitlines(), start=1):
                    for sev, code, msg, pat in _SCRIPT_PATTERNS:
                        if code not in existing_codes and pat.search(jline):
                            effective_sev = sev if (is_script or sev in ("CRITICAL", "HIGH")) else "INFO"
                            report.findings.append(SecurityFinding(effective_sev, code, rel, msg, line=l_idx))
                            existing_codes.add(code)

    tree_hash, file_hashes = compute_tree_hash(resolved_root)
    report.tree_hash = tree_hash
    report.file_hashes = file_hashes
    return report
