#!/usr/bin/env python3
"""Show drift library status: list contents or compare library vs project.

Modes:
  --list                 List all artifacts in the library
  (default)              Compare library artifacts vs project

Usage:
    python3 library-status.py [--list] [--library <path>] <config-file>
    python3 library-status.py --list --library ~/.drift/library
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

TYPE_DIRS: dict[str, str] = {
    "eslint-rule": "rules/eslint",
    "ruff-rule": "rules/ruff",
    "ast-grep-rule": "rules/ast-grep",
    "adr": "adr",
    "pattern": "patterns",
    "checklist": "checklists",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def resolve_library_path(raw: str) -> Path:
    return Path(os.path.expanduser(raw)).resolve()


def list_library(lib_path: Path) -> None:
    """Print all artifacts in the library."""
    if not (lib_path / "library.json").exists():
        print(f"[-] No library.json at {lib_path}", file=sys.stderr)
        sys.exit(1)

    manifest = load_json(lib_path / "library.json")
    artifacts = manifest.get("artifacts", [])

    if not artifacts:
        print("Library is empty.", file=sys.stderr)
        return

    # Group by type
    by_type: dict[str, list[dict]] = {}
    for art in artifacts:
        by_type.setdefault(art.get("type", "unknown"), []).append(art)

    for art_type in sorted(by_type):
        print(f"\n{art_type} ({len(by_type[art_type])})")
        print("-" * 60)
        for art in sorted(by_type[art_type], key=lambda a: a.get("id", "")):
            source = art.get("source_project", "?")
            updated = art.get("updated", "?")
            desc = art.get("description", "")
            filename = art.get("filename", art.get("id", "?"))
            line = f"  {filename:<30} from {source} ({updated})"
            if desc:
                line += f"\n{'':34}{desc}"
            print(line)

    print(f"\nTotal: {len(artifacts)} artifact(s)")


def status(config_path: Path, lib_path_override: Path | None = None) -> None:
    """Compare library artifacts vs project state."""
    config = load_json(config_path)
    project_root = config_path.parent.parent

    lib_path = lib_path_override or resolve_library_path(config.get("library", "~/.drift/library"))
    sync_map = config.get("sync", {})

    if not (lib_path / "library.json").exists():
        print(f"[-] No library at {lib_path}", file=sys.stderr)
        sys.exit(1)

    manifest = load_json(lib_path / "library.json")
    artifacts = manifest.get("artifacts", [])

    if not artifacts:
        print("No artifacts in library.", file=sys.stderr)
        return

    in_sync: list[str] = []
    library_newer: list[str] = []
    project_newer: list[str] = []
    not_synced: list[str] = []

    for art in artifacts:
        art_type = art.get("type", "")
        filename = art.get("filename", os.path.basename(art.get("path", art["id"])))
        label = f"{art_type}/{filename}"

        if art_type not in sync_map:
            not_synced.append(f"{label} (no sync mapping for type '{art_type}')")
            continue

        dest_dir = project_root / sync_map[art_type]
        dest_file = dest_dir / filename

        if not dest_file.exists():
            not_synced.append(label)
            continue

        local_checksum = sha256_file(dest_file)
        lib_checksum = art.get("checksum", "")

        if local_checksum == lib_checksum:
            in_sync.append(label)
        else:
            # Determine which is newer by comparing file mtimes
            lib_file = lib_path / TYPE_DIRS.get(art_type, "") / filename
            if lib_file.exists() and lib_file.stat().st_mtime > dest_file.stat().st_mtime:
                library_newer.append(label)
            else:
                project_newer.append(label)

    # Print report
    total = len(artifacts)
    print(f"Library status ({total} artifact(s)):\n")

    if in_sync:
        print(f"  In sync ({len(in_sync)}):")
        for item in sorted(in_sync):
            print(f"    = {item}")

    if library_newer:
        print(f"\n  Library newer ({len(library_newer)}) — run 'drift library sync' to update:")
        for item in sorted(library_newer):
            print(f"    < {item}")

    if project_newer:
        print(f"\n  Project newer ({len(project_newer)}) — run 'drift library publish' to update:")
        for item in sorted(project_newer):
            print(f"    > {item}")

    if not_synced:
        print(f"\n  Not synced ({len(not_synced)}):")
        for item in sorted(not_synced):
            print(f"    ? {item}")

    if not library_newer and not project_newer and not not_synced:
        print("\nAll artifacts are in sync.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Drift library status")
    parser.add_argument("config", nargs="?", help="Path to .drift-audit/config.json")
    parser.add_argument("--list", action="store_true", help="List all library artifacts")
    parser.add_argument("--library", help="Library path override")
    args = parser.parse_args()

    if args.list:
        if args.library:
            lib_path = resolve_library_path(args.library)
        elif args.config:
            config = load_json(Path(args.config).resolve())
            lib_path = resolve_library_path(config.get("library", "~/.drift/library"))
        else:
            lib_path = resolve_library_path("~/.drift/library")
        list_library(lib_path)
    else:
        if not args.config:
            print("Usage: library-status.py [--list] <config-file>", file=sys.stderr)
            sys.exit(1)
        config_path = Path(args.config).resolve()
        if not config_path.exists():
            print(f"[-] Config not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        lib_override = resolve_library_path(args.library) if args.library else None
        status(config_path, lib_override)


if __name__ == "__main__":
    main()
