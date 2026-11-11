"""Universal Source Resolution Engine.

Resolves skill packages from:
  * Local directories (single skill or multi-skill repository)
  * Local ZIP / tar.gz archives (with strict Zip-Slip and symlink escape protection)
  * GitHub shorthand: ``owner/repo``, ``github:owner/repo``, ``owner/repo/subpath@ref``
  * Full GitHub tree URLs: ``https://github.com/owner/repo/tree/<ref>/<subpath>``
  * Arbitrary Git URLs: ``https://...``, ``git@...``, ``file://...``
  * Registry packages: ``registry:publisher/name@version``

Security invariant: Source resolution NEVER executes scripts inside fetched
repositories or archives.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import discover

_GITHUB_SHORTHAND_RE = re.compile(
    r"^(?:github:)?(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)"
    r"(?:/(?P<subpath>[^@#]+))?(?:[@#](?P<ref>[A-Za-z0-9_./-]+))?$"
)

_GITHUB_TREE_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)"
    r"(?:/tree/(?P<ref>[^/]+)(?:/(?P<subpath>.+))?)?/?$"
)


class SourceError(RuntimeError):
    """Raised when a skill source cannot be safely resolved or extracted."""


@dataclass
class ResolvedSource:
    """Result of resolving a local or remote skill specifier."""

    raw_spec: str
    kind: str  # "local" | "archive" | "github" | "git" | "registry"
    canonical_source: str
    root_dir: Path
    skill_dirs: list[Path] = field(default_factory=list)
    resolved_commit: str = ""
    ref: str = ""
    temp_dir: Path | None = None

    def cleanup(self) -> None:
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)


def _find_skill_dirs(search_root: Path) -> list[Path]:
    """Find all skill directories containing SKILL.md under *search_root*."""
    if (search_root / "SKILL.md").is_file():
        return [search_root]
    found: list[Path] = []
    seen_dirs: set[Path] = set()
    for skill_md in discover(search_root):
        parent = skill_md.parent.resolve()
        if parent not in seen_dirs:
            seen_dirs.add(parent)
            found.append(parent)
    return found


#: A git ref must look like a ref. Anything starting with "-" would be parsed by
#: git as an option (argument injection): ``--upload-pack=`` alone is enough to
#: execute a command on some git versions.
_SAFE_GIT_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")


def _validate_git_ref(ref: str) -> str:
    """Return *ref* if it is a plausible git ref, else raise SourceError."""
    if not ref:
        return ref
    if not _SAFE_GIT_REF.match(ref) or ".." in ref:
        raise SourceError(
            f"invalid git ref {ref!r}: refs may contain only letters, digits, '.', '_', '/' "
            "and '-' (not as the first character)"
        )
    return ref


def _unsafe_member_name(name: str) -> str:
    """Return a reason string when an archive member name is unsafe, else "".

    Both separators are normalised before checking: on POSIX ``Path("..\\..\\x").parts``
    yields a single opaque component (backslash is a valid filename character), so a
    Windows-style traversal entry slips past a naive ``.. in Path(name).parts`` check.
    The same archive is traversal on Windows, so the guard must be platform-independent.
    """
    raw = name.replace("\\", "/")
    if raw.startswith("/") or raw.startswith("//"):
        return "absolute path"
    if len(raw) > 1 and raw[1] == ":":  # C:\ or C:/
        return "drive-qualified path"
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if ".." in parts:
        return "path traversal"
    if "\x00" in raw:
        return "NUL byte in name"
    return ""


def safe_extract_zip(archive_path: Path, dest_dir: Path) -> Path:
    """Extract a ZIP archive into *dest_dir*, rejecting path traversal (Zip-Slip) and symlinks."""
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            reason = _unsafe_member_name(name)
            if reason:
                raise SourceError(f"unsafe archive path {name!r} in {archive_path} ({reason} rejected)")
            # UNIX symlink mode check (0o120000 in external_attr >> 16)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise SourceError(f"unsafe symlink entry {name!r} in {archive_path} (archive symlinks rejected)")
            target = (dest_dir / name).resolve()
            try:
                target.relative_to(dest_dir)
            except ValueError as exc:
                raise SourceError(f"archive member {name!r} escapes destination directory") from exc
        # Extract from the same ZipFile we validated instead of zf.extractall():
        # re-reading the archive closes the window where a swapped file could
        # carry members the validation loop never saw.
        for info in zf.infolist():
            target = (dest_dir / info.filename).resolve()
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info.filename) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return dest_dir


def safe_extract_tar(archive_path: Path, dest_dir: Path) -> Path:
    """Extract a tar archive into *dest_dir*, rejecting path traversal and symlinks/devices."""
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:*") as tf:
        for member in tf.getmembers():
            reason = _unsafe_member_name(member.name)
            if reason:
                raise SourceError(f"unsafe tar path {member.name!r} in {archive_path} ({reason} rejected)")
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise SourceError(
                    f"unsafe special/symlink entry {member.name!r} in {archive_path} (rejected by security policy)"
                )
            target = (dest_dir / member.name).resolve()
            try:
                target.relative_to(dest_dir)
            except ValueError as exc:
                raise SourceError(f"tar member {member.name!r} escapes destination directory") from exc
        # Extract only regular files/directories from this validated handle;
        # tf.extractall() would re-open the archive and re-trust its members.
        for member in tf.getmembers():
            target = (dest_dir / member.name).resolve()
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            with src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if member.mode:
                with contextlib.suppress(OSError):
                    os.chmod(target, member.mode & 0o777)
    return dest_dir


def _git_clone(url: str, ref: str = "", subpath: str = "", raw_spec: str = "", kind: str = "git") -> ResolvedSource:
    ref = _validate_git_ref(ref)
    tmp = Path(tempfile.mkdtemp(prefix="skillporter-src-"))
    repo_dir = tmp / "repo"
    try:
        cmd = ["git", "clone", "--quiet"]
        # Use shallow clone when ref is empty or looks like branch/tag, full clone for commit SHA
        is_sha = bool(ref and re.fullmatch(r"[0-9a-fA-F]{7,40}", ref))
        if not is_sha:
            cmd.extend(["--depth", "1"])
            if ref:
                cmd.extend(["--branch", ref])
        # "--" terminates option parsing: a URL can never be read as a flag.
        cmd.extend(["--", url, str(repo_dir)])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if proc.returncode != 0:
            raise SourceError(f"git clone failed for {url!r}: {(proc.stderr or proc.stdout).strip()}")

        if is_sha:
            chk = subprocess.run(
                ["git", "-C", str(repo_dir), "checkout", "--quiet", ref],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if chk.returncode != 0:
                raise SourceError(f"git checkout {ref!r} failed: {(chk.stderr or chk.stdout).strip()}")

        rev = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        commit_sha = rev.stdout.strip() if rev.returncode == 0 else ""

        target_root = repo_dir
        if subpath:
            clean_sub = subpath.strip("/")
            if ".." in Path(clean_sub).parts:
                raise SourceError(f"unsafe subpath {subpath!r}")
            target_root = (repo_dir / clean_sub).resolve()
            try:
                target_root.relative_to(repo_dir.resolve())
            except ValueError as exc:
                raise SourceError(f"subpath {subpath!r} escapes repository root") from exc
            if not target_root.exists():
                raise SourceError(f"subpath {subpath!r} not found in {url}")

        skills = _find_skill_dirs(target_root)
        if not skills:
            raise SourceError(f"no SKILL.md found in {raw_spec or url}")

        return ResolvedSource(
            raw_spec=raw_spec or url,
            kind=kind,
            canonical_source=url + (f"#{subpath}" if subpath else ""),
            root_dir=target_root,
            skill_dirs=skills,
            resolved_commit=commit_sha,
            ref=ref,
            temp_dir=tmp,
        )
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def resolve_source(spec: str, *, base_dir: Path | None = None, ref_override: str = "") -> ResolvedSource:
    """Resolve a local path, archive, GitHub shorthand, Git URL, or registry specifier."""
    spec = spec.strip()
    base = (base_dir or Path.cwd()).resolve()

    if spec.startswith("registry:"):
        from .registry import resolve_registry_spec

        reg_entry = resolve_registry_spec(spec[len("registry:"):])
        return resolve_source(reg_entry.source, base_dir=base, ref_override=ref_override or reg_entry.version)

    # 1. Check GitHub tree URL: https://github.com/owner/repo/tree/ref/subpath
    m_url = _GITHUB_TREE_URL_RE.match(spec)
    if m_url:
        owner = m_url.group("owner")
        repo = m_url.group("repo")
        if repo.endswith(".git"):
            repo = repo[:-4]
        ref = ref_override or (m_url.group("ref") or "")
        subpath = m_url.group("subpath") or ""
        git_url = f"https://github.com/{owner}/{repo}.git"
        return _git_clone(git_url, ref=ref, subpath=subpath, raw_spec=spec, kind="github")

    # 2. Check arbitrary git URL (https://, http://, git@, file://) before Path()
    # so file:// URIs on Windows are never misinterpreted as relative drive paths.
    if spec.startswith(("https://", "http://", "git@", "file://")):
        url_part, _, frag_ref = spec.partition("@") if not spec.startswith("git@") else (spec, "", "")
        if "#" in url_part:
            url_part, _, frag_ref = url_part.partition("#")
        return _git_clone(url_part, ref=ref_override or frag_ref, raw_spec=spec, kind="git")

    # 3. Check if spec is an existing local path (directory, SKILL.md file, or archive)
    candidate = Path(spec).expanduser()
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()

    if candidate.exists():
        if candidate.is_file() and candidate.name == "SKILL.md":
            candidate = candidate.parent
        if candidate.is_file():
            lower_name = candidate.name.lower()
            tmp = Path(tempfile.mkdtemp(prefix="skillporter-archive-"))
            try:
                if lower_name.endswith(".zip"):
                    safe_extract_zip(candidate, tmp)
                elif lower_name.endswith((".tar.gz", ".tgz", ".tar")):
                    safe_extract_tar(candidate, tmp)
                else:
                    raise SourceError(f"unsupported archive format: {candidate}")
                skills = _find_skill_dirs(tmp)
                if not skills:
                    raise SourceError(f"no SKILL.md found inside archive {candidate}")
                return ResolvedSource(
                    raw_spec=spec,
                    kind="archive",
                    canonical_source=str(candidate),
                    root_dir=tmp,
                    skill_dirs=skills,
                    temp_dir=tmp,
                )
            except Exception:
                shutil.rmtree(tmp, ignore_errors=True)
                raise

        skills = _find_skill_dirs(candidate)
        if not skills:
            raise SourceError(f"no SKILL.md found under local path {candidate}")
        local_commit = ""
        if (candidate / ".git").exists():
            rev = subprocess.run(
                ["git", "-C", str(candidate), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if rev.returncode == 0:
                local_commit = rev.stdout.strip()
        return ResolvedSource(
            raw_spec=spec,
            kind="local",
            canonical_source=str(candidate),
            root_dir=candidate,
            skill_dirs=skills,
            resolved_commit=local_commit,
        )

    # 4. Check GitHub shorthand: owner/repo, github:owner/repo, owner/repo/subpath@ref
    m_gh = _GITHUB_SHORTHAND_RE.match(spec)
    if m_gh and not spec.startswith((".", "/")):
        owner = m_gh.group("owner")
        repo = m_gh.group("repo")
        subpath = m_gh.group("subpath") or ""
        ref = ref_override or (m_gh.group("ref") or "")
        git_url = f"https://github.com/{owner}/{repo}.git"
        return _git_clone(git_url, ref=ref, subpath=subpath, raw_spec=spec, kind="github")

    raise SourceError(f"cannot resolve source {spec!r} (path does not exist and is not a valid repository specifier)")
