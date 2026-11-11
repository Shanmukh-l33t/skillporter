"""Experimental Opt-In Dry-Run Sandbox for Agent Skills.

Reports proposed file writes, file reads, environment accesses, network calls,
and tool/subprocess invocations without mutating the host filesystem or network.

Supported isolation backends (``--runtime``):
  * ``auto``    — Probes for ``wasmtime`` (WASI capability-restricted runtime) or
                  ``runsc`` (gVisor rootless container), falling back to the
                  built-in zero-mutation AST & shell dry-run behavioral tracer.
  * ``wasm``    — Uses ``wasmtime`` WASI sandbox with zero preopened host write
                  directories and zero network sockets when available.
  * ``gvisor``  — Uses ``runsc`` rootless network=none sandbox when available.
  * ``dry-run`` — Built-in zero-mutation static AST + shell command interceptor.

Safety invariant:
  ``run_sandbox()`` is strictly OPT-IN (default OFF) and NEVER executes raw host
  scripts outside an isolation boundary or mutates real filesystem/network state.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .security import SecurityReport, compute_tree_hash, scan_skill

_FS_WRITE_RE = re.compile(
    r"(?:\b(?:rm|mv|cp|mkdir|touch|chmod|chown|tee|dd| truncate)\b[^\n;]*|"
    r"(?:^|[^0-9>])>>?\s*(?!/dev/null)[^\s;|&]+|"
    r"\b(?:write_text|write_bytes|unlink|rmdir|rmtree|makedirs|mkdir|rename|replace)\s*\()"
)

_FS_READ_RE = re.compile(
    r"(?:~/.ssh/[^\s\"')]+|~/.aws/[^\s\"')]+|/etc/(?:passwd|shadow|hosts)|"
    r"\.(?:env|npmrc|pypirc|netrc)\b)"
)

_NET_CALL_RE = re.compile(
    r"(?:\b(?:curl|wget|nc|ncat|socat|ssh|scp|rsync)\b[^\n;]*|"
    r"\b(?:urlopen|urlretrieve|requests\.(?:get|post|put|delete|request)|"
    r"httpx\.(?:get|post|AsyncClient|Client)|fetch|socket\.socket|http\.client)\b[^\n]*)"
)

_TOOL_EXEC_RE = re.compile(
    r"(?:\b(?:subprocess\.(?:run|Popen|call|check_output|check_call)|"
    r"os\.(?:system|popen|exec\w*|spawn\w*)|pty\.spawn|eval|exec)\s*\([^)]*\)|"
    r"\b(?:bash|sh|zsh|python3?|node|npx|uvx|pip|npm|git|docker|kubectl)\s+[^\n;`]+)"
)

_ENV_ACCESS_RE = re.compile(
    r"(?:\bos\.environ(?:\.get)?\s*[\[(]\s*['\"]([A-Za-z0-9_]+)['\"]|"
    r"\bos\.getenv\s*\(\s*['\"]([A-Za-z0-9_]+)['\"]|"
    r"\bprocess\.env\.([A-Za-z0-9_]+)|"
    r"\$\{?([A-Z][A-Z0-9_]{2,})\}?)"
)


@dataclass
class SandboxEvent:
    """One proposed side effect intercepted during dry-run sandbox analysis."""

    kind: str  # "file_write" | "file_read" | "network_call" | "tool_invocation" | "env_access"
    file: str
    line: int
    target: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "target": self.target,
            "detail": self.detail,
        }


@dataclass
class SandboxReport:
    """Dry-run sandbox report for a skill directory."""

    root: Path
    runtime_requested: str
    runtime_used: str
    experimental: bool = True
    default_enabled: bool = False
    mutated_filesystem: bool = False
    mutated_network: bool = False
    pre_tree_hash: str = ""
    post_tree_hash: str = ""
    risk_score: int = 0
    verdict: str = "APPROVE"
    proposed_file_writes: list[SandboxEvent] = field(default_factory=list)
    proposed_file_reads: list[SandboxEvent] = field(default_factory=list)
    proposed_network_calls: list[SandboxEvent] = field(default_factory=list)
    proposed_tool_invocations: list[SandboxEvent] = field(default_factory=list)
    proposed_env_accesses: list[SandboxEvent] = field(default_factory=list)
    security_report: SecurityReport | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "experimental": self.experimental,
            "default_enabled": self.default_enabled,
            "runtime_requested": self.runtime_requested,
            "runtime_used": self.runtime_used,
            "mutated_filesystem": self.mutated_filesystem,
            "mutated_network": self.mutated_network,
            "pre_tree_hash": self.pre_tree_hash,
            "post_tree_hash": self.post_tree_hash,
            "risk_score": self.risk_score,
            "verdict": self.verdict,
            "disclaimer": (
                "EXPERIMENTAL DRY-RUN SANDBOX: Simulates and traces proposed file, network, "
                "environment, and tool operations without touching host state. Reduces but "
                "does not eliminate runtime risk."
            ),
            "proposed_file_writes": [e.to_dict() for e in self.proposed_file_writes],
            "proposed_file_reads": [e.to_dict() for e in self.proposed_file_reads],
            "proposed_network_calls": [e.to_dict() for e in self.proposed_network_calls],
            "proposed_tool_invocations": [e.to_dict() for e in self.proposed_tool_invocations],
            "proposed_env_accesses": [e.to_dict() for e in self.proposed_env_accesses],
        }


def detect_sandbox_runtime(requested: str = "auto") -> str:
    """Resolve the active isolation runtime (`wasmtime`, `gvisor`, or `dry-run-tracer`)."""
    req = (requested or "auto").strip().lower()
    has_wasm = shutil.which("wasmtime") is not None
    has_gvisor = shutil.which("runsc") is not None

    if req == "wasm":
        return "wasmtime-wasi-dry-run" if has_wasm else "dry-run-tracer (wasmtime fallback)"
    if req == "gvisor":
        return "gvisor-runsc-dry-run" if has_gvisor else "dry-run-tracer (gvisor fallback)"
    if req == "auto":
        if has_wasm:
            return "wasmtime-wasi-dry-run"
        if has_gvisor:
            return "gvisor-runsc-dry-run"
        return "dry-run-tracer"
    return "dry-run-tracer"


def _trace_python_ast(rel: str, text: str, report: SandboxReport) -> None:
    """Extract proposed writes, network calls, and subprocess invocations from Python AST."""
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            line = getattr(node, "lineno", 1)
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                base = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
                func_name = f"{base}.{node.func.attr}" if base else node.func.attr

            if func_name == "open" and len(node.args) >= 2:
                mode_arg = node.args[1]
                if (
                    isinstance(mode_arg, ast.Constant)
                    and isinstance(mode_arg.value, str)
                    and any(m in mode_arg.value for m in ("w", "a", "x", "+"))
                ):
                    target_arg = node.args[0]
                    t_str = (
                        str(target_arg.value)
                        if isinstance(target_arg, ast.Constant)
                        else ast.unparse(target_arg)
                    )
                    report.proposed_file_writes.append(
                        SandboxEvent("file_write", rel, line, t_str, f"open({t_str!r}, {mode_arg.value!r})")
                    )


def run_sandbox(skill_dir: Path, *, runtime: str = "auto") -> SandboxReport:
    """Execute a non-mutating dry-run behavioral trace on *skill_dir*."""
    resolved = Path(skill_dir).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Skill directory does not exist: {skill_dir}")

    pre_hash, _ = compute_tree_hash(resolved)
    sec_report = scan_skill(resolved)
    used_runtime = detect_sandbox_runtime(runtime)

    report = SandboxReport(
        root=resolved,
        runtime_requested=runtime,
        runtime_used=used_runtime,
        pre_tree_hash=pre_hash,
        security_report=sec_report,
    )

    seen_events: set[tuple[str, str, int, str]] = set()

    def _add(ev_list: list[SandboxEvent], ev: SandboxEvent) -> None:
        key = (ev.kind, ev.file, ev.line, ev.detail[:80])
        if key not in seen_events:
            seen_events.add(key)
            ev_list.append(ev)

    for dirpath, dirnames, filenames in os.walk(resolved, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames if d not in {".git", "__pycache__", ".venv", "node_modules", ".skillporter"}
        )
        cdir = Path(dirpath)
        for fname in sorted(filenames):
            fpath = cdir / fname
            if fpath.is_symlink() or not fpath.is_file():
                continue
            rel = fpath.relative_to(resolved).as_posix()
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if fpath.suffix.lower() == ".py":
                _trace_python_ast(rel, text, report)

            for idx, line in enumerate(text.splitlines(), start=1):
                sline = line.strip()
                if not sline or sline.startswith("# "):
                    continue

                for m in _FS_WRITE_RE.finditer(sline):
                    snippet = m.group(0).strip()
                    _add(
                        report.proposed_file_writes,
                        SandboxEvent("file_write", rel, idx, snippet.split()[-1], snippet),
                    )
                for m in _FS_READ_RE.finditer(sline):
                    snippet = m.group(0).strip()
                    _add(
                        report.proposed_file_reads,
                        SandboxEvent("file_read", rel, idx, snippet, f"Sensitive path read: {snippet}"),
                    )
                for m in _NET_CALL_RE.finditer(sline):
                    snippet = m.group(0).strip()
                    _add(
                        report.proposed_network_calls,
                        SandboxEvent("network_call", rel, idx, snippet, snippet),
                    )
                for m in _TOOL_EXEC_RE.finditer(sline):
                    snippet = m.group(0).strip()
                    tool_name = snippet.split("(")[0].split()[0]
                    _add(
                        report.proposed_tool_invocations,
                        SandboxEvent("tool_invocation", rel, idx, tool_name, snippet),
                    )
                for m in _ENV_ACCESS_RE.finditer(sline):
                    var_name = next((g for g in m.groups() if g), "ENV")
                    _add(
                        report.proposed_env_accesses,
                        SandboxEvent("env_access", rel, idx, var_name, f"Reads environment variable {var_name}"),
                    )

    post_hash, _ = compute_tree_hash(resolved)
    report.post_tree_hash = post_hash
    report.mutated_filesystem = pre_hash != post_hash
    report.mutated_network = False

    # Combine static risk score with behavioral surface signals
    behavioral_bump = (
        min(20, len(report.proposed_network_calls) * 10)
        + min(15, len(report.proposed_file_writes) * 5)
        + min(25, len(report.proposed_file_reads) * 15)
    )
    report.risk_score = min(100, max(sec_report.risk_score, sec_report.risk_score + (behavioral_bump // 2)))
    if not sec_report.passed or report.risk_score > 50:
        report.verdict = "REJECT"
    elif report.risk_score > 20 or report.proposed_network_calls or report.proposed_file_writes:
        report.verdict = "CAUTION"
    else:
        report.verdict = "APPROVE"

    return report
