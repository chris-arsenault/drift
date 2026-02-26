"""Stage 2a: Structural fingerprinting.

Reads code-units.json and computes per-unit structural fingerprints including
JSX hashes, hook profiles, import constellations, behavior flags, and data
access patterns.
"""

import hashlib
import json
import math
import re
from pathlib import Path

from .io_utils import read_code_units, write_artifact
from .vectors import SparseVector


def _sha256(obj: object) -> str:
    """Deterministic SHA-256 hex digest of a JSON-serializable object."""
    raw = json.dumps(obj, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# JSX hashing
# ---------------------------------------------------------------------------

_PASCAL_RE = re.compile(r"^[A-Z][a-zA-Z0-9]+$")


def _wildcard_custom_tags(tree: dict | None) -> dict | None:
    """Replace PascalCase tag names with '<C>' for fuzzy matching."""
    if tree is None:
        return None
    tag = tree.get("tag", "")
    if _PASCAL_RE.match(tag):
        tag = "<C>"
    children = []
    for child in tree.get("children", []):
        if isinstance(child, dict):
            children.append(_wildcard_custom_tags(child))
        else:
            children.append(child)
    return {"tag": tag, "children": children}


def jsx_hash(unit: dict) -> dict:
    """Compute exact and fuzzy JSX structure hashes.

    Returns ``{"exact": str|None, "fuzzy": str|None}``.
    """
    jsx_tree = unit.get("jsxTree")
    if jsx_tree is None:
        return {"exact": None, "fuzzy": None}
    exact = _sha256(jsx_tree)
    fuzzy_tree = _wildcard_custom_tags(jsx_tree)
    fuzzy = _sha256(fuzzy_tree)
    return {"exact": exact, "fuzzy": fuzzy}


# ---------------------------------------------------------------------------
# Hook profile
# ---------------------------------------------------------------------------

_HOOK_ORDER = [
    "useState",
    "useEffect",
    "useCallback",
    "useMemo",
    "useRef",
    "useContext",
    "useReducer",
    "useLayoutEffect",
    "useDeferredValue",
    "useTransition",
]


def hook_profile(unit: dict) -> list[int]:
    """Fixed-length vector of React built-in hook call counts."""
    hook_calls = unit.get("hookCalls", [])
    # hookCalls may be a list of {name, count} or a list of strings
    counts: dict[str, int] = {}
    for entry in hook_calls:
        if isinstance(entry, dict):
            name = entry.get("name", "")
            counts[name] = counts.get(name, 0) + entry.get("count", 1)
        elif isinstance(entry, str):
            counts[entry] = counts.get(entry, 0) + 1
    return [counts.get(hook, 0) for hook in _HOOK_ORDER]


# ---------------------------------------------------------------------------
# Import constellation
# ---------------------------------------------------------------------------


def _compute_idf(units: list[dict]) -> dict[str, float]:
    """Compute inverse document frequency for import sources across all units."""
    doc_count = len(units)
    if doc_count == 0:
        return {}
    source_doc_counts: dict[str, int] = {}
    for u in units:
        sources = set()
        for imp in u.get("imports", []):
            src = imp.get("source", "") if isinstance(imp, dict) else str(imp)
            if src:
                sources.add(src)
        for src in sources:
            source_doc_counts[src] = source_doc_counts.get(src, 0) + 1
    return {src: math.log(doc_count / count) for src, count in source_doc_counts.items()}


def import_constellation(unit: dict, idf: dict[str, float]) -> SparseVector:
    """Import sources weighted by inverse document frequency."""
    vec: SparseVector = {}
    for imp in unit.get("imports", []):
        src = imp.get("source", "") if isinstance(imp, dict) else str(imp)
        if src and src in idf:
            vec[src] = vec.get(src, 0.0) + idf[src]
    return vec


# ---------------------------------------------------------------------------
# Behavior flags
# ---------------------------------------------------------------------------

_BEHAVIOR_KEYS = [
    "isAsync",
    "hasErrorHandling",
    "hasLoadingState",
    "hasEmptyState",
    "hasRetryLogic",
    "rendersIteration",
    "rendersConditional",
    "sideEffects",
]


def behavior_flags(unit: dict) -> list[int]:
    """Binary vector derived from behavior markers."""
    return [1 if unit.get(key, False) else 0 for key in _BEHAVIOR_KEYS]


# ---------------------------------------------------------------------------
# Data access pattern
# ---------------------------------------------------------------------------


def data_access_pattern(unit: dict) -> SparseVector:
    """Sparse vector over store names and data source names."""
    vec: SparseVector = {}
    for store in unit.get("storeAccess", []):
        name = store.get("name", store) if isinstance(store, dict) else str(store)
        if name:
            vec[f"store:{name}"] = vec.get(f"store:{name}", 0.0) + 1.0
    for ds in unit.get("dataSourceAccess", []):
        name = ds.get("name", ds) if isinstance(ds, dict) else str(ds)
        if name:
            vec[f"ds:{name}"] = vec.get(f"ds:{name}", 0.0) + 1.0
    return vec


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def compute_fingerprints(units: list[dict]) -> dict:
    """Compute structural fingerprints for all units.

    Returns a dict keyed by unit id.
    """
    idf = _compute_idf(units)
    result: dict[str, dict] = {}
    for unit in units:
        uid = unit.get("id", "")
        if not uid:
            continue
        result[uid] = {
            "jsxHash": jsx_hash(unit),
            "hookProfile": hook_profile(unit),
            "importConstellation": import_constellation(unit, idf),
            "behaviorFlags": behavior_flags(unit),
            "dataAccessPattern": data_access_pattern(unit),
        }
    return result


def run(output_dir: Path) -> None:
    """Read code-units.json and write structural-fingerprints.json."""
    units = read_code_units(output_dir)
    fingerprints = compute_fingerprints(units)
    write_artifact("structural-fingerprints.json", fingerprints, output_dir)
