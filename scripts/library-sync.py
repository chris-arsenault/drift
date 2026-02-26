#!/usr/bin/env python3
"""Sync matching artifacts from the centralized library into a project.

Reads .drift-audit/config.json for:
  - library path
  - project tags (used to filter artifacts)
  - sync mappings (artifact type → project directory)

Copies artifacts whose tags intersect with the project's tags.
Only copies when the checksum differs (library is newer).

Usage:
    python3 library-sync.py <config-file>
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

# ── Artifact type → library subdirectory mapping ─────────────────────────
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


def tags_match(artifact_tags: list[str], project_tags: list[str]) -> bool:
    """True if any artifact tag appears in the project's tag list."""
    return bool(set(artifact_tags) & set(project_tags))


def sync(config_path: Path) -> None:
    config = load_json(config_path)
    project_root = config_path.parent.parent

    lib_path = resolve_library_path(config.get("library", "~/.drift/library"))
    project_tags = config.get("tags", [])
    sync_map = config.get("sync", {})

    if not lib_path.exists() or not (lib_path / "library.json").exists():
        print(f"[-] Library not found at {lib_path}", file=sys.stderr)
        print("[-] Run 'drift library init' first.", file=sys.stderr)
        sys.exit(1)

    if not project_tags:
        print("[!] No tags in .drift-audit/config.json — nothing will match.", file=sys.stderr)
        print("[!] Add tags to enable sync (e.g. [\"react\", \"zustand\"]).", file=sys.stderr)
        return

    manifest = load_json(lib_path / "library.json")
    artifacts = manifest.get("artifacts", [])

    synced = 0
    skipped = 0
    no_mapping = 0

    for art in artifacts:
        art_tags = art.get("tags", [])
        art_type = art.get("type", "")

        if not tags_match(art_tags, project_tags):
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
    if no_mapping:
        print(f"[!] {no_mapping} artifact(s) matched by tag but have no sync mapping for their type.", file=sys.stderr)


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
