"""Shared utilities for drift scripts.

Internal module — not part of the public API.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────

TYPE_DIRS: dict[str, str] = {
    "eslint-rule": "rules/eslint",
    "ruff-rule": "rules/ruff",
    "ast-grep-rule": "rules/ast-grep",
    "adr": "adr",
    "pattern": "patterns",
    "checklist": "checklists",
}

TYPE_EXTENSIONS: dict[str, set[str]] = {
    "eslint-rule": {".js", ".cjs", ".mjs", ".ts"},
    "ruff-rule": {".py", ".toml"},
    "ast-grep-rule": {".yml", ".yaml"},
    "adr": {".md"},
    "pattern": {".md"},
    "checklist": {".md"},
}

DRIFT_MARKER = "drift-generated"

MARKER_PATTERNS: dict[str, str] = {
    ".md": "<!-- drift-generated -->",
    ".js": "// drift-generated",
    ".cjs": "// drift-generated",
    ".mjs": "// drift-generated",
    ".ts": "// drift-generated",
    ".py": "# drift-generated",
    ".toml": "# drift-generated",
    ".yml": "# drift-generated",
    ".yaml": "# drift-generated",
}

IMPACT_ORDER: dict[str, int] = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

TYPE_ORDER: dict[str, int] = {"semantic": 3, "behavioral": 2, "structural": 1}

# ── Output helpers ────────────────────────────────────────────────────

def info(msg: str) -> None:
    print(f"[*] {msg}", file=sys.stderr)


def success(msg: str) -> None:
    print(f"[+] {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"[!] {msg}", file=sys.stderr)


def error(msg: str) -> None:
    print(f"[-] {msg}", file=sys.stderr)


# ── JSON I/O ──────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict | list) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ── File utilities ────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def resolve_library_path(raw: str) -> Path:
    return Path(os.path.expanduser(raw)).resolve()


def has_drift_marker(path: Path) -> bool:
    """Check if a file contains the drift-generated marker in first 5 lines."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for _, line in zip(range(5), f):
                if DRIFT_MARKER in line:
                    return True
    except OSError:
        pass
    return False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Project-level I/O ─────────────────────────────────────────────────

def resolve_project_root(raw: str) -> Path:
    """Resolve a project root path, expanding ~ and making absolute."""
    return Path(os.path.expanduser(raw)).resolve()


def load_config(project_root: Path) -> dict:
    """Load .drift-audit/config.json from a project root."""
    config_path = project_root / ".drift-audit" / "config.json"
    if not config_path.exists():
        error(f"No config at {config_path}")
        sys.exit(1)
    return load_json(config_path)


def load_manifest(project_root: Path) -> dict:
    """Load drift-manifest.json, returning empty structure if missing."""
    path = project_root / ".drift-audit" / "drift-manifest.json"
    if path.exists():
        return load_json(path)
    return {"areas": [], "summary": {}}


def save_manifest(project_root: Path, manifest: dict) -> None:
    path = project_root / ".drift-audit" / "drift-manifest.json"
    save_json(path, manifest)


def load_plan(project_root: Path) -> dict | None:
    """Load attack-plan.json, returning None if missing."""
    path = project_root / ".drift-audit" / "attack-plan.json"
    if path.exists():
        return load_json(path)
    return None


def save_plan(project_root: Path, plan: dict) -> None:
    path = project_root / ".drift-audit" / "attack-plan.json"
    save_json(path, plan)


# ── Manifest helpers ──────────────────────────────────────────────────

def area_files(area: dict) -> set[str]:
    """Extract the set of file paths from an area's variants (strip line ranges)."""
    files: set[str] = set()
    for variant in area.get("variants", []):
        for f in variant.get("files", []):
            files.add(f.split(":")[0])
    return files


def jaccard(a: set, b: set) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Text analysis helpers ─────────────────────────────────────────────

_SENTENCE_RE = re.compile(r"[.!?](?:\s|$)")


def count_sentences(text: str) -> int:
    """Count sentences in text (split by sentence-ending punctuation)."""
    if not text:
        return 0
    return len(_SENTENCE_RE.findall(text))


_PATH_RE = re.compile(r"(?:src/|\.\/|[\w-]+/[\w-]+\.(?:ts|js|tsx|jsx|css|py|md))")
_IFACE_RE = re.compile(r"[A-Z][a-z]+[A-Z]\w+|`\w+`|\w+\(\)")


def has_specific_target(text: str) -> bool:
    """Check if text contains path-like or interface-like tokens."""
    if not text or len(text) < 50:
        return False
    return bool(_PATH_RE.search(text) or _IFACE_RE.search(text))


_LINE_RANGE_RE = re.compile(r":\d+-\d+$")


def has_line_range(file_path: str) -> bool:
    """Check if a file path includes :startLine-endLine."""
    return bool(_LINE_RANGE_RE.search(file_path))
