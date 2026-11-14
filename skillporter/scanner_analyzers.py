"""Bounded Language-Aware & Cross-File Static Security Analyzers.

Provides deterministic, zero-execution analyzers used by ``skillporter.security``:
  * Python AST security analyzer (alias tracking, shell=True subprocess, dynamic imports,
    unsafe deserialization, encoded exec, socket reverse shells, credential store reads)
  * JavaScript / TypeScript static analyzer (new Function, vm contexts, shell child_process,
    remote dynamic ESM imports, process.env exfiltration)
  * Markdown instruction & delegation analyzer (comment smuggling, secret exfiltration
    directives, safety/sandbox bypass delegation)
  * Bounded Base64 / Hex / PowerShell -EncodedCommand inspector (strict memory caps,
    never executes decoded content)
  * Cross-file multi-stage correlation (encoded blob + decoder + dynamic exec across files;
    SKILL.md referencing a remote second-stage dropper script).
"""

from __future__ import annotations

import ast
import base64
import binascii
import re
from dataclasses import dataclass, field

MAX_ENCODED_CANDIDATES_PER_FILE = 32
MAX_ENCODED_TOKEN_CHARS = 8192

_SENSITIVE_PATH_SUBSTRINGS: tuple[str, ...] = (
    ".ssh/id_",
    ".ssh/authorized_keys",
    ".aws/credentials",
    ".kube/config",
    ".gnupg/",
    "/etc/shadow",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "Library/Keychains",
    "Login Data",
)

_DECODED_MALICIOUS_RE = re.compile(
    r"(?i)(?:\b(?:curl|wget)\b[^\n]*\|\s*(?:ba)?sh\b|"
    r"/dev/tcp/\d|bash\s+-i|nc\s+-e|"
    r"\b(?:Invoke-Expression|IEX|DownloadString|FromBase64String)\b|"
    r"\b(?:os\.system|pty\.spawn|subprocess\.Popen)\b|"
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
    r"(?:~/.ssh/|/etc/shadow|\.aws/credentials))"
)

_POWERSHELL_ENC_RE = re.compile(
    r"(?i)\b(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\b[^\n]*?\s-(?:e|ec|enc|encodedcommand)\s+([A-Za-z0-9+/=]{16,4096})"
)

_B64_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9+/=])([A-Za-z0-9+/]{28,}={0,2})(?![A-Za-z0-9+/=])")
_HEX_CANDIDATE_RE = re.compile(r"(?<![0-9a-fA-F])((?:[0-9a-fA-F]{2}){20,2048})(?![0-9a-fA-F])")

_JS_DYNAMIC_EVAL_RE = re.compile(
    r"(?:\bnew\s+Function\s*\(|\bvm\.(?:runInNewContext|runInThisContext|runInContext|compileFunction)\s*\(|\beval\s*\()"
)
_JS_CHILD_PROC_RE = re.compile(
    r"(?:\b(?:child_process\.)?(?:exec|execSync)\s*\(|\bspawn(?:Sync)?\s*\([^)]*shell\s*:\s*true)"
)
_JS_REMOTE_CODE_RE = re.compile(
    r"(?:\bimport\s*\(\s*['\"`]https?://|\bfetch\s*\([^)]*\)[\s\S]{0,160}?\.\s*then\s*\(\s*(?:eval|Function)\b)"
)
_JS_ENV_EXFIL_RE = re.compile(
    r"(?:\bfetch|\baxios\.(?:post|get|put)|\bhttps?\.request)\s*\([\s\S]{0,240}?\bprocess\.env\b"
)

_MD_COMMENT_SMUGGLE_RE = re.compile(
    r"\[//\]:\s*#\s*\([^)]*(?:override|ignore|bypass|safety|exfiltrate|curl|wget|bash|eval|never\s+inform|do\s+not\s+tell)[^)]*\)",
    re.IGNORECASE,
)
_MD_SECRET_EXFIL_RE = re.compile(
    r"(?i)(?:(?:read|cat|print|upload|send|post|transmit|exfiltrate)\b[^\n]{0,140}"
    r"(?:\.env\b|\$[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN)|~/.ssh|id_rsa)[^\n]{0,140}"
    r"(?:https?://|webhook\.site|requestbin|oastify|burpcollaborator)|"
    r"https?://(?:webhook\.site|[^\s/)]*oastify\.com|[^\s/)]*burpcollaborator\.net)/)"
)
_MD_UNSAFE_DELEGATION_RE = re.compile(
    r"(?i)(?:^(?!\s*(?:never|do\s+not|don't)\b)[^\n]*\b"
    r"(?:without\s+(?:asking\s+|user\s+)?confirmation|"
    r"disable\s+(?:all\s+)?sandbox(?:ing|\s+restrictions)?|"
    r"bypass\s+(?:all\s+)?(?:safety|sandbox|approval)\s+(?:checks|restrictions|boundaries))|"
    r"NOPASSWD\s*:\s*ALL)"
)
_MD_SCRIPT_REF_RE = re.compile(r"\b((?:scripts|assets|references)/[A-Za-z0-9_./-]+\.(?:py|sh|bash|js|ts|mjs|ps1))\b")


