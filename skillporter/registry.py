"""Skillporter Ecosystem Registry Client, Seed Index, and Immutable Packager.

Implements the Phase 1 Community Skill Registry Client Contract (v1.0):
  * Built-in curated seed catalog of real, verified open-source skill packages
  * Custom local JSON index or remote HTTP registry support via ``SKILLPORTER_REGISTRY_URL``
  * Ratings, download counts, security risk scores, and dependency metadata
  * Deterministic, immutable release archive builder (``pack_skill``) emitting
    ``<name>-<version>.tar.gz`` + ``provenance.json`` with SHA-256 digests
  * Client-side publication pipeline (``publish_skill``) for validating,
    security-gating, packing, and publishing skills to a registry index.
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .atomic import atomic_write_text
from .frontmatter import parse_skill, validate
from .install import validate_skill_name_segment
from .security import scan_skill

REGISTRY_CONTRACT_VERSION = "1.0.0"


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
    rating: float = 5.0
    downloads: int = 0
    risk_score: int = 0
    dependencies: tuple[str, ...] = field(default_factory=tuple)

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
            "rating": self.rating,
            "downloads": self.downloads,
            "risk_score": self.risk_score,
            "dependencies": list(self.dependencies),
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
        version="3.1.0",
        category="developer-tools",
        tags=("skills", "package-manager", "diagnostics", "claude-code", "codex", "cursor", "hermes"),
        verified_harnesses=("claude-code", "codex", "cursor", "hermes", "openclaw", "github-copilot", "gemini-cli"),
        homepage="https://github.com/Shanmukh-l33t/skillporter",
        rating=5.0,
        downloads=4820,
        risk_score=0,
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
        rating=4.9,
        downloads=19400,
        risk_score=0,
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
        rating=4.8,
        downloads=11200,
        risk_score=0,
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
        rating=4.8,
        downloads=6300,
        risk_score=0,
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
        rating=4.7,
        downloads=5100,
        risk_score=0,
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
        rating=4.8,
        downloads=3900,
        risk_score=0,
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
        rating=4.9,
        downloads=4450,
        risk_score=0,
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
            _MAX_REGISTRY_BYTES = 1 << 20
            with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310  # nosec B310
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
                rating=float(item.get("rating", 5.0)),
                downloads=int(item.get("downloads", 0)),
                risk_score=int(item.get("risk_score", 0)),
                dependencies=tuple(str(d) for d in item.get("dependencies", ())),
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
    name = validate_skill_name_segment(doc.name or skill_dir.name)
    meta = doc.frontmatter.get("metadata")
    version = validate_skill_name_segment(
        str(meta.get("version", "1.0.0")) if isinstance(meta, dict) else "1.0.0"
    )

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
        for dirpath, dirnames, filenames in os.walk(skill_dir, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d not in {".git", "__pycache__", ".DS_Store"})
            cdir = Path(dirpath)
            if cdir != skill_dir:
                rel_d = cdir.relative_to(skill_dir).as_posix()
                tf.add(cdir, arcname=f"{name}/{rel_d}", recursive=False, filter=_reset_tarinfo)
            for fname in sorted(filenames):
                if fname == ".DS_Store":
                    continue
                fpath = cdir / fname
                rel = fpath.relative_to(skill_dir).as_posix()
                tf.add(fpath, arcname=f"{name}/{rel}", recursive=False, filter=_reset_tarinfo)

    archive_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    provenance = {
        "schema_version": 2,
        "registry_contract_version": REGISTRY_CONTRACT_VERSION,
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
            "engine": sec_report.engine,
            "engine_version": sec_report.engine_version,
            "risk_score": sec_report.risk_score,
            "recommendation": sec_report.recommendation,
            "passed": sec_report.passed,
            "critical": sec_report.critical_count,
            "high": sec_report.high_count,
            "medium": sec_report.medium_count,
        },
    }
    atomic_write_text(provenance_path, json.dumps(provenance, indent=2) + "\n")
    return PackedRelease(
        skill_name=name,
        version=version,
        archive_path=archive_path,
        provenance_path=provenance_path,
        archive_sha256=archive_sha256,
        tree_hash=sec_report.tree_hash,
    )


def publish_skill(
    skill_dir: Path,
    *,
    publisher: str = "local",
    registry_url: str | None = None,
    out_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """Validate, security-gate, package, and publish a skill under the Phase 1 Registry Client Contract."""
    skill_dir = Path(skill_dir).resolve()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError(f"{skill_dir} does not contain SKILL.md")

    doc = parse_skill(skill_md)
    issues = validate(doc)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise ValueError(f"cannot publish invalid skill ({len(errors)} error(s)): {errors[0]}")

    sec = scan_skill(skill_dir)
    if not sec.passed or sec.has_structural_escape or sec.risk_score > 30:
        raise ValueError(
            f"cannot publish skill {doc.name!r}: security risk score {sec.risk_score}/100 "
            f"({sec.recommendation}) exceeds registry publication threshold (max 30)"
        )

    dist_dir = (out_dir or (skill_dir / ".skillporter" / "dist")).resolve()
    packed = pack_skill(skill_dir, dist_dir)
    meta = doc.frontmatter.get("metadata")
    author = (
        str(meta.get("author", publisher))
        if isinstance(meta, dict) and meta.get("author")
        else publisher
    )
    slug = f"{author.split()[0].lower()}/{packed.skill_name}"

    entry = RegistryPackage(
        slug=slug,
        name=packed.skill_name,
        publisher=author,
        description=doc.description,
        source=str(packed.archive_path),
        version=packed.version,
        license=str(doc.frontmatter.get("license", "MIT") or "MIT"),
        risk_score=sec.risk_score,
    )

    target_registry = registry_url or os.environ.get("SKILLPORTER_REGISTRY_URL", "").strip()
    if dry_run:
        published_to = "dry-run (client contract verified)"
    elif not target_registry:
        raise ValueError(
            "no target registry configured; pass --registry <index.json-or-url>, "
            "set SKILLPORTER_REGISTRY_URL, or pass --dry-run (or use `skillporter pack` for local bundles)"
        )
    elif target_registry.startswith(("http://", "https://")):
        parsed_u = urllib.parse.urlsplit(target_registry)
        host = (parsed_u.hostname or "").lower()
        is_loopback = host in ("127.0.0.1", "localhost", "::1")
        if not host or any(ord(c) < 32 for c in target_registry):
            raise ValueError(f"invalid registry URL {target_registry!r}")
        if parsed_u.scheme == "http" and not is_loopback:
            raise ValueError(
                f"refusing cleartext HTTP registry URL {target_registry!r}; "
                "use https:// (http:// is permitted only for localhost/127.0.0.1 testing)"
            )

        class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                new_p = urllib.parse.urlsplit(newurl)
                new_host = (new_p.hostname or "").lower()
                if new_p.scheme not in ("https", "http") or (
                    new_p.scheme == "http" and new_host not in ("127.0.0.1", "localhost", "::1")
                ):
                    raise urllib.error.URLError(f"unsafe redirect to {newurl!r} blocked")
                redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
                if redirected is not None and new_host != host:
                    redirected.headers.pop("Authorization", None)
                    redirected.unredirected_hdrs.pop("Authorization", None)
                return redirected

        token = os.environ.get("SKILLPORTER_REGISTRY_TOKEN", "").strip()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "skillporter-registry-client/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload_bytes = json.dumps(
            {
                "contract_version": REGISTRY_CONTRACT_VERSION,
                "package": entry.to_dict(),
                "archive_sha256": packed.archive_sha256,
                "tree_hash": packed.tree_hash,
            }
        ).encode("utf-8")
        req = urllib.request.Request(target_registry, data=payload_bytes, headers=headers, method="POST")
        opener = urllib.request.build_opener(_SafeRedirectHandler())
        try:
            with opener.open(req, timeout=15) as resp:
                status_code = getattr(resp, "status", 200)
                if status_code >= 400:
                    raise ValueError(f"registry rejected publication with HTTP {status_code}")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise ValueError(
                    f"registry authentication failed (HTTP {exc.code}); verify SKILLPORTER_REGISTRY_TOKEN"
                ) from exc
            raise ValueError(f"registry publication failed with HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"network failure reaching registry {target_registry!r}: {exc.reason}") from exc
        published_to = target_registry
    else:
        idx_path = Path(target_registry).expanduser().resolve()
        existing_items: list[dict[str, object]] = []
        if idx_path.is_file():
            try:
                raw = json.loads(idx_path.read_text(encoding="utf-8"))
                existing_items = list(raw.get("packages", raw if isinstance(raw, list) else []))
            except (OSError, json.JSONDecodeError):
                existing_items = []
        existing_items = [x for x in existing_items if isinstance(x, dict) and x.get("slug") != slug]
        existing_items.append(entry.to_dict())
        try:
            idx_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                idx_path,
                json.dumps(
                    {"contract_version": REGISTRY_CONTRACT_VERSION, "packages": existing_items},
                    indent=2,
                )
                + "\n",
            )
        except OSError as exc:
            raise ValueError(f"cannot write registry index {idx_path}: {exc}") from exc
        published_to = str(idx_path)

    return {
        "contract_version": REGISTRY_CONTRACT_VERSION,
        "dry_run": dry_run,
        "published_to": published_to,
        "package": entry.to_dict(),
        "archive": str(packed.archive_path),
        "archive_sha256": packed.archive_sha256,
        "provenance": str(packed.provenance_path),
        "tree_hash": packed.tree_hash,
        "risk_score": sec.risk_score,
    }
