"""Skillporter Ecosystem Registry Client, Seed Index, and Immutable Packager.

Prepares Generation 2 registry boundaries without adding external dependencies:
  * Built-in curated seed catalog of real, verified open-source skill packages
  * Custom local JSON index or remote HTTP registry support via ``SKILLPORTER_REGISTRY_URL``
  * Deterministic, immutable release archive builder (``pack_skill``) emitting
    ``<name>-<version>.tar.gz`` + ``provenance.json`` with SHA-256 digests.
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .frontmatter import parse_skill
from .security import scan_skill


@dataclass(frozen=True)
class RegistryPackage:
    """Metadata record for a discoverable skill package in the registry."""

    slug: str  # publisher/name
    name: str
    publisher: str
    description: str
    source: str
    version: str = "1.0.0"
    category: str = "general"
    tags: tuple[str, ...] = field(default_factory=tuple)
    verified_harnesses: tuple[str, ...] = field(default_factory=tuple)
    license: str = "MIT"
    homepage: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "name": self.name,
            "publisher": self.publisher,
            "description": self.description,
            "source": self.source,
            "version": self.version,
            "category": self.category,
            "tags": list(self.tags),
            "verified_harnesses": list(self.verified_harnesses),
            "license": self.license,
            "homepage": self.homepage,
        }


SEED_CATALOG: tuple[RegistryPackage, ...] = (
    RegistryPackage(
        slug="Shanmukh-l33t/skillporter",
        name="skillporter",
        publisher="Shanmukh-l33t",
        description=(
            "Diagnose, validate, scan, and synchronize Agent Skills across 19 AI coding "
            "and autonomous harnesses."
        ),
        source="https://github.com/Shanmukh-l33t/skillporter/tree/main/skills/skillporter",
        version="2.0.0",
        category="developer-tools",
        tags=("skills", "package-manager", "diagnostics", "claude-code", "codex", "cursor", "hermes"),
        verified_harnesses=("claude-code", "codex", "cursor", "hermes", "openclaw", "github-copilot", "gemini-cli"),
        homepage="https://github.com/Shanmukh-l33t/skillporter",
    ),
    RegistryPackage(
        slug="anthropics/skills",
        name="anthropic-skills",
        publisher="anthropics",
        description=(
            "Official Anthropic reference collection of Agent Skills "
            "(document processing, web testing, MCP builder)."
        ),
        source="https://github.com/anthropics/skills",
        version="1.0.0",
        category="official-collections",
        tags=("anthropic", "claude-code", "docx", "pdf", "pptx", "xlsx", "mcp"),
        verified_harnesses=("claude-code", "codex", "cursor", "github-copilot", "gemini-cli"),
        license="Apache-2.0",
        homepage="https://github.com/anthropics/skills",
    ),
    RegistryPackage(
        slug="vercel-labs/agent-skills",
        name="vercel-agent-skills",
        publisher="vercel-labs",
        description="Vercel engineering Agent Skills for Next.js, React, deployment workflows, and web performance.",
        source="https://github.com/vercel-labs/agent-skills",
        version="1.0.0",
        category="web-development",
        tags=("nextjs", "react", "vercel", "frontend", "typescript"),
        verified_harnesses=("claude-code", "codex", "cursor", "windsurf", "github-copilot"),
        homepage="https://github.com/vercel-labs/agent-skills",
    ),
    RegistryPackage(
        slug="JetBrains/skills",
        name="jetbrains-skills",
        publisher="JetBrains",
        description="Official JetBrains Junie Agent Skills for JVM, Kotlin, Python, and IDE-assisted refactoring.",
        source="https://github.com/JetBrains/skills",
        version="1.0.0",
        category="coding",
        tags=("jetbrains", "junie", "kotlin", "java", "python", "refactoring"),
        verified_harnesses=("junie", "claude-code", "codex", "cursor"),
        homepage="https://github.com/JetBrains/skills",
    ),
    RegistryPackage(
        slug="OpenHands/extensions",
        name="openhands-extensions",
        publisher="OpenHands",
        description=(
            "Community and official Agent Skills and microagents for autonomous "
            "software engineering in OpenHands."
        ),
        source="https://github.com/OpenHands/extensions",
        version="1.0.0",
        category="autonomous-agents",
        tags=("openhands", "autonomous", "debugging", "github", "ci"),
        verified_harnesses=("openhands", "codex", "claude-code", "cursor"),
        homepage="https://github.com/OpenHands/extensions",
    ),
    RegistryPackage(
        slug="netdata/skills",
        name="netdata-skills",
        publisher="netdata",
        description=(
            "Agent Skills for infrastructure observability, metrics troubleshooting, "
            "and Netdata instrumentation."
        ),
        source="https://github.com/netdata/skills",
        version="1.0.0",
        category="devops",
        tags=("observability", "monitoring", "devops", "linux", "metrics"),
        verified_harnesses=("claude-code", "cursor", "windsurf", "codex", "github-copilot", "gemini-cli"),
        homepage="https://github.com/netdata/skills",
    ),
    RegistryPackage(
        slug="elastic/agent-skills",
        name="elastic-agent-skills",
        publisher="elastic",
        description="Official Elastic Agent Skills for Elasticsearch queries, observability, and security analytics.",
        source="https://github.com/elastic/agent-skills",
        version="1.0.0",
        category="data-and-security",
        tags=("elasticsearch", "security", "siem", "search", "observability"),
        verified_harnesses=("claude-code", "cursor", "codex", "windsurf", "github-copilot", "gemini-cli"),
        homepage="https://github.com/elastic/agent-skills",
    ),
)


def load_catalog(registry_url: str | None = None) -> list[RegistryPackage]:
    """Load the registry catalog from seed entries plus optional local/remote index."""
    packages: dict[str, RegistryPackage] = {p.slug.lower(): p for p in SEED_CATALOG}
    url = registry_url or os.environ.get("SKILLPORTER_REGISTRY_URL", "").strip()
    if not url:
        return list(packages.values())

    try:
        if url.startswith(("http://", "https://")):
            # Bounded read: an unbounded resp.read() lets a hostile registry
            # exhaust memory. Cap at 1 MiB and reject larger payloads outright.
            _MAX_REGISTRY_BYTES = 1 << 20
            with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
                body = resp.read(_MAX_REGISTRY_BYTES + 1)
            if len(body) > _MAX_REGISTRY_BYTES:
                raise ValueError(f"registry payload exceeds {_MAX_REGISTRY_BYTES} bytes; refusing to parse")
            raw = json.loads(body.decode("utf-8"))
        else:
            raw = json.loads(Path(url).expanduser().read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("packages", [])
        for item in items:
            if not isinstance(item, dict) or "slug" not in item or "source" not in item:
                continue
            pkg = RegistryPackage(
                slug=str(item["slug"]),
                name=str(item.get("name", item["slug"].split("/")[-1])),
                publisher=str(item.get("publisher", item["slug"].split("/")[0])),
                description=str(item.get("description", "")),
                source=str(item["source"]),
                version=str(item.get("version", "1.0.0")),
                category=str(item.get("category", "general")),
                tags=tuple(str(t) for t in item.get("tags", ())),
                verified_harnesses=tuple(str(h) for h in item.get("verified_harnesses", ())),
                license=str(item.get("license", "MIT")),
                homepage=str(item.get("homepage", "")),
            )
            packages[pkg.slug.lower()] = pkg
    except Exception:
        pass
    return list(packages.values())


def search_catalog(query: str = "", *, category: str = "", registry_url: str | None = None) -> list[RegistryPackage]:
    """Search packages by keyword across slug, name, description, category, and tags."""
    q = query.strip().lower()
    cat = category.strip().lower()
    results: list[RegistryPackage] = []
    for pkg in load_catalog(registry_url):
        if cat and pkg.category.lower() != cat:
            continue
        if not q:
            results.append(pkg)
            continue
        haystack = " ".join([pkg.slug, pkg.name, pkg.description, pkg.category, *pkg.tags]).lower()
        if all(token in haystack for token in q.split()):
            results.append(pkg)
    return results


def resolve_registry_spec(spec: str, *, registry_url: str | None = None) -> RegistryPackage:
    """Resolve ``publisher/name[@version]`` or ``name`` from the registry catalog."""
    slug_part, _, _ver = spec.strip().partition("@")
    needle = slug_part.lower()
    for pkg in load_catalog(registry_url):
        if pkg.slug.lower() == needle or pkg.name.lower() == needle:
            return pkg
    raise KeyError(f"package {spec!r} not found in registry catalog")


@dataclass
class PackedRelease:
    """Immutable release artifact and provenance manifest."""

    skill_name: str
    version: str
    archive_path: Path
    provenance_path: Path
    archive_sha256: str
    tree_hash: str


def pack_skill(skill_dir: Path, out_dir: Path) -> PackedRelease:
    """Create a deterministic, immutable ``.tar.gz`` skill archive and ``provenance.json``."""
    skill_dir = skill_dir.resolve()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError(f"{skill_dir} does not contain SKILL.md")

    doc = parse_skill(skill_md)
    name = doc.name or skill_dir.name
    meta = doc.frontmatter.get("metadata")
    version = str(meta.get("version", "1.0.0")) if isinstance(meta, dict) else "1.0.0"

    sec_report = scan_skill(skill_dir)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    archive_path = out_dir / f"{name}-{version}.tar.gz"
    provenance_path = out_dir / f"{name}-{version}.provenance.json"

    def _reset_tarinfo(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        ti.uid = 0
        ti.gid = 0
        ti.uname = "root"
        ti.gname = "root"
        ti.mtime = 0
        return ti

    with tarfile.open(archive_path, "w:gz") as tf:
        for fpath in sorted(skill_dir.rglob("*")):
            if any(part in {".git", "__pycache__", ".DS_Store"} for part in fpath.parts):
                continue
            rel = fpath.relative_to(skill_dir).as_posix()
            tf.add(fpath, arcname=f"{name}/{rel}", recursive=False, filter=_reset_tarinfo)

    archive_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    provenance = {
        "schema_version": 1,
        "name": name,
        "version": version,
        "description": doc.description,
        "license": str(doc.frontmatter.get("license", "")),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "archive": archive_path.name,
        "archive_sha256": archive_sha256,
        "tree_hash": sec_report.tree_hash,
        "file_hashes": sec_report.file_hashes,
        "security_assessment": {
            "type": sec_report.assessment_type,
            "passed": sec_report.passed,
            "critical": sec_report.critical_count,
            "high": sec_report.high_count,
            "medium": sec_report.medium_count,
        },
    }
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return PackedRelease(
        skill_name=name,
        version=version,
        archive_path=archive_path,
        provenance_path=provenance_path,
        archive_sha256=archive_sha256,
        tree_hash=sec_report.tree_hash,
    )