@dataclass
class AnalyzerHit:
    severity: str
    code: str
    file: str
    message: str
    line: int = 0
    confidence: str = "HIGH"


@dataclass
class FileSignals:
    file: str
    has_encoded_blob: bool = False
    has_decoder: bool = False
    has_dynamic_exec: bool = False
    has_network_fetch: bool = False
    has_file_write: bool = False
    has_dynamic_subprocess: bool = False
    referenced_scripts: set[str] = field(default_factory=set)


def _call_qualname(node: ast.Call, aliases: dict[str, str]) -> str:
    if isinstance(node.func, ast.Name):
        raw = node.func.id
        return aliases.get(raw, raw)
    if isinstance(node.func, ast.Attribute):
        parts: list[str] = [node.func.attr]
        cur: ast.expr = node.func.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            root_name = aliases.get(cur.id, cur.id)
            parts.append(root_name)
            return ".".join(reversed(parts))
        return node.func.attr
    return ""


def _ast_contains_decoder(node: ast.AST, aliases: dict[str, str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            qname = _call_qualname(sub, aliases)
            if any(
                tok in qname
                for tok in ("b64decode", "urlsafe_b64decode", "fromhex", "unhexlify", "decompress", "codecs.decode")
            ):
                return True
    return False


def _is_getattr_exec(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
        attr_arg = node.args[1]
        if isinstance(attr_arg, ast.Constant) and attr_arg.value in ("eval", "exec", "__import__", "system"):
            return True
    return False


def analyze_python_ast(rel: str, text: str, signals: FileSignals) -> list[AnalyzerHit]:
    """Perform bounded AST security inspection on a Python source file."""
    hits: list[AnalyzerHit] = []
    try:
        tree = ast.parse(text, filename=rel)
    except (SyntaxError, ValueError, RecursionError):
        return hits

    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                aliases[bound] = alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                bound = alias.asname or alias.name
                aliases[bound] = f"{mod}.{alias.name}" if mod else alias.name

    has_socket_connect = False
    has_fd_dup = False
    socket_line = 1

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        lineno = getattr(node, "lineno", 1)
        qname = _call_qualname(node, aliases)

        # 1. Dynamic / encoded execution (eval, exec, getattr(__builtins__, 'exec'))
        if qname in ("eval", "exec", "builtins.eval", "builtins.exec") or _is_getattr_exec(node.func):
            signals.has_dynamic_exec = True
            if any(_ast_contains_decoder(arg, aliases) for arg in node.args):
                hits.append(
                    AnalyzerHit(
                        "CRITICAL",
                        "sec-py-encoded-exec",
                        rel,
                        "Python dynamic execution of decoded/obfuscated byte payload",
                        line=lineno,
                        confidence="HIGH",
                    )
                )
            else:
                hits.append(
                    AnalyzerHit(
                        "HIGH",
                        "sec-dynamic-eval",
                        rel,
                        f"Python dynamic code execution via {qname or 'getattr(..., exec/eval)'}()",
                        line=lineno,
                        confidence="HIGH",
                    )
                )

        # 2. Subprocess calls: distinguish shell=True vs dynamic path execution vs safe static list
        if qname in (
            "subprocess.run",
            "subprocess.Popen",
            "subprocess.call",
            "subprocess.check_call",
            "subprocess.check_output",
        ):
            shell_true = False
            for kw in node.keywords:
                if kw.arg == "shell" and (not isinstance(kw.value, ast.Constant) or bool(kw.value.value) is True):
                    shell_true = True
            if shell_true:
                signals.has_dynamic_exec = True
                hits.append(
                    AnalyzerHit(
                        "HIGH",
                        "sec-py-unsafe-subprocess",
                        rel,
                        f"Unsafe subprocess invocation `{qname}(..., shell=True)` allows shell injection",
                        line=lineno,
                        confidence="HIGH",
                    )
                )
            elif node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, (ast.List, ast.Tuple)):
                    # Check if any argument is a non-constant variable (e.g. executing a downloaded file)
                    if any(not isinstance(elt, ast.Constant) for elt in first_arg.elts):
                        signals.has_dynamic_subprocess = True
                elif not isinstance(first_arg, ast.Constant):
                    signals.has_dynamic_subprocess = True

        if qname in ("os.system", "os.popen", "pty.spawn"):
            signals.has_dynamic_exec = True
            hits.append(
                AnalyzerHit(
                    "HIGH",
                    "sec-dynamic-eval",
                    rel,
                    f"Direct shell execution via `{qname}()`",
                    line=lineno,
                    confidence="HIGH",
                )
            )

        # 3. Unsafe deserialization (pickle / marshal)
        if qname in ("pickle.loads", "pickle.load", "marshal.loads", "marshal.load", "_pickle.loads"):
            signals.has_dynamic_exec = True
            hits.append(
                AnalyzerHit(
                    "HIGH",
                    "sec-py-unsafe-deserialization",
                    rel,
                    f"Unsafe binary deserialization via `{qname}()` enables arbitrary code execution",
                    line=lineno,
                    confidence="HIGH",
                )
            )

        # 4. Dynamic imports with non-constant target or risky stdlib modules
        if qname in ("__import__", "builtins.__import__", "importlib.import_module") and node.args:
            arg0 = node.args[0]
            if not isinstance(arg0, ast.Constant) or str(arg0.value) in ("os", "subprocess", "pty", "socket"):
                hits.append(
                    AnalyzerHit(
                        "HIGH",
                        "sec-py-dynamic-import",
                        rel,
                        f"Dynamic module import via `{qname}()`",
                        line=lineno,
                        confidence="MEDIUM",
                    )
                )

        # 5. Track decoder calls, network calls, file writes, socket reverse shells, and credential opens
        if any(tok in qname for tok in ("b64decode", "urlsafe_b64decode", "fromhex", "unhexlify")):
            signals.has_decoder = True

        if any(
            tok in qname
            for tok in ("urlopen", "urlretrieve", "requests.get", "requests.post", "httpx.get", "httpx.post")
        ):
            signals.has_network_fetch = True

        if qname.endswith(("write_bytes", "write_text")) or (
            qname == "open"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and any(m in node.args[1].value for m in ("w", "a", "x"))
        ):
            signals.has_file_write = True

        if qname.endswith(".connect") or qname == "connect":
            has_socket_connect = True
            socket_line = lineno
        if qname in ("os.dup2", "posix.dup2"):
            has_fd_dup = True

        # Check all string constants inside file/path calls for credential store targets
        if qname in ("open", "os.path.expanduser", "Path", "pathlib.Path") or qname.endswith(
            ("read_text", "read_bytes", "expanduser")
        ):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    sval = sub.value.replace("\\", "/")
                    if any(marker in sval for marker in _SENSITIVE_PATH_SUBSTRINGS):
                        hits.append(
                            AnalyzerHit(
                                "HIGH",
                                "sec-credential-harvest",
                                rel,
                                f"Python AST accesses sensitive host credential path ({sval})",
                                line=lineno,
                                confidence="HIGH",
                            )
                        )

    if has_socket_connect and has_fd_dup:
        hits.append(
            AnalyzerHit(
                "CRITICAL",
                "sec-reverse-shell",
                rel,
                "Python socket connection combined with file-descriptor duplication (os.dup2 reverse shell)",
                line=socket_line,
                confidence="HIGH",
            )
        )

    return hits


def analyze_js_ts(rel: str, text: str, signals: FileSignals) -> list[AnalyzerHit]:
    """Inspect JavaScript / TypeScript files for dynamic eval, shell exec, and remote code."""
    hits: list[AnalyzerHit] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        sline = line.strip()
        if sline.startswith("//"):
            continue
        if _JS_DYNAMIC_EVAL_RE.search(line):
            signals.has_dynamic_exec = True
            hits.append(
                AnalyzerHit(
                    "HIGH",
                    "sec-js-dynamic-eval",
                    rel,
                    "JavaScript/TypeScript dynamic code evaluation (`eval` / `new Function` / `vm`)",
                    line=idx,
                    confidence="HIGH",
                )
            )
        if _JS_CHILD_PROC_RE.search(line):
            signals.has_dynamic_exec = True
            hits.append(
                AnalyzerHit(
                    "HIGH",
                    "sec-js-child-process",
                    rel,
                    "JavaScript/TypeScript shell-interpreted child-process execution (`exec` / `execSync`)",
                    line=idx,
                    confidence="HIGH",
                )
            )
        if "atob(" in line or ("Buffer.from(" in line and "base64" in line):
            signals.has_decoder = True
        if "fetch(" in line or "axios." in line or "https.get" in line:
            signals.has_network_fetch = True
        if "writeFileSync" in line or "writeFile(" in line:
            signals.has_file_write = True

    for m in _JS_REMOTE_CODE_RE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        hits.append(
            AnalyzerHit(
                "CRITICAL",
                "sec-js-remote-code",
                rel,
                "JavaScript/TypeScript remote dynamic module import or fetch-to-eval execution",
                line=line_no,
                confidence="HIGH",
            )
        )

    for m in _JS_ENV_EXFIL_RE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        hits.append(
            AnalyzerHit(
                "CRITICAL",
                "sec-env-exfil",
                rel,
                "JavaScript/TypeScript network call transmitting `process.env`",
                line=line_no,
                confidence="HIGH",
            )
        )
    return hits


def analyze_markdown_instructions(rel: str, text: str, signals: FileSignals) -> list[AnalyzerHit]:
    """Inspect Markdown skill instructions for hidden comments, exfil directives, and unsafe delegation."""
    hits: list[AnalyzerHit] = []
    for m in _MD_SCRIPT_REF_RE.finditer(text):
        signals.referenced_scripts.add(m.group(1))

    for idx, line in enumerate(text.splitlines(), start=1):
        if _MD_COMMENT_SMUGGLE_RE.search(line):
            hits.append(
                AnalyzerHit(
                    "HIGH",
                    "sec-md-hidden-comment",
                    rel,
                    "Markdown reference-comment smuggling containing override or execution directives",
                    line=idx,
                    confidence="HIGH",
                )
            )
        if _MD_SECRET_EXFIL_RE.search(line):
            hits.append(
                AnalyzerHit(
                    "CRITICAL",
                    "sec-md-secret-exfil",
                    rel,
                    "Markdown instruction directs agent to exfiltrate secrets or communicate with an exfil endpoint",
                    line=idx,
                    confidence="HIGH",
                )
            )
        if _MD_UNSAFE_DELEGATION_RE.search(line):
            hits.append(
                AnalyzerHit(
                    "HIGH",
                    "sec-md-unsafe-delegation",
                    rel,
                    "Markdown instruction attempts to disable confirmation, sandbox, or safety boundaries",
                    line=idx,
                    confidence="MEDIUM",
                )
            )
    return hits


def _safe_decode_text(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""
    # Check UTF-16LE (PowerShell) if alternating NUL bytes are present
    if len(raw_bytes) >= 8 and raw_bytes[1::2].count(0) >= (len(raw_bytes) // 4):
        try:
            u16 = raw_bytes.decode("utf-16-le", errors="strict")
            if sum(1 for c in u16 if c.isprintable() or c in "\r\n\t") >= int(len(u16) * 0.85):
                return u16
        except UnicodeDecodeError:
            pass
    try:
        u8 = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return ""
    printable = sum(1 for c in u8 if c.isprintable() or c in "\r\n\t")
    if printable < int(len(u8) * 0.85):
        return ""
    return u8


def analyze_encoded_content(rel: str, text: str, signals: FileSignals) -> list[AnalyzerHit]:
    """Bounded, non-executing inspection of Base64, Hex, and PowerShell encoded payloads."""
    hits: list[AnalyzerHit] = []

    for m in _POWERSHELL_ENC_RE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        b64_tok = m.group(1)[:MAX_ENCODED_TOKEN_CHARS]
        decoded_summary = ""
        try:
            padded = b64_tok + ("=" * ((4 - len(b64_tok) % 4) % 4))
            raw = base64.b64decode(padded, validate=False)[:4096]
            decoded_summary = _safe_decode_text(raw)[:80]
        except (binascii.Error, ValueError):
            decoded_summary = ""
        detail = f" (decoded preview: {decoded_summary!r})" if decoded_summary else ""
        signals.has_encoded_blob = True
        hits.append(
            AnalyzerHit(
                "CRITICAL",
                "sec-powershell-encoded",
                rel,
                f"PowerShell `-EncodedCommand` obfuscated execution detected{detail}",
                line=line_no,
                confidence="HIGH",
            )
        )

    checked = 0
    for m in _B64_CANDIDATE_RE.finditer(text):
        if checked >= MAX_ENCODED_CANDIDATES_PER_FILE:
            break
        tok = m.group(1)
        if len(tok) > MAX_ENCODED_TOKEN_CHARS or len(tok) % 4 == 1:
            continue
        checked += 1
        try:
            padded = tok + ("=" * ((4 - len(tok) % 4) % 4))
            raw = base64.b64decode(padded, validate=True)[:4096]
        except (binascii.Error, ValueError):
            continue
        decoded = _safe_decode_text(raw)
        if len(decoded) < 16:
            continue
        signals.has_encoded_blob = True
        if _DECODED_MALICIOUS_RE.search(decoded):
            line_no = text.count("\n", 0, m.start()) + 1
            hits.append(
                AnalyzerHit(
                    "CRITICAL",
                    "sec-encoded-payload",
                    rel,
                    "Base64-encoded malicious command or prompt-injection payload detected",
                    line=line_no,
                    confidence="HIGH",
                )
            )

    hex_checked = 0
    for m in _HEX_CANDIDATE_RE.finditer(text):
        if hex_checked >= MAX_ENCODED_CANDIDATES_PER_FILE:
            break
        htok = m.group(1)
        # Skip 40-char git SHAs and 64-char SHA-256 digests so lockfiles/checksums never false-positive
        if len(htok) in (40, 64, 128):
            continue
        hex_checked += 1
        try:
            raw = bytes.fromhex(htok)[:4096]
        except ValueError:
            continue
        decoded = _safe_decode_text(raw)
        if len(decoded) < 12:
            continue
        signals.has_encoded_blob = True
        if _DECODED_MALICIOUS_RE.search(decoded):
            line_no = text.count("\n", 0, m.start()) + 1
            hits.append(
                AnalyzerHit(
                    "CRITICAL",
                    "sec-encoded-payload",
                    rel,
                    "Hex-encoded malicious command or payload detected",
                    line=line_no,
                    confidence="HIGH",
                )
            )

    return hits


def analyze_cross_file_chains(signals_by_file: dict[str, FileSignals]) -> list[AnalyzerHit]:
    """Correlate multi-stage suspicious behaviors split across multiple files in a skill."""
    hits: list[AnalyzerHit] = []
    blob_files = sorted(f for f, s in signals_by_file.items() if s.has_encoded_blob)
    decoder_files = sorted(f for f, s in signals_by_file.items() if s.has_decoder)
    exec_files = sorted(f for f, s in signals_by_file.items() if s.has_dynamic_exec)

    participating = set(blob_files) | set(decoder_files) | set(exec_files)
    if blob_files and decoder_files and exec_files and len(participating) >= 2:
        anchor = exec_files[0]
        chain_desc = f"payload={blob_files[0]} -> decode={decoder_files[0]} -> exec={exec_files[0]}"
        hits.append(
            AnalyzerHit(
                "HIGH",
                "sec-cross-file-staged-exec",
                anchor,
                f"Multi-file staged payload decode-and-execute chain detected ({chain_desc})",
                line=1,
                confidence="HIGH",
            )
        )

    for md_file, md_sig in sorted(signals_by_file.items()):
        for ref_script in sorted(md_sig.referenced_scripts):
            script_sig = signals_by_file.get(ref_script)
            if script_sig is None:
                continue
            if (
                script_sig.has_network_fetch
                and script_sig.has_file_write
                and (script_sig.has_dynamic_exec or script_sig.has_dynamic_subprocess)
            ):
                hits.append(
                    AnalyzerHit(
                        "HIGH",
                        "sec-cross-file-remote-stage",
                        ref_script,
                        (
                            f"{md_file} instructs execution of {ref_script}, which downloads, writes, "
                            "and executes a second-stage payload"
                        ),
                        line=1,
                        confidence="HIGH",
                    )
                )

    return hits
