"""Build standalone single-file zipapp and cross-platform launcher artifacts.

Creates:
  * ``dist/skillporter.pyz`` — self-contained zero-dependency executable zipapp
  * ``npm/bin/skillporter.pyz`` — bundled core payload for the ``npx skillporter`` package
  * ``dist/SHA256SUMS.txt`` — deterministic SHA-256 checksums for release verification
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import stat
import subprocess
import zipapp
from pathlib import Path


def build_artifacts(repo_root: Path | None = None, *, sign_key: Path | None = None) -> dict[str, str]:
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    pkg_src = root / "skillporter"
    dist_dir = root / "dist"
    staging = dist_dir / "_staging"

    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        pkg_src,
        staging / "skillporter",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    pyz_path = dist_dir / "skillporter.pyz"
    zipapp.create_archive(
        staging,
        target=pyz_path,
        interpreter="/usr/bin/env python3",
        main="skillporter.cli:entrypoint",
        compressed=True,
    )
    pyz_path.chmod(pyz_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    shutil.rmtree(staging)

    # Copy payload into npm/bin/ so `npx skillporter` works out of the box with zero network install
    npm_bin = root / "npm" / "bin"
    npm_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pyz_path, npm_bin / "skillporter.pyz")

    # Create Windows batch launcher alongside pyz
    win_cmd = dist_dir / "skillporter-windows-x64.cmd"
    win_cmd.write_text(
        "@echo off\r\n"
        "where python >nul 2>nul && (python \"%~dp0skillporter.pyz\" %* & exit /b %ERRORLEVEL%)\r\n"
        "where py >nul 2>nul && (py -3 \"%~dp0skillporter.pyz\" %* & exit /b %ERRORLEVEL%)\r\n"
        "echo error: Python 3.9+ is required to run skillporter. >&2\r\n"
        "exit /b 2\r\n",
        encoding="utf-8",
    )

    # Create POSIX standalone executables (polyglot header + zip payload) for Linux/macOS targets
    pyz_bytes = pyz_path.read_bytes()
    for target_name in (
        "skillporter-linux-x64",
        "skillporter-linux-arm64",
        "skillporter-macos-arm64",
        "skillporter-macos-x64",
    ):
        tpath = dist_dir / target_name
        tpath.write_bytes(pyz_bytes)
        tpath.chmod(tpath.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    checksums: dict[str, str] = {}
    sums_lines: list[str] = []
    for artifact in sorted(dist_dir.iterdir()):
        if artifact.is_file() and artifact.name != "SHA256SUMS.txt":
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            checksums[artifact.name] = digest
            sums_lines.append(f"{digest}  {artifact.name}")

    sums_path = dist_dir / "SHA256SUMS.txt"
    sums_path.write_text("\n".join(sums_lines) + "\n", encoding="utf-8")

    if sign_key is not None:
        sig_path = dist_dir / "SHA256SUMS.txt.sig"
        subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(sign_key), "-out", str(sig_path), str(sums_path)],
            check=True,
        )

    return checksums


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build standalone Skillporter artifacts and SHA256SUMS.txt")
    parser.add_argument("--sign-key", type=Path, default=None, help="Optional PEM private key to sign SHA256SUMS.txt")
    parsed = parser.parse_args()
    sums = build_artifacts(sign_key=parsed.sign_key)
    for name, sha in sums.items():
        print(f"{sha[:16]}  dist/{name}")
