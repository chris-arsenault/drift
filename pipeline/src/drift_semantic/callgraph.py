"""Stage 2d: Call graph vector computation.

Reads code-units.json and computes per-unit call graph vectors including
callee set vectors, sequence hashes, chain pattern hashes, and depth profiles.
"""

import hashlib
import json
import math
from pathlib import Path

from .io_utils import read_code_units, write_artifact
from .vectors import SparseVector


def _sha256(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _compute_callee_idf(units: list[dict]) -> dict[str, float]:
    """Compute inverse document frequency for callees across all units."""
    doc_count = len(units)
    if doc_count == 0:
        return {}
    callee_doc_counts: dict[str, int] = {}
    for u in units:
        seen: set[str] = set()
        for callee in u.get("callees", []):
            target = callee.get("target", callee) if isinstance(callee, dict) else str(callee)
            if target and target not in seen:
                seen.add(target)
                callee_doc_counts[target] = callee_doc_counts.get(target, 0) + 1
    return {name: math.log(doc_count / count) for name, count in callee_doc_counts.items()}


def callee_set_vector(unit: dict, idf: dict[str, float]) -> SparseVector:
    """Callee names weighted by inverse frequency across all units."""
    vec: SparseVector = {}
    for callee in unit.get("callees", []):
        target = callee.get("target", callee) if isinstance(callee, dict) else str(callee)
        if target and target in idf:
            vec[target] = vec.get(target, 0.0) + idf[target]
    return vec


def sequence_hashes(unit: dict) -> dict[str, str]:
    """Hash of calleeSequence per context (render, effect, handler).

    Returns a dict mapping context name to SHA-256 hash of the ordered
    callee list for that context.
    """
    callee_sequences = unit.get("calleeSequence", {})
    if not isinstance(callee_sequences, dict):
        return {}
    result: dict[str, str] = {}
    for context, seq in callee_sequences.items():
        if isinstance(seq, list) and seq:
            result[context] = _sha256(seq)
    return result


def chain_pattern_hashes(unit: dict) -> list[str]:
    """Hashes of chainPatterns for structural comparison."""
    patterns = unit.get("chainPatterns", [])
    if not isinstance(patterns, list):
        return []
    return [_sha256(p) for p in patterns if p]


def depth_profile(unit: dict) -> list[int]:
    """[direct_calls, depth2, depth3plus] from callDepth and callees.

    Uses callDepth if available, otherwise estimates from callees list.
    """
    call_depth = unit.get("callDepth", {})
    if isinstance(call_depth, dict) and call_depth:
        direct = call_depth.get("1", call_depth.get(1, 0))
        depth2 = call_depth.get("2", call_depth.get(2, 0))
        depth3plus = sum(
            v
            for k, v in call_depth.items()
            if isinstance(v, (int, float))
            and str(k) not in ("1", "2")
            and (
                (isinstance(k, int) and k >= 3)
                or (isinstance(k, str) and k.isdigit() and int(k) >= 3)
            )
        )
        return [int(direct), int(depth2), int(depth3plus)]

    # Fallback: count unique callees as direct calls
    callees = unit.get("callees", [])
    unique = unit.get(
        "uniqueCallees",
        len(set((c.get("target", c) if isinstance(c, dict) else str(c)) for c in callees)),
    )
    return [int(unique), 0, 0]


def compute_call_vectors(units: list[dict]) -> dict:
    """Compute call graph vectors for all units.

    Returns a dict keyed by unit id.
    """
    idf = _compute_callee_idf(units)
    result: dict[str, dict] = {}
    for unit in units:
        uid = unit.get("id", "")
        if not uid:
            continue
        result[uid] = {
            "calleeSetVector": callee_set_vector(unit, idf),
            "sequenceHashes": sequence_hashes(unit),
            "chainPatternHashes": chain_pattern_hashes(unit),
            "depthProfile": depth_profile(unit),
        }
    return result


def run(output_dir: Path) -> None:
    """Read code-units.json and write call-graph.json."""
    units = read_code_units(output_dir)
    call_vectors = compute_call_vectors(units)
    write_artifact("call-graph.json", call_vectors, output_dir)
