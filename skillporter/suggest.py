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

CATALOG_NOTE = (
    "Hand-curated from the upstream repository's public skill listing. Not an endorsement, "
    "not scanned, and not version-pinned: `skillporter add` scans before installing."
)


@dataclass(frozen=True)
class CuratedRecommendation:
    """One curated recommendation backed by a concrete stack signal.

    Third-party entries carry no version, scan result, or risk score: Skillporter has not
    scanned or pinned them. Those facts only exist after `skillporter add` runs the scanner.
    """

    id: str
    title: str
    source: str
    required_any_signals: tuple[str, ...]
    problem_solved: str
    limitations: str = CATALOG_NOTE
    install_cmd: str = ""
    bundled: bool = False


_CURATED_RULES: tuple[CuratedRecommendation, ...] = (
    CuratedRecommendation(
        id="react-best-practices",
        title="Vercel agent skills: React and web best practices",
        source="vercel-labs/agent-skills",
        required_any_signals=("nextjs", "react"),
        problem_solved=(
            "Upstream ships react-best-practices, composition-patterns, web-design-guidelines "
            "and deploy-to-vercel skills. It is general React guidance, not specific to the Next.js App Router."
        ),
        install_cmd="skillporter add vercel-labs/agent-skills --skill react-best-practices",
    ),
    CuratedRecommendation(
        id="playwright-webapp-testing",
        title="Anthropic webapp-testing skill",
        source="anthropics/skills",
        required_any_signals=("playwright",),
        problem_solved="Upstream skill `webapp-testing` for testing local web applications with Playwright.",
        install_cmd="skillporter add anthropics/skills --skill webapp-testing",
    ),
    CuratedRecommendation(
        id="jetbrains-kotlin-java",
        title="JetBrains curated Kotlin and Java skills",
        source="JetBrains/skills",
        required_any_signals=("jvm",),
        problem_solved=(
            "Upstream lists Kotlin, Java and Spring skills such as kotlin-idiomatic-refactorer-spring-aware "
            "and gradle-kotlin-dsl-doctor. It has no Python skills."
        ),
        install_cmd="skillporter inspect JetBrains/skills",
    ),
    CuratedRecommendation(
        id="elastic-elasticsearch",
        title="Official Elastic Elasticsearch skills",
        source="elastic/agent-skills",
        required_any_signals=("elasticsearch",),
        problem_solved=(
            "Upstream lists elasticsearch-query-optimization, elasticsearch-index-design, "
            "elasticsearch-esql and elasticsearch-ingest skills."
        ),
        install_cmd="skillporter inspect elastic/agent-skills",
    ),
    CuratedRecommendation(
        id="multi-agent-self-skill",
        title="Official Skillporter skill",
        source="Shanmukh-l33t/skillporter",
        required_any_signals=("multi-agent", "mcp"),
        problem_solved=(
            "Lets an AI coding agent run Skillporter commands such as status, scan and consolidate preview "
            "on your behalf."
        ),
        limitations="Bundled with this Skillporter release. Write operations still need explicit flags.",
        install_cmd="skillporter self-skill install --harness detected",
        bundled=True,
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

    all_harness_names = sorted(harnesses.HARNESSES)
    recommendations: list[dict[str, object]] = []
    for rule in _CURATED_RULES:
        matched_sigs = [sig for sig in rule.required_any_signals if sig in signal_map]
        if not matched_sigs:
            continue
        if rule.id == "multi-agent-self-skill" and "skillporter" in installed_names:
            continue

        ev_labels = [f"{signal_map[sig]['label']} ({signal_map[sig]['evidence']})" for sig in matched_sigs]
        recommendations.append(
            {
                "id": rule.id,
                "title": rule.title,
                "source": rule.source,
                "version": None,
                "matched_signals": matched_sigs,
                "why_relevant": "Detected " + ", ".join(ev_labels),
                "problem_solved": rule.problem_solved,
                # SKILL.md is a shared format, so any of these harnesses can receive the skill.
                "compatible_harnesses": list(active_h),
                "all_supported_harnesses": all_harness_names,
                "security_scanned": False,
                "risk_score": None,
                "scan_status": "bundled" if rule.bundled else "not scanned (runs on `skillporter add`)",
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
