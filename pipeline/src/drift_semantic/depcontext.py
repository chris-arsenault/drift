"""Stage 2e: Dependency context computation.

Reads code-units.json and computes per-unit dependency context including
consumer profiles, co-occurrence vectors, and neighborhood hashes.
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


def _shannon_entropy(counts: dict[str, int]) -> float:
    """Shannon entropy over a dict of category → count."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def consumer_profile(unit: dict) -> list[float]:
    """[normalized_consumer_count, kind_entropy, directory_spread].

    - normalized_consumer_count: consumer count capped and normalized to [0, 1]
    - kind_entropy: Shannon entropy over consumer kinds
    - directory_spread: distinct consumer directories / total consumers
    """
    consumers = unit.get("consumers", [])
    consumer_count = unit.get("consumerCount", len(consumers))

    # Normalize consumer count: sigmoid-like mapping, cap at ~50
    normalized_count = min(1.0, consumer_count / 50.0) if consumer_count > 0 else 0.0

    # Kind entropy
    consumer_kinds = unit.get("consumerKinds", {})
    if isinstance(consumer_kinds, list):
        kind_counts: dict[str, int] = {}
        for k in consumer_kinds:
            kind_counts[k] = kind_counts.get(k, 0) + 1
        consumer_kinds = kind_counts
    kind_entropy = _shannon_entropy(consumer_kinds) if consumer_kinds else 0.0

    # Directory spread
    consumer_dirs = unit.get("consumerDirectories", [])
    if isinstance(consumer_dirs, list):
        distinct_dirs = len(set(consumer_dirs))
    elif isinstance(consumer_dirs, dict):
        distinct_dirs = len(consumer_dirs)
    else:
        # Extract directories from consumer paths if available
        dirs: set[str] = set()
        for c in consumers:
            if isinstance(c, dict):
                fp = c.get("filePath", c.get("file", ""))
            else:
                fp = str(c)
            if "/" in fp:
                dirs.add(fp.rsplit("/", 1)[0])
        distinct_dirs = len(dirs)

    total_consumers = max(consumer_count, 1)
    dir_spread = distinct_dirs / total_consumers if distinct_dirs > 0 else 0.0

    return [normalized_count, kind_entropy, min(1.0, dir_spread)]


def cooccurrence_vector(unit: dict) -> SparseVector:
    """Sparse vector from unit's coOccurrences field.

    coOccurrences is expected to be a list of {unitId, count, ratio} or
    a dict mapping unitId to count/ratio.
    """
    co = unit.get("coOccurrences", {})
    vec: SparseVector = {}
    if isinstance(co, list):
        for entry in co:
            if isinstance(entry, dict):
                uid = entry.get("unitId", entry.get("id", ""))
                weight = entry.get("ratio", entry.get("count", 1.0))
                if uid:
                    vec[uid] = float(weight)
    elif isinstance(co, dict):
        for uid, val in co.items():
            if isinstance(val, (int, float)):
                vec[uid] = float(val)
            elif isinstance(val, dict):
                vec[uid] = float(val.get("ratio", val.get("count", 1.0)))
    return vec


def _build_consumer_graph(units: list[dict]) -> dict[str, set[str]]:
    """Build a mapping from unit id to set of consumer unit ids."""
    graph: dict[str, set[str]] = {}
    for unit in units:
        uid = unit.get("id", "")
        if not uid:
            continue
        consumers = unit.get("consumers", [])
        consumer_ids: set[str] = set()
        for c in consumers:
            if isinstance(c, dict):
                cid = c.get("id", c.get("unitId", ""))
            else:
                cid = str(c)
            if cid:
                consumer_ids.add(cid)
        graph[uid] = consumer_ids
    return graph


def neighborhood_hash(
    unit_id: str,
    consumer_graph: dict[str, set[str]],
    radius: int,
) -> str:
    """Hash of unit IDs reachable within *radius* hops of the consumer graph."""
    visited: set[str] = {unit_id}
    frontier: set[str] = {unit_id}
    for _ in range(radius):
        next_frontier: set[str] = set()
        for nid in frontier:
            for neighbor in consumer_graph.get(nid, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier
        if not frontier:
            break
    # Exclude the unit itself from the neighborhood set
    neighborhood = sorted(visited - {unit_id})
    return _sha256(neighborhood)


def compute_dep_context(units: list[dict]) -> dict:
    """Compute dependency context for all units.

    Returns a dict keyed by unit id.
    """
    consumer_graph = _build_consumer_graph(units)
    result: dict[str, dict] = {}
    for unit in units:
        uid = unit.get("id", "")
        if not uid:
            continue
        result[uid] = {
            "consumerProfile": consumer_profile(unit),
            "cooccurrenceVector": cooccurrence_vector(unit),
            "neighborhoodHash_r1": neighborhood_hash(uid, consumer_graph, 1),
            "neighborhoodHash_r2": neighborhood_hash(uid, consumer_graph, 2),
        }
    return result


def run(output_dir: Path) -> None:
    """Read code-units.json and write dependency-context.json."""
    units = read_code_units(output_dir)
    dep_ctx = compute_dep_context(units)
    write_artifact("dependency-context.json", dep_ctx, output_dir)
