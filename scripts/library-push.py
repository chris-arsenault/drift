#!/usr/bin/env python3
"""Publish drift-guard artifacts from a project into the centralized library.

Reads .drift-audit/config.json to find:
  - library path
  - sync mappings (artifact type → project directory)

Scans each sync directory, computes checksums, and copies new/updated
artifacts into the library.  Updates library.json accordingly.

Usage:
    python3 library-push.py <config-file>
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _drift_common import (
    TYPE_DIRS,
    TYPE_EXTENSIONS,
    DRIFT_MARKER,
    MARKER_PATTERNS,
    has_drift_marker,
    sha256_file,
    load_json,
    save_json,
    resolve_library_path,
)


def collect_artifacts(
    project_root: Path,
    sync_map: dict[str, str],
    project_name: str,
) -> list[dict]:
    """Walk sync directories and collect publishable artifact metadata."""
    artifacts: list[dict] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    skipped: list[tuple[str, str]] = []  # (type, filename) — files missing marker

    for art_type, rel_dir in sync_map.items():
        if art_type not in TYPE_DIRS:
            print(f"  [!] Unknown artifact type '{art_type}' in config — skipping", file=sys.stderr)
            continue

        src_dir = project_root / rel_dir
        if not src_dir.is_dir():
            continue

        extensions = TYPE_EXTENSIONS.get(art_type, set())

        for entry in sorted(src_dir.iterdir()):
            if not entry.is_file():
                continue
            if extensions and entry.suffix not in extensions:
                continue
            if not has_drift_marker(entry):
                skipped.append((art_type, str(entry.relative_to(project_root))))
                continue

            art_id = entry.stem
            checksum = sha256_file(entry)

            artifacts.append(
                {
                    "id": art_id,
                    "type": art_type,
                    "filename": entry.name,
                    "source_project": project_name,
                    "created": now,
                    "updated": now,
                    "description": "",
                    "checksum": checksum,
                    "_src_path": str(entry),
                }
            )

    if skipped:
        print(f"\n[!] {len(skipped)} file(s) skipped — missing drift-generated marker:", file=sys.stderr)
        for art_type, rel_path in skipped:
            marker = MARKER_PATTERNS.get(Path(rel_path).suffix, DRIFT_MARKER)
            print(f"    {rel_path}  (add '{marker}' as the first line)", file=sys.stderr)
        print(file=sys.stderr)

    return artifacts


def publish(config_path: Path) -> None:
    config = load_json(config_path)
    project_root = config_path.parent.parent  # .drift-audit/config.json → project root

    lib_path = resolve_library_path(config.get("library", "~/.drift/library"))
    sync_map = config.get("sync", {})

    # Use directory basename as project identity
    project_name = project_root.name

    if not lib_path.exists() or not (lib_path / "library.json").exists():
        print(f"[-] Library not found at {lib_path}", file=sys.stderr)
        print("[-] Run 'drift library init' first.", file=sys.stderr)
        sys.exit(1)

    # Collect from project
    local_artifacts = collect_artifacts(project_root, sync_map, project_name)

    if not local_artifacts:
        print("[*] No artifacts found to publish.", file=sys.stderr)
        return

    # Load library manifest
    manifest = load_json(lib_path / "library.json")
    existing: dict[tuple[str, str], dict] = {}
    for art in manifest.get("artifacts", []):
        key = (art["type"], art.get("filename", art["id"]))
        existing[key] = art

    published = 0
    skipped = 0

    for art in local_artifacts:
        src_path = Path(art.pop("_src_path"))
        key = (art["type"], art["filename"])
        lib_subdir = lib_path / TYPE_DIRS[art["type"]]
        dest_path = lib_subdir / art["filename"]

        if key in existing:
            old = existing[key]
            if old.get("checksum") == art["checksum"]:
                skipped += 1
                continue
            # Update existing entry
            old["checksum"] = art["checksum"]
            old["updated"] = art["updated"]
            old["source_project"] = art["source_project"]
        else:
            # New artifact — assign library-relative path
            art["path"] = f"{TYPE_DIRS[art['type']]}/{art['filename']}"
            manifest.setdefault("artifacts", []).append(art)

        lib_subdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src_path), str(dest_path))
        published += 1
        print(f"[+] Published: {art['type']}/{art['filename']}", file=sys.stderr)

    save_json(lib_path / "library.json", manifest)

    print(file=sys.stderr)
    print(f"[+] Published {published} artifact(s), {skipped} unchanged.", file=sys.stderr)


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config-file>", file=sys.stderr)
        sys.exit(1)

    config_path = Path(sys.argv[1]).resolve()
    if not config_path.exists():
        print(f"[-] Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    publish(config_path)


if __name__ == "__main__":
    main()
