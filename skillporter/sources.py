"""Universal Source Resolution Engine.

Resolves skill packages from:
  * Local directories (single skill or multi-skill repository)
  * Local ZIP / tar.gz archives (with strict Zip-Slip, duplicate-entry, symlink, and bomb protection)
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
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import zipfile
import zlib
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

MAX_ARCHIVE_FILES = 1000
MAX_SINGLE_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB per member
MAX_TOTAL_ARCHIVE_BYTES = 50 * 1024 * 1024  # 50 MiB total archive extraction budget


def _copy_bounded(
    src,
    out,
    *,
    member_name: str,
    max_file_bytes: int,
    total_counter: list[int],
    max_total_bytes: int,
) -> None:
    """Copy stream in chunks while enforcing per-file and total decompression limits."""
    written = 0
    while True:
        chunk = src.read(65536)
        if not chunk:
            break
        written += len(chunk)
        total_counter[0] += len(chunk)
        if written > max_file_bytes:
            raise SourceError(
                f"archive member {member_name!r} exceeds maximum allowed size ({max_file_bytes} bytes)"
            )
        if total_counter[0] > max_total_bytes:
            raise SourceError(
                f"archive exceeds maximum total extracted size ({max_total_bytes} bytes)"
            )
        out.write(chunk)


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


_WIN_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
)


def _unsafe_member_name(name: str) -> str:
    """Return a reason string when an archive member name is unsafe, else ""."""
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
    if any(ord(ch) < 32 for ch in raw):
        return "control character in name"
    for seg in parts:
        if ":" in seg:
            return "colon / alternate data stream in name"
        if seg.endswith(".") or seg.endswith(" "):
            return "trailing dot or space in segment"
        stem = seg.split(".", 1)[0].upper()
        if stem in _WIN_RESERVED_NAMES:
            return f"Windows reserved device name {stem!r}"
    return ""


def _normalized_archive_key(name: str) -> str:
    """Return a Unicode-NFC, case-folded POSIX path key for duplicate/collision detection."""
    raw = unicodedata.normalize("NFC", name.replace("\\", "/").rstrip("/"))
    if not raw or raw == ".":
        return ""
    return posixpath.normpath(raw).casefold()


def _open_new_archive_target(dest_dir: Path, target: Path):
    """Safely create a brand-new regular file under *dest_dir* without following symlinks."""
    cur = target.parent
    while cur != dest_dir and dest_dir in cur.parents:
        if cur.is_symlink():
            raise SourceError(f"symlinked parent directory {cur} rejected during extraction")
        cur = cur.parent
    if target.is_symlink() or target.exists():
        raise SourceError(f"refusing to overwrite pre-existing entry or symlink {target}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(target), flags, 0o644)
    except OSError as exc:
        raise SourceError(f"cannot safely create extracted file {target}: {exc}") from exc
    return os.fdopen(fd, "wb")


def safe_extract_zip(
    archive_path: Path,
    dest_dir: Path,
    *,
    max_files: int = MAX_ARCHIVE_FILES,
    max_file_bytes: int = MAX_SINGLE_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_ARCHIVE_BYTES,
) -> Path:
    """Extract a ZIP archive into *dest_dir*, rejecting path traversal, duplicates, symlinks, and zip bombs."""
    dest_dir = dest_dir.resolve()
    existed_before = dest_dir.exists()
    dest_dir.mkdir(parents=True, exist_ok=True)
    created_entries: list[Path] = []
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > max_files:
                raise SourceError(
                    f"archive {archive_path} contains {len(infos)} entries (exceeds limit of {max_files})"
                )
            seen_files: set[str] = set()
            for info in infos:
                name = info.filename
                reason = _unsafe_member_name(name)
                if reason:
                    raise SourceError(f"unsafe archive path {name!r} in {archive_path} ({reason} rejected)")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise SourceError(f"unsafe symlink entry {name!r} in {archive_path} (archive symlinks rejected)")
                if mode != 0 and mode not in (0o100000, 0o040000):
                    raise SourceError(
                        f"unsafe special file entry {name!r} in {archive_path} (mode {oct(mode)} rejected)"
                    )
                if info.file_size < 0 or info.file_size > max_file_bytes:
                    raise SourceError(
                        f"archive member {name!r} exceeds maximum allowed size ({max_file_bytes} bytes)"
                    )
                if not info.is_dir():
                    nkey = _normalized_archive_key(name)
                    if nkey in seen_files:
                        raise SourceError(
                            f"duplicate or case-colliding archive entry {name!r} in {archive_path}"
                        )
                    seen_files.add(nkey)
                raw_target = dest_dir / unicodedata.normalize("NFC", name.replace("\\", "/"))
                if raw_target.is_symlink():
                    raise SourceError(f"archive member {name!r} targets an existing symlink in destination")
                target = raw_target.resolve()
                try:
                    target.relative_to(dest_dir)
                except ValueError as exc:
                    raise SourceError(f"archive member {name!r} escapes destination directory") from exc

            total_counter = [0]
            for info in infos:
                rel_clean = unicodedata.normalize("NFC", info.filename.replace("\\", "/"))
                raw_target = dest_dir / rel_clean
                if info.is_dir():
                    raw_target.mkdir(parents=True, exist_ok=True)
                    created_entries.append(raw_target)
                    continue
                raw_target.parent.mkdir(parents=True, exist_ok=True)
                created_entries.append(raw_target)
                with zf.open(info) as src, _open_new_archive_target(dest_dir, raw_target) as out:
                    _copy_bounded(
                        src,
                        out,
                        member_name=info.filename,
                        max_file_bytes=max_file_bytes,
                        total_counter=total_counter,
                        max_total_bytes=max_total_bytes,
                    )
    except SourceError:
        for entry in reversed(created_entries):
            if entry.is_file() or entry.is_symlink():
                entry.unlink(missing_ok=True)
        if not existed_before:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise
    except (zipfile.BadZipFile, EOFError, zlib.error, OSError) as exc:
        for entry in reversed(created_entries):
            if entry.is_file() or entry.is_symlink():
                entry.unlink(missing_ok=True)
        if not existed_before:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise SourceError(f"corrupted or unreadable zip archive {archive_path}: {exc}") from exc
    return dest_dir


def safe_extract_tar(
    archive_path: Path,
    dest_dir: Path,
    *,
    max_files: int = MAX_ARCHIVE_FILES,
    max_file_bytes: int = MAX_SINGLE_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_ARCHIVE_BYTES,
) -> Path:
    """Extract a tar archive into *dest_dir*, rejecting path traversal, duplicates, symlinks/devices, and tar bombs."""
    dest_dir = dest_dir.resolve()
    existed_before = dest_dir.exists()
    dest_dir.mkdir(parents=True, exist_ok=True)
    created_entries: list[Path] = []
    try:
        with tarfile.open(archive_path, "r:*") as tf:
            members = tf.getmembers()
            if len(members) > max_files:
                raise SourceError(
                    f"archive {archive_path} contains {len(members)} entries (exceeds limit of {max_files})"
                )
            seen_files: set[str] = set()
            for member in members:
                reason = _unsafe_member_name(member.name)
                if reason:
                    raise SourceError(f"unsafe tar path {member.name!r} in {archive_path} ({reason} rejected)")
                if member.issym() or member.islnk() or member.isdev() or member.isfifo() or not (
                    member.isfile() or member.isdir()
                ):
                    raise SourceError(
                        f"unsafe special/symlink entry {member.name!r} in {archive_path} (rejected by security policy)"
                    )
                if member.size < 0 or member.size > max_file_bytes:
                    raise SourceError(
                        f"archive member {member.name!r} exceeds maximum allowed size ({max_file_bytes} bytes)"
                    )
                if member.isfile():
                    nkey = _normalized_archive_key(member.name)
                    if nkey in seen_files:
                        raise SourceError(
                            f"duplicate or case-colliding tar entry {member.name!r} in {archive_path}"
                        )
                    seen_files.add(nkey)
                raw_target = dest_dir / unicodedata.normalize("NFC", member.name.replace("\\", "/"))
                if raw_target.is_symlink():
                    raise SourceError(f"tar member {member.name!r} targets an existing symlink in destination")
                target = raw_target.resolve()
                try:
                    target.relative_to(dest_dir)
                except ValueError as exc:
                    raise SourceError(f"tar member {member.name!r} escapes destination directory") from exc

            total_counter = [0]
            for member in members:
                rel_clean = unicodedata.normalize("NFC", member.name.replace("\\", "/"))
                raw_target = dest_dir / rel_clean
                if member.isdir():
                    raw_target.mkdir(parents=True, exist_ok=True)
                    created_entries.append(raw_target)
                    continue
                raw_target.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is None:
                    continue
                created_entries.append(raw_target)
                with src, _open_new_archive_target(dest_dir, raw_target) as out:
                    _copy_bounded(
                        src,
                        out,
                        member_name=member.name,
                        max_file_bytes=max_file_bytes,
                        total_counter=total_counter,
                        max_total_bytes=max_total_bytes,
                    )
                if member.mode:
                    with contextlib.suppress(OSError):
                        os.chmod(raw_target, member.mode & 0o755)
    except SourceError:
        for entry in reversed(created_entries):
            if entry.is_file() or entry.is_symlink():
                entry.unlink(missing_ok=True)
        if not existed_before:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise
    except (tarfile.TarError, EOFError, zlib.error, OSError) as exc:
        for entry in reversed(created_entries):
            if entry.is_file() or entry.is_symlink():
                entry.unlink(missing_ok=True)
        if not existed_before:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise SourceError(f"corrupted or unreadable tar archive {archive_path}: {exc}") from exc
    return dest_dir


def _git_clone(url: str, ref: str = "", subpath: str = "", raw_spec: str = "", kind: str = "git") -> ResolvedSource:
    ref = _validate_git_ref(ref)
    tmp = Path(tempfile.mkdtemp(prefix="skillporter-src-"))
    repo_dir = tmp / "repo"
    try:
        cmd = [
            "git",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.symlinks=false",
            "clone",
            "--quiet",
        ]
        is_sha = bool(ref and re.fullmatch(r"[0-9a-fA-F]{7,40}", ref))
        if not is_sha:
            cmd.extend(["--depth", "1"])
            if ref:
                cmd.extend(["--branch", ref])
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

    # 2. Check explicit github: shorthand before Path() (avoids ':' syntax error on Windows)
    if spec.startswith("github:"):
        m_gh_explicit = _GITHUB_SHORTHAND_RE.match(spec)
        if m_gh_explicit:
            owner = m_gh_explicit.group("owner")
            repo = m_gh_explicit.group("repo")
            subpath = m_gh_explicit.group("subpath") or ""
            ref = ref_override or (m_gh_explicit.group("ref") or "")
            return _git_clone(
                f"https://github.com/{owner}/{repo}.git",
                ref=ref,
                subpath=subpath,
                raw_spec=spec,
                kind="github",
            )

    # 3. Check arbitrary git URL (https://, http://, git@, file://) before Path()
    if spec.lower().startswith(("https://", "http://", "file://")) or spec.startswith("git@"):
        frag_ref = ""
        url_part = spec
        if "#" in url_part:
            url_part, _, frag_ref = url_part.partition("#")
        elif not url_part.startswith("git@") and not url_part.lower().startswith("file://"):
            split_u = urllib.parse.urlsplit(url_part)
            if "@" in split_u.path:
                clean_path, _, frag_ref = split_u.path.rpartition("@")
                url_part = urllib.parse.urlunsplit((split_u.scheme, split_u.netloc, clean_path, split_u.query, ""))
        if url_part.lower().startswith("file://"):
            parsed_f = urllib.parse.urlsplit(url_part)
            local_git_path = urllib.request.url2pathname(urllib.parse.unquote(parsed_f.path))
            url_part = str(Path(local_git_path).resolve())
        return _git_clone(url_part, ref=ref_override or frag_ref, raw_spec=spec, kind="git")

    # 4. Check if spec is an existing local path (directory, SKILL.md file, or archive)
    candidate: Path | None = None
    try:
        cand_raw = Path(spec).expanduser()
        candidate = (base / cand_raw).resolve() if not cand_raw.is_absolute() else cand_raw.resolve()
    except OSError:
        candidate = None

    if candidate is not None and candidate.exists():
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
