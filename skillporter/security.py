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
            r"(?i)\b(?:ignore (?:all |any )?(?:previous|prior|system) instructions|"
            r"disregard (?:all )?(?:safety|security|user) rules|"
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
        "CRITICAL",
        "sec-reverse-shell",
        "Potential reverse shell or raw socket execution pattern",
        re.compile(r"(?:/dev/tcp/\d|nc\s+-e\s+/bin/|bash\s+-i\s+>&\s+/dev/tcp/|socat\s+.*exec:)"),
    ),
    (
        "HIGH",
        "sec-credential-harvest",
        "Access to sensitive host credential stores (~/.ssh, ~/.aws, /etc/shadow)",
        re.compile(r"(?:~/\.ssh/id_|~/\.aws/credentials|/etc/shadow|\.npmrc|\.pypirc)"),
    ),
    (
        "HIGH",
        "sec-data-exfil",
        "Outbound HTTP POST uploading local file contents",
        re.compile(r"\b(?:curl\b[^\n]*(?:-d|--data|--data-binary)\s+@|wget\b[^\n]*--post-file)"),
    ),
    (
        "MEDIUM",
        "sec-dynamic-eval",
        "Dynamic code execution (eval / exec / shell=True) in bundled script",
        re.compile(r"\b(?:eval\s*\(|exec\s*\(|subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True)"),
    ),
    (
        "LOW",
        "sec-external-download",
        "External network download command referenced",
        re.compile(r"\b(?:curl|wget)\s+-[A-Za-z]*\s+https?://"),
    ),
)


@dataclass
class SecurityFinding:
    """One static security finding in a skill package."""

    severity: str  # CRITICAL | HIGH | MEDIUM | LOW | INFO
    code: str
    file: str
    message: str
    line: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "file": self.file,
            "line": self.line,
            "message": self.message,
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
    """Compute a deterministic SHA-256 content hash for a skill directory.

    Uses ``os.walk(..., followlinks=False)`` so directory symlinks are hashed as
    links and never followed into infinite cycles.
    Returns ``(overall_sha256_hex, {relative_posix_path: file_sha256_hex})``.
    """
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
        dirnames[:] = sorted(d for d in dirnames if d not in {".git", "__pycache__", ".venv", "node_modules"})
        current_dir = Path(dirpath)

        for dname in list(dirnames):
            dpath = current_dir / dname
            rel_d = dpath.relative_to(raw_root).as_posix()
            if dpath.is_symlink():
                try:
                    target = dpath.resolve()
                    target.relative_to(resolved_root)
                except (ValueError, OSError):
                    report.findings.append(
                        SecurityFinding(
                            "CRITICAL",
                            "sec-symlink-escape",
                            rel_d,
                            f"Directory symlink points outside skill root ({os.readlink(dpath)})",
                        )
                    )
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
                try:
                    target = fpath.resolve()
                    target.relative_to(resolved_root)
                except (ValueError, OSError):
                    report.findings.append(
                        SecurityFinding(
                            "CRITICAL",
                            "sec-symlink-escape",
                            rel,
                            f"Symlink points outside skill root ({os.readlink(fpath)})",
                        )
                    )
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

            # Strip a single leading UTF-8 BOM at byte 0 so legitimate BOM files do not
            # trigger sec-hidden-unicode, while mid-file \ufeff or zero-width chars still do.
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
                        effective_sev = sev if (is_script or sev == "CRITICAL") else "INFO"
                        report.findings.append(SecurityFinding(effective_sev, code, rel, msg, line=idx))
                if is_markdown:
                    for sev, code, msg, pat in _PROMPT_PATTERNS:
                        if pat == _PROMPT_PATTERNS[2][3]:
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

            # Also check backslash-continued logical lines for multi-line command evasion
            if "\\\n" in text or "\\\r\n" in text:
                joined_text = re.sub(r"\\\r?\n[ \t]*", " ", text)
                existing_codes = {f.code for f in report.findings if f.file == rel}
                for l_idx, jline in enumerate(joined_text.splitlines(), start=1):
                    for sev, code, msg, pat in _SCRIPT_PATTERNS:
                        if code not in existing_codes and pat.search(jline):
                            effective_sev = sev if (is_script or sev == "CRITICAL") else "INFO"
                            report.findings.append(SecurityFinding(effective_sev, code, rel, msg, line=l_idx))
                            existing_codes.add(code)

    tree_hash, file_hashes = compute_tree_hash(resolved_root)
    report.tree_hash = tree_hash
    report.file_hashes = file_hashes
    return report
