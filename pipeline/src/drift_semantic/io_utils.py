"""I/O utilities for reading and writing pipeline artifacts."""

import json
from pathlib import Path
from typing import Any


def ensure_output_dir(output_dir: Path) -> None:
    """Create the output directory if it doesn't exist."""
    output_dir.mkdir(parents=True, exist_ok=True)


def read_artifact(name: str, output_dir: Path) -> dict:
    """Read a JSON artifact from the output directory.

    Args:
        name: Artifact filename (e.g. 'code-units.json').
        output_dir: Directory containing pipeline artifacts.

    Returns:
        Parsed JSON content.

    Raises:
        FileNotFoundError: With a helpful message indicating which artifact
            is missing and which stage produces it.
    """
    path = output_dir / name
    if not path.exists():
        stage_hints = {
            "code-units.json": "extract (TypeScript extractor)",
            "structural-fingerprints.json": "fingerprint",
            "type-signatures.json": "typesig",
            "call-graph.json": "callgraph",
            "dependency-context.json": "depcontext",
            "semantic-embeddings.json": "embed",
            "similarity-matrix.json": "score",
            "clusters.json": "cluster",
            "purpose-statements.json": "ingest-purposes (written by Claude)",
            "findings.json": "ingest-findings (written by Claude)",
        }
        hint = stage_hints.get(name, "unknown")
        raise FileNotFoundError(
            f"Artifact '{name}' not found at {path}. Run the '{hint}' stage first."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_artifact(name: str, data: Any, output_dir: Path) -> Path:
    """Write a JSON artifact to the output directory.

    Args:
        name: Artifact filename.
        data: Data to serialize as JSON.
        output_dir: Directory to write into.

    Returns:
        Path to the written file.
    """
    ensure_output_dir(output_dir)
    path = output_dir / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return path


def resolve_consumer_id(consumer: object) -> str:
    """Extract a consumer unit ID from a dict or string.

    Consumer entries in code-units.json may be plain strings (unit IDs)
    or dicts with 'id' or 'unitId' keys.
    """
    if isinstance(consumer, dict):
        return consumer.get("id", consumer.get("unitId", ""))
    return str(consumer)


def read_code_units(output_dir: Path) -> list[dict]:
    """Read code-units.json and return the units array.

    The file may contain either a bare array or an object with a 'units' key.
    """
    data = read_artifact("code-units.json", output_dir)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "units" in data:
        return data["units"]
    raise ValueError("code-units.json must be a JSON array or an object with a 'units' key.")
