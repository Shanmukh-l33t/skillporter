#!/usr/bin/env python3
"""Generate the website datasets from the authoritative Python sources.

The website never hand-maintains harness or CLI facts. This script reads:

  * ``skillporter.harnesses.HARNESSES``  -> ``website/src/data/harnesses.json``
  * ``skillporter.cli.build_parser()``   -> ``website/src/data/cli.json``
  * ``skillporter.__version__``          -> ``website/src/data/release.json``

and refreshes the generated matrix inside ``docs/harnesses/README.md``.

Usage:
    python3 website/scripts/generate_site_data.py           # write files
    python3 website/scripts/generate_site_data.py --check   # exit 1 when stale

The output is deterministic (no timestamps), so ``--check`` can run in CI and
fail whenever the committed website data drifts from the Python registry.
Standard library only; it imports the package from the repository checkout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WEBSITE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = WEBSITE_DIR.parent
DATA_DIR = WEBSITE_DIR / "src" / "data"
HARNESS_DOC = REPO_ROOT / "docs" / "harnesses" / "README.md"

sys.path.insert(0, str(REPO_ROOT))

import skillporter  # noqa: E402
from skillporter import cli as sp_cli  # noqa: E402
from skillporter import harnesses as sp_harnesses  # noqa: E402

BEGIN_MARK = "<!-- BEGIN GENERATED: harness-matrix (website/scripts/generate_site_data.py) -->"
END_MARK = "<!-- END GENERATED: harness-matrix -->"

SHARED_DIR = ".agents/skills"
GITHUB_REPO = "Shanmukh-l33t/skillporter"


def _display_path(path: str, scope: str) -> str:
    """Render a registry path the way a person types it."""
    if scope == "user" and not path.startswith(("$", "/", "~")):
        return f"~/{path}"
    return path


def _path_rows(paths: tuple[sp_harnesses.SkillPath, ...]) -> list[dict[str, object]]:
    return [
        {
            "path": _display_path(p.path, p.scope),
            "compat": bool(p.is_compatibility),
            "note": p.note,
        }
        for p in paths
    ]


def _shared_role(h: sp_harnesses.Harness) -> str | None:
    """How a harness relates to the shared project directory ``.agents/skills``."""
    primary = h.primary_project_path
    if primary and primary.path == SHARED_DIR:
        return "primary"
    if any(p.path == SHARED_DIR for p in h.project_paths):
        return "compat"
    return None


def build_harness_data() -> dict[str, object]:
    levels: list[str] = [str(level) for level in sp_harnesses.VERIFICATION_LEVELS]
    ordered = sorted(
        sp_harnesses.HARNESSES.values(),
        key=lambda h: levels.index(h.verification_level),
    )
    rows: list[dict[str, object]] = []
    for h in ordered:
        project_primary = h.primary_project_path
        user_primary = h.primary_user_path
        rows.append(
            {
                "id": h.name,
                "name": h.label,
                "category": h.category,
                "support": h.support_status,
                "verification": h.verification_level,
                "verified_date": h.verified_date,
                "docs": h.docs,
                "aliases": list(h.aliases),
                "project_primary": _display_path(project_primary.path, "project") if project_primary else None,
                "user_primary": _display_path(user_primary.path, "user") if user_primary else None,
                "project_paths": _path_rows(h.project_paths),
                "user_paths": _path_rows(h.user_paths),
                "shared_agents_dir": _shared_role(h),
                "recursive_discovery": bool(h.capabilities.recursive_discovery),
                "adapted_format": h.capabilities.adapted_format,
                "notes": list(h.notes),
                "limitations": list(h.limitations),
            }
        )

    def tally(key: str, order: list[str]) -> dict[str, int]:
        counts = {name: 0 for name in order}
        for row in rows:
            counts[str(row[key])] = counts.get(str(row[key]), 0) + 1
        return {name: n for name, n in counts.items() if n}

    return {
        "source": "skillporter/harnesses.py",
        "version": skillporter.__version__,
        "counts": {
            "total": len(rows),
            "verification": tally("verification", levels),
            "support": tally("support", [str(s) for s in sp_harnesses.SUPPORT_STATUSES]),
            "category": tally("category", ["coding", "autonomous", "editor"]),
            "shared_primary": sum(1 for r in rows if r["shared_agents_dir"] == "primary"),
            "shared_compat": sum(1 for r in rows if r["shared_agents_dir"] == "compat"),
        },
        "harnesses": rows,
    }


def _describe_parser(parser: argparse.ArgumentParser) -> dict[str, object]:
    flags: list[str] = []
    positionals: list[str] = []
    subcommands: dict[str, object] = {}
    for action in parser._actions:  # noqa: SLF001 - argparse has no public introspection API
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, sub in sorted(action.choices.items()):
                subcommands[name] = _describe_parser(sub)
            continue
        if isinstance(action, argparse._HelpAction):  # noqa: SLF001
            continue
        if action.option_strings:
            flags.extend(action.option_strings)
        else:
            positionals.append(action.dest)
    entry: dict[str, object] = {"flags": sorted(flags), "positionals": positionals}
    if subcommands:
        entry["subcommands"] = subcommands
    return entry


def build_cli_data() -> dict[str, object]:
    parser = sp_cli.build_parser()
    described = _describe_parser(parser)
    helps: dict[str, str] = {}
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for choice in action._choices_actions:  # noqa: SLF001
                helps[choice.dest] = choice.help or ""
    commands = described.get("subcommands", {})
    assert isinstance(commands, dict)
    for name, entry in commands.items():
        assert isinstance(entry, dict)
        entry["help"] = helps.get(name, "")
    return {
        "source": "skillporter/cli.py",
        "version": skillporter.__version__,
        "global_flags": described["flags"],
        "commands": commands,
    }


def build_release_data() -> dict[str, object]:
    version = skillporter.__version__
    tag = f"v{version}"
    npm_meta = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    return {
        "version": version,
        "tag": tag,
        "license": npm_meta["license"],
        "repository": f"https://github.com/{GITHUB_REPO}",
        "release_url": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}",
        "installer_url": f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/install.sh",
        "pypi_package": "skillporter",
        "npm_package": npm_meta["name"],
    }


def render_harness_table(data: dict[str, object]) -> str:
    rows = data["harnesses"]
    counts = data["counts"]
    assert isinstance(rows, list) and isinstance(counts, dict)
    lines = [
        BEGIN_MARK,
        "",
        "| ID | Harness | Category | Support | Verification | Project path | User path | Vendor docs |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        cells = [
            f"`{row['id']}`",
            str(row["name"]),
            str(row["category"]),
            f"`{row['support']}`",
            f"`{row['verification']}`",
            f"`{row['project_primary']}`",
            f"`{row['user_primary']}`",
            f"[Docs]({row['docs']})",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    verification = counts["verification"]
    assert isinstance(verification, dict)
    summary = ", ".join(f"{n} `{level}`" for level, n in verification.items())
    lines += ["", f"{counts['total']} adapters: {summary}.", "", END_MARK]
    return "\n".join(lines)


def refresh_harness_doc(data: dict[str, object]) -> str:
    text = HARNESS_DOC.read_text(encoding="utf-8")
    if BEGIN_MARK not in text or END_MARK not in text:
        raise SystemExit(f"error: generated-region markers missing from {HARNESS_DOC}")
    head, rest = text.split(BEGIN_MARK, 1)
    _, tail = rest.split(END_MARK, 1)
    return head + render_harness_table(data) + tail


def _dump(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the website datasets from the Python sources.")
    ap.add_argument("--check", action="store_true", help="verify committed files are current; write nothing")
    args = ap.parse_args()

    harness_data = build_harness_data()
    outputs: dict[Path, str] = {
        DATA_DIR / "harnesses.json": _dump(harness_data),
        DATA_DIR / "cli.json": _dump(build_cli_data()),
        DATA_DIR / "release.json": _dump(build_release_data()),
        HARNESS_DOC: refresh_harness_doc(harness_data),
    }

    stale = [p for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]

    if args.check:
        if stale:
            for path in stale:
                print(f"STALE: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
            print(
                "error: website data is out of sync with the Python registry. "
                "Run: python3 website/scripts/generate_site_data.py",
                file=sys.stderr,
            )
            return 1
        counts = harness_data["counts"]
        assert isinstance(counts, dict)
        print(f"website data is current ({counts['total']} harnesses, skillporter {skillporter.__version__}).")
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in stale:
        path.write_text(outputs[path], encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    if not stale:
        print("website data already current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
