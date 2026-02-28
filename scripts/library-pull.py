#!/usr/bin/env python3
"""Sync artifacts from the centralized library into a project.

Reads .drift-audit/config.json for:
  - library path
  - sync mappings (artifact type → project directory)

Copies artifacts that have a matching sync mapping.
Only copies when the checksum differs (library is newer).

Usage:
    python3 library-pull.py <config-file>
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _drift_common import (
    TYPE_DIRS,
    sha256_file,
    load_json,
    resolve_library_path,
)


def sync(config_path: Path) -> None:
    config = load_json(config_path)
    project_root = config_path.parent.parent

    lib_path = resolve_library_path(config.get("library", "~/.drift/library"))
    sync_map = config.get("sync", {})

    if not lib_path.exists() or not (lib_path / "library.json").exists():
        print(f"[-] Library not found at {lib_path}", file=sys.stderr)
        print("[-] Run 'drift library init' first.", file=sys.stderr)
        sys.exit(1)

    manifest = load_json(lib_path / "library.json")
    artifacts = manifest.get("artifacts", [])

    # Load per-project excludes from subscriptions.json
    project_name = project_root.name
    exclude_set: set[str] = set()
    subs_path = lib_path / "subscriptions.json"
    if subs_path.exists():
        try:
            subs = load_json(subs_path)
            exclude_set = set(subs.get("projects", {}).get(project_name, {}).get("exclude", []))
        except (json.JSONDecodeError, OSError):
            pass

    synced = 0
    skipped = 0
    excluded = 0
    no_mapping = 0

    for art in artifacts:
        art_type = art.get("type", "")

        if art.get("id", "") in exclude_set:
            excluded += 1
            continue

        if art_type not in sync_map:
            no_mapping += 1
            continue

        filename = art.get("filename", os.path.basename(art.get("path", art["id"])))
        lib_file = lib_path / TYPE_DIRS.get(art_type, "") / filename

        if not lib_file.exists():
            print(f"[!] Library artifact missing: {lib_file}", file=sys.stderr)
            continue

        dest_dir = project_root / sync_map[art_type]
        dest_file = dest_dir / filename

        # Check if project already has this file with same checksum
        if dest_file.exists():
            local_checksum = sha256_file(dest_file)
            if local_checksum == art.get("checksum", ""):
                skipped += 1
                continue

        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(lib_file), str(dest_file))
        synced += 1
        print(f"[+] Synced: {art_type}/{filename}", file=sys.stderr)

    print(file=sys.stderr)
    print(f"[+] Synced {synced} artifact(s), {skipped} already up-to-date.", file=sys.stderr)
    if excluded:
        print(f"[*] {excluded} artifact(s) excluded by subscription settings.", file=sys.stderr)
    if no_mapping:
        print(f"[!] {no_mapping} artifact(s) in library have no mapping in this project.", file=sys.stderr)


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config-file>", file=sys.stderr)
        sys.exit(1)

    config_path = Path(sys.argv[1]).resolve()
    if not config_path.exists():
        print(f"[-] Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    sync(config_path)


if __name__ == "__main__":
    main()
