"""Smart Local-First Project Skill Recommendation Engine (`skillporter suggest`).

Inspects repository manifests, frameworks, databases, test runners, and CI
configuration locally (100% offline, zero data uploaded) and recommends high-signal,
security-graded skills with concrete evidence explaining *why* each skill fits.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import harnesses
from .diagnose import diagnose
from .instructions import discover_instruction_files
from .manifest import load_manifest


@dataclass(frozen=True)
class CuratedRecommendation:
    """One curated skill recommendation rule backed by concrete stack signals."""

    id: str
    title: str
    source: str
    version: str
    required_any_signals: tuple[str, ...]
    problem_solved: str
    harnesses: tuple[str, ...]
    security_scanned: bool = True
    risk_score: int = 0
    limitations: str = "Upstream repository requires static security scan on install (`skillporter add`)."
    install_cmd: str = ""


_CURATED_RULES: tuple[CuratedRecommendation, ...] = (
    CuratedRecommendation(
        id="nextjs-react",
        title="Vercel Next.js & React Engineering Skills",
        source="vercel-labs/agent-skills",
        version="1.0.0",
        required_any_signals=("nextjs", "react"),
        problem_solved=(
            "App Router server/client boundary conventions, data fetching patterns, "
            "and React rendering performance."
        ),
        harnesses=("claude-code", "codex", "cursor", "windsurf", "github-copilot", "gemini-cli"),
        risk_score=0,
        install_cmd="skillporter add vercel-labs/agent-skills",
    ),
    CuratedRecommendation(
        id="prisma-db",
        title="Prisma Schema & Safe Migration Workflow",
        source="anthropics/skills",
        version="1.0.0",
        required_any_signals=("prisma", "postgresql"),
        problem_solved=(
            "Zero-downtime schema migrations, relation indexing, and query N+1 prevention "
            "for Prisma and PostgreSQL."
        ),
        harnesses=("claude-code", "codex", "cursor", "github-copilot", "gemini-cli"),
        risk_score=0,
        limitations="Multi-skill repository; pass `--skill <name>` after `skillporter inspect anthropics/skills`.",
        install_cmd="skillporter inspect anthropics/skills",
    ),
    CuratedRecommendation(
        id="playwright-e2e",
        title="Playwright End-to-End Web Testing",
        source="anthropics/skills",
        version="1.0.0",
        required_any_signals=("playwright", "cypress"),
        problem_solved="Deterministic browser locator selection, trace debugging, and flake-free E2E test authoring.",
        harnesses=("claude-code", "codex", "cursor", "github-copilot", "gemini-cli"),
        risk_score=0,
        install_cmd="skillporter add anthropics/skills --skill webapp-testing",
    ),
    CuratedRecommendation(
        id="docker-devops",
        title="Container & Infrastructure Observability Skills",
        source="netdata/skills",
        version="1.0.0",
        required_any_signals=("docker", "kubernetes", "terraform"),
        problem_solved=(
            "Multi-stage container hardening, Linux resource bottleneck triage, "
            "and infrastructure observability."
        ),
        harnesses=("claude-code", "codex", "cursor", "windsurf", "github-copilot", "gemini-cli"),
        risk_score=0,
        install_cmd="skillporter add netdata/skills",
    ),
    CuratedRecommendation(
        id="python-engineering",
        title="Python Packaging, Pytest & Refactoring Skills",
        source="JetBrains/skills",
        version="1.0.0",
        required_any_signals=("python", "fastapi", "django", "pytest", "jvm"),
        problem_solved="Type-safe refactoring, test-first pytest workflows, and clean module boundaries.",
        harnesses=("junie", "claude-code", "codex", "cursor"),
        risk_score=0,
        install_cmd="skillporter add JetBrains/skills",
    ),
    CuratedRecommendation(
        id="ci-autonomous",
        title="CI/CD Failure Diagnosis & Autonomous Debugging",
        source="OpenHands/extensions",
        version="1.0.0",
        required_any_signals=("github-actions",),
        problem_solved="Automated GitHub Actions workflow failure reproduction and pull-request validation.",
        harnesses=("openhands", "codex", "claude-code", "cursor"),
        risk_score=0,
        install_cmd="skillporter add OpenHands/extensions",
    ),
    CuratedRecommendation(
        id="search-security",
        title="Elasticsearch, Observability & Security Analytics",
        source="elastic/agent-skills",
        version="1.0.0",
        required_any_signals=("elasticsearch",),
        problem_solved="Query optimization, index mapping validation, and security log triage.",
        harnesses=("claude-code", "cursor", "codex", "windsurf", "github-copilot", "gemini-cli"),
        risk_score=0,
        install_cmd="skillporter add elastic/agent-skills",
    ),
    CuratedRecommendation(
        id="multi-agent-self-skill",
        title="Official Skillporter Multi-Agent Control Skill",
        source="Shanmukh-l33t/skillporter",
        version="3.1.0",
        required_any_signals=("multi-agent", "mcp"),
        problem_solved=(
            "Lets AI coding agents inspect, synchronize, security-scan, and consolidate "
            "skills and instructions directly."
        ),
        harnesses=("claude-code", "codex", "cursor", "hermes", "openclaw", "github-copilot", "gemini-cli"),
        risk_score=0,
        limitations="Write operations require confirmation or explicit flags.",
        install_cmd="skillporter self-skill install --harness detected",
    ),
)


def detect_project_signals(root: Path) -> list[dict[str, str]]:
    """Inspect local project manifests and configuration files to identify the tech stack."""
    root = Path(root).resolve()
    signals: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(sig: str, label: str, evidence: str) -> None:
        if sig not in seen:
            seen.add(sig)
            signals.append({"signal": sig, "label": label, "evidence": evidence})

    pkg_json = root / "package.json"
    if pkg_json.is_file():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            pkg = {}
        if isinstance(pkg, dict):
            deps = {}
            for sec in ("dependencies", "devDependencies", "peerDependencies"):
                sub = pkg.get(sec)
                if isinstance(sub, dict):
                    deps.update(sub)
            if "next" in deps:
                _add("nextjs", "Next.js", "package.json (next)")
            if "react" in deps:
                _add("react", "React", "package.json (react)")
            if "prisma" in deps or "@prisma/client" in deps:
                _add("prisma", "Prisma", "package.json (@prisma/client)")
            if "@playwright/test" in deps or "playwright" in deps:
                _add("playwright", "Playwright", "package.json (@playwright/test)")
            if "cypress" in deps:
                _add("cypress", "Cypress", "package.json (cypress)")
            if "@elastic/elasticsearch" in deps:
                _add("elasticsearch", "Elasticsearch", "package.json (@elastic/elasticsearch)")
            if "@modelcontextprotocol/sdk" in deps:
                _add("mcp", "Model Context Protocol", "package.json (@modelcontextprotocol/sdk)")

    prisma_schema = root / "prisma" / "schema.prisma"
    if prisma_schema.is_file():
        _add("prisma", "Prisma", "prisma/schema.prisma")
        stxt = prisma_schema.read_text(encoding="utf-8", errors="replace").lower()
        if "postgresql" in stxt or "postgres" in stxt:
            _add("postgresql", "PostgreSQL", "prisma/schema.prisma (provider = postgresql)")

    pyproj = root / "pyproject.toml"
    if pyproj.is_file():
        ptxt = pyproj.read_text(encoding="utf-8", errors="replace").lower()
        _add("python", "Python", "pyproject.toml")
        if "fastapi" in ptxt:
            _add("fastapi", "FastAPI", "pyproject.toml (fastapi)")
        if "django" in ptxt:
            _add("django", "Django", "pyproject.toml (django)")
        if "pytest" in ptxt:
            _add("pytest", "pytest", "pyproject.toml (pytest)")
        if "psycopg" in ptxt or "asyncpg" in ptxt:
            _add("postgresql", "PostgreSQL", "pyproject.toml (postgres driver)")

    req_txt = root / "requirements.txt"
    if req_txt.is_file():
        rtxt = req_txt.read_text(encoding="utf-8", errors="replace").lower()
        _add("python", "Python", "requirements.txt")
        if "fastapi" in rtxt:
            _add("fastapi", "FastAPI", "requirements.txt (fastapi)")
        if "pytest" in rtxt:
            _add("pytest", "pytest", "requirements.txt (pytest)")
        if "elasticsearch" in rtxt:
            _add("elasticsearch", "Elasticsearch", "requirements.txt (elasticsearch)")

    if (root / "pom.xml").is_file() or any(root.glob("build.gradle*")):
        _add("jvm", "JVM / Kotlin / Java", "build.gradle / pom.xml")

    for df in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml"):
        if (root / df).is_file():
            _add("docker", "Docker", df)
            dtxt = (root / df).read_text(encoding="utf-8", errors="replace").lower()
            if re.search(r"\bpostgres(?::|\s|$)", dtxt):
                _add("postgresql", "PostgreSQL", f"{df} (postgres image)")
            break

    if any(root.glob("*.tf")) or (root / "terraform").is_dir():
        _add("terraform", "Terraform", "*.tf / terraform/")

    gh_wf = root / ".github" / "workflows"
    if gh_wf.is_dir() and any(gh_wf.glob("*.y*ml")):
        _add("github-actions", "GitHub Actions", ".github/workflows/")

    if (root / ".mcp.json").is_file() or (root / "server.json").is_file():
        _add("mcp", "Model Context Protocol", "server.json / .mcp.json")

    inst_files = discover_instruction_files(root)
    if len(inst_files) >= 2:
        _add("multi-agent", "Multi-Agent Instructions", f"{len(inst_files)} instruction files found")

    return signals


def recommend_skills_for_project(
    root: Path,
    *,
    preferred_harnesses: list[str] | None = None,
) -> dict[str, object]:
    """Generate ranked, evidence-backed local skill recommendations for *root*."""
    root = Path(root).resolve()
    stack = detect_project_signals(root)
    signal_map = {item["signal"]: item for item in stack}

    diag = diagnose(root, scope="project")
    installed_names = {s.lower() for s in diag.skill_names}

    manifest = load_manifest(root)
    if preferred_harnesses:
        active_h = [harnesses.get(h).name for h in preferred_harnesses]
    elif manifest and manifest.harnesses:
        active_h = [harnesses.get(h).name for h in manifest.harnesses if h in harnesses.HARNESSES]
    else:
        det = [d.harness.name for d in harnesses.detect_harnesses(root) if d.installed]
        active_h = det or ["claude-code", "codex", "cursor"]

    recommendations: list[dict[str, object]] = []
    for rule in _CURATED_RULES:
        matched_sigs = [s for s in rule.required_any_signals if s in signal_map]
        if not matched_sigs:
            continue
        if rule.id == "multi-agent-self-skill" and "skillporter" in installed_names:
            continue

        ev_labels = [f"{signal_map[s]['label']} ({signal_map[s]['evidence']})" for s in matched_sigs]
        compat_active = [h for h in rule.harnesses if h in active_h] or list(rule.harnesses)

        recommendations.append(
            {
                "id": rule.id,
                "title": rule.title,
                "source": rule.source,
                "version": rule.version,
                "matched_signals": matched_sigs,
                "why_relevant": "Detected " + ", ".join(ev_labels),
                "problem_solved": rule.problem_solved,
                "compatible_harnesses": compat_active,
                "all_supported_harnesses": list(rule.harnesses),
                "security_scanned": rule.security_scanned,
                "risk_score": rule.risk_score,
                "limitations": rule.limitations,
                "install_command": rule.install_cmd or f"skillporter add {rule.source}",
            }
        )

    return {
        "root": str(root),
        "local_only": True,
        "detected_stack": stack,
        "active_harnesses": active_h,
        "recommendations": recommendations,
    }
