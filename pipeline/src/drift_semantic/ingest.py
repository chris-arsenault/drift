"""Ingest external files written by Claude Code (purpose statements, findings).

Validates structure and copies into the pipeline output directory.
"""

import json
import shutil
import sys
from pathlib import Path

from .io_utils import ensure_output_dir

_VALID_VERDICTS = {"DUPLICATE", "OVERLAPPING", "RELATED", "FALSE_POSITIVE"}


def ingest_purposes(file_path: Path, output_dir: Path) -> None:
    """Validate and copy purpose-statements.json into the output directory.

    Each entry must have at least ``unitId`` (str) and ``purpose`` (str) fields.

    Raises:
        ValueError: If the file content is malformed.
    """
    data = _read_json(file_path)

    if not isinstance(data, list):
        raise ValueError("purpose-statements.json must be a JSON array.")

    errors: list[str] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            errors.append(f"  Entry {i}: not an object")
            continue
        if not isinstance(entry.get("unitId"), str):
            errors.append(f"  Entry {i}: missing or non-string 'unitId'")
        if not isinstance(entry.get("purpose"), str):
            errors.append(f"  Entry {i}: missing or non-string 'purpose'")

    if errors:
        raise ValueError("Validation errors in purpose-statements.json:\n" + "\n".join(errors))

    ensure_output_dir(output_dir)
    dest = output_dir / "purpose-statements.json"
    if file_path.resolve() != dest.resolve():
        shutil.copy2(file_path, dest)
    print(f"  Ingested {len(data)} purpose statements to {dest}", file=sys.stderr)


def ingest_findings(file_path: Path, output_dir: Path) -> None:
    """Validate and copy findings.json into the output directory.

    Each entry must have ``clusterId`` (str), ``verdict`` (str), and
    ``confidence`` (str) fields.  Verdicts must be one of:
    DUPLICATE, OVERLAPPING, RELATED, FALSE_POSITIVE.

    Raises:
        ValueError: If the file content is malformed.
    """
    data = _read_json(file_path)

    if not isinstance(data, list):
        raise ValueError("findings.json must be a JSON array.")

    errors: list[str] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            errors.append(f"  Entry {i}: not an object")
            continue
        if not isinstance(entry.get("clusterId"), str):
            errors.append(f"  Entry {i}: missing or non-string 'clusterId'")
        if "verdict" not in entry:
            errors.append(f"  Entry {i}: missing 'verdict'")
        elif entry["verdict"] not in _VALID_VERDICTS:
            errors.append(
                f"  Entry {i}: invalid verdict '{entry['verdict']}'. "
                f"Must be one of: {', '.join(sorted(_VALID_VERDICTS))}"
            )
        if "confidence" not in entry:
            errors.append(f"  Entry {i}: missing 'confidence'")

    if errors:
        raise ValueError("Validation errors in findings.json:\n" + "\n".join(errors))

    ensure_output_dir(output_dir)
    dest = output_dir / "findings.json"
    if file_path.resolve() != dest.resolve():
        shutil.copy2(file_path, dest)
    print(f"  Ingested {len(data)} findings to {dest}", file=sys.stderr)


def _read_json(file_path: Path) -> list | dict:
    """Read and parse a JSON file, raising ValueError on problems."""
    if not file_path.exists():
        raise ValueError(f"File not found: {file_path}")
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {file_path}: {e}") from e
