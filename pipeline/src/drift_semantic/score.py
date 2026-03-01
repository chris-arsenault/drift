"""Stage 3: Pairwise similarity scoring.

THE CORE. Reads all Stage 2 artifacts, computes pairwise similarity for all
viable unit pairs, and emits scored pairs above a configurable threshold.
"""

import contextlib
import sys
from pathlib import Path

from .io_utils import read_artifact, read_code_units, resolve_consumer_id, write_artifact
from .similarity import (
    normalized_hamming,
    tree_edit_distance_normalized,
)
from .vectors import SparseVector, cosine_sim, jaccard_sim

# ---------------------------------------------------------------------------
# Weight matrices
# ---------------------------------------------------------------------------

WEIGHTS_WITH_EMBEDDINGS = {
    "semantic": 0.20,
    "typeSignature": 0.12,
    "jsxStructure": 0.13,
    "hookProfile": 0.05,
    "imports": 0.05,
    "dataAccess": 0.03,
    "behavior": 0.02,
    "calleeSet": 0.10,
    "callSequence": 0.10,
    "consumerSet": 0.08,
    "coOccurrence": 0.07,
    "neighborhood": 0.05,
}

WEIGHTS_WITHOUT_EMBEDDINGS = {
    "typeSignature": 0.16,
    "jsxStructure": 0.16,
    "hookProfile": 0.06,
    "imports": 0.06,
    "dataAccess": 0.04,
    "behavior": 0.02,
    "calleeSet": 0.13,
    "callSequence": 0.13,
    "consumerSet": 0.10,
    "coOccurrence": 0.08,
    "neighborhood": 0.06,
}

# Component/hook only signals — dropped for non-component pairs
_COMPONENT_ONLY_SIGNALS = {"jsxStructure", "hookProfile"}

# Kinds that should be skipped entirely (structural, not behavioral)
_SKIP_KINDS = {"type", "enum", "constant", "interface", "typeAlias"}

# Cross-kind pairs that are allowed
_RELATED_KINDS = {
    frozenset({"component", "hook"}),
    frozenset({"hook", "function"}),
}


def _is_comparable(kind_a: str, kind_b: str) -> bool:
    """Check if two unit kinds should be compared."""
    if kind_a == kind_b:
        return True
    return frozenset({kind_a, kind_b}) in _RELATED_KINDS


def _get_weights(
    has_embeddings: bool,
    has_structural_patterns: bool,
    kind_a: str,
    kind_b: str,
) -> dict[str, float]:
    """Build the weight dict adapted to available signals and unit kinds."""
    base = dict(WEIGHTS_WITH_EMBEDDINGS if has_embeddings else WEIGHTS_WITHOUT_EMBEDDINGS)

    # If structural patterns available, take 0.05 proportionally from others
    if has_structural_patterns:
        total = sum(base.values())
        reduction = 0.05
        for k in base:
            base[k] *= (total - reduction) / total
        base["structuralPattern"] = 0.05

    # Drop inapplicable signals for cross-kind pairs
    is_both_components = kind_a == "component" and kind_b == "component"
    has_hooks = kind_a in ("component", "hook") and kind_b in ("component", "hook")

    signals_to_drop: set[str] = set()
    if not is_both_components:
        signals_to_drop.add("jsxStructure")
    if not has_hooks:
        signals_to_drop.add("hookProfile")

    for sig in signals_to_drop:
        base.pop(sig, None)

    # Renormalize
    total = sum(base.values())
    if total > 0:
        for k in base:
            base[k] /= total

    return base


# ---------------------------------------------------------------------------
# Signal functions — each returns float in [0, 1]
# ---------------------------------------------------------------------------


def sig_semantic(uid_a: str, uid_b: str, embeddings: dict[str, list[float]]) -> float:
    """Cosine similarity of purpose embeddings."""
    emb_a = embeddings.get(uid_a)
    emb_b = embeddings.get(uid_b)
    if emb_a is None or emb_b is None:
        return 0.0
    # Convert lists to sparse vectors for cosine_sim
    vec_a: SparseVector = {str(i): v for i, v in enumerate(emb_a)}
    vec_b: SparseVector = {str(i): v for i, v in enumerate(emb_b)}
    return cosine_sim(vec_a, vec_b)


def sig_type_signature(uid_a: str, uid_b: str, typesigs: dict[str, dict]) -> float:
    """Type signature similarity: strict hash match -> 1.0, loose -> 0.7, arity -> 0.4."""
    sig_a = typesigs.get(uid_a, {})
    sig_b = typesigs.get(uid_b, {})
    if not sig_a or not sig_b:
        return 0.0

    # Strict match
    if sig_a.get("strict_hash") and sig_a["strict_hash"] == sig_b.get("strict_hash"):
        return 1.0

    # Loose match
    if sig_a.get("loose_hash") and sig_a["loose_hash"] == sig_b.get("loose_hash"):
        return 0.7

    # Arity overlap
    arity_a = sig_a.get("arity", 0)
    arity_b = sig_b.get("arity", 0)
    if arity_a > 0 and arity_a == arity_b:
        return 0.4

    return 0.0


def sig_jsx_structure(
    uid_a: str, uid_b: str, fps: dict[str, dict], units_by_id: dict[str, dict]
) -> float:
    """Tree edit distance on JSX trees (components only)."""
    unit_a = units_by_id.get(uid_a, {})
    unit_b = units_by_id.get(uid_b, {})
    tree_a = unit_a.get("jsxTree")
    tree_b = unit_b.get("jsxTree")
    if tree_a is None or tree_b is None:
        return 0.0

    # Check exact hash first
    fp_a = fps.get(uid_a, {}).get("jsxHash", {})
    fp_b = fps.get(uid_b, {}).get("jsxHash", {})
    if fp_a.get("exact") and fp_a["exact"] == fp_b.get("exact"):
        return 1.0
    if fp_a.get("fuzzy") and fp_a["fuzzy"] == fp_b.get("fuzzy"):
        return 0.9

    return tree_edit_distance_normalized(tree_a, tree_b)


def sig_hook_profile(uid_a: str, uid_b: str, fps: dict[str, dict]) -> float:
    """Cosine similarity of hook profile vectors."""
    hp_a = fps.get(uid_a, {}).get("hookProfile", [])
    hp_b = fps.get(uid_b, {}).get("hookProfile", [])
    if not hp_a or not hp_b:
        return 0.0
    # Convert to sparse vectors
    vec_a: SparseVector = {str(i): float(v) for i, v in enumerate(hp_a) if v}
    vec_b: SparseVector = {str(i): float(v) for i, v in enumerate(hp_b) if v}
    return cosine_sim(vec_a, vec_b)


def sig_imports(uid_a: str, uid_b: str, fps: dict[str, dict]) -> float:
    """Cosine similarity of import constellation vectors."""
    ic_a = fps.get(uid_a, {}).get("importConstellation", {})
    ic_b = fps.get(uid_b, {}).get("importConstellation", {})
    return cosine_sim(ic_a, ic_b)


def sig_data_access(uid_a: str, uid_b: str, fps: dict[str, dict]) -> float:
    """Jaccard similarity on data source/store access sets."""
    dap_a = fps.get(uid_a, {}).get("dataAccessPattern", {})
    dap_b = fps.get(uid_b, {}).get("dataAccessPattern", {})
    if not dap_a and not dap_b:
        return 0.0
    return jaccard_sim(set(dap_a.keys()), set(dap_b.keys()))


def sig_behavior(uid_a: str, uid_b: str, fps: dict[str, dict]) -> float:
    """Normalized Hamming similarity of behavior flag vectors."""
    bf_a = fps.get(uid_a, {}).get("behaviorFlags", [])
    bf_b = fps.get(uid_b, {}).get("behaviorFlags", [])
    if not bf_a and not bf_b:
        return 1.0
    return normalized_hamming(bf_a, bf_b)


def sig_callee_set(uid_a: str, uid_b: str, cg: dict[str, dict]) -> float:
    """Cosine similarity of callee set vectors."""
    cv_a = cg.get(uid_a, {}).get("calleeSetVector", {})
    cv_b = cg.get(uid_b, {}).get("calleeSetVector", {})
    return cosine_sim(cv_a, cv_b)


def sig_call_sequence(uid_a: str, uid_b: str, cg: dict[str, dict]) -> float:
    """LCS-based similarity on call sequences, best across contexts."""
    seq_a = cg.get(uid_a, {}).get("sequenceHashes", {})
    seq_b = cg.get(uid_b, {}).get("sequenceHashes", {})

    # Also look at raw calleeSequence from units if available
    # Fall back to comparing sequence hashes if no raw sequences
    common_contexts = set(seq_a.keys()) & set(seq_b.keys())
    if not common_contexts:
        return 0.0

    # Hash-based: exact match on any context gives 1.0
    for ctx in common_contexts:
        if seq_a[ctx] == seq_b[ctx]:
            return 1.0

    # No exact match — return partial score based on having common contexts
    return 0.3 * len(common_contexts) / max(len(seq_a), len(seq_b))


def sig_consumer_set(uid_a: str, uid_b: str, units_by_id: dict[str, dict]) -> float:
    """Jaccard similarity on consumer sets, bonus for cross-directory overlap."""
    ua = units_by_id.get(uid_a, {})
    ub = units_by_id.get(uid_b, {})
    consumers_a = _extract_consumer_ids(ua)
    consumers_b = _extract_consumer_ids(ub)
    if not consumers_a and not consumers_b:
        return 0.0

    base = jaccard_sim(consumers_a, consumers_b)

    # Cross-directory bonus: if shared consumers span multiple directories
    shared = consumers_a & consumers_b
    if shared:
        dirs: set[str] = set()
        for cid in shared:
            cu = units_by_id.get(cid, {})
            fp = cu.get("filePath", "")
            if "/" in fp:
                dirs.add(fp.rsplit("/", 1)[0])
        if len(dirs) > 1:
            base = min(1.0, base * 1.2)

    return base


def _extract_consumer_ids(unit: dict) -> set[str]:
    """Extract consumer unit IDs from a unit dict."""
    ids: set[str] = set()
    for c in unit.get("consumers", []):
        cid = resolve_consumer_id(c)
        if cid:
            ids.add(cid)
    return ids


def sig_cooccurrence(uid_a: str, uid_b: str, dc: dict[str, dict]) -> float:
    """Cosine similarity of co-occurrence vectors."""
    cv_a = dc.get(uid_a, {}).get("cooccurrenceVector", {})
    cv_b = dc.get(uid_b, {}).get("cooccurrenceVector", {})
    return cosine_sim(cv_a, cv_b)


def sig_neighborhood(uid_a: str, uid_b: str, dc: dict[str, dict]) -> float:
    """Hash match on neighborhood hashes: r1 match -> 1.0, r2 match -> 0.6."""
    dc_a = dc.get(uid_a, {})
    dc_b = dc.get(uid_b, {})
    r1_a = dc_a.get("neighborhoodHash_r1")
    r1_b = dc_b.get("neighborhoodHash_r1")
    if r1_a and r1_a == r1_b:
        return 1.0
    r2_a = dc_a.get("neighborhoodHash_r2")
    r2_b = dc_b.get("neighborhoodHash_r2")
    if r2_a and r2_a == r2_b:
        return 0.6
    return 0.0


def sig_structural_pattern(uid_a: str, uid_b: str, patterns: dict[str, list[str]]) -> float:
    """Jaccard similarity on ast-grep pattern tag sets."""
    pa = patterns.get(uid_a, [])
    pb = patterns.get(uid_b, [])
    if not pa and not pb:
        return 0.0
    return jaccard_sim(set(pa), set(pb))


# ---------------------------------------------------------------------------
# Main scoring
# ---------------------------------------------------------------------------


def _load_scoring_artifacts(output_dir: Path) -> dict:
    """Load all Stage 2 artifacts needed for scoring."""
    artifacts = {
        "units": read_code_units(output_dir),
        "fps": read_artifact("structural-fingerprints.json", output_dir),
        "typesigs": read_artifact("type-signatures.json", output_dir),
        "cg": read_artifact("call-graph.json", output_dir),
        "dc": read_artifact("dependency-context.json", output_dir),
        "embeddings": {},
        "structural_patterns": {},
    }
    with contextlib.suppress(FileNotFoundError):
        artifacts["embeddings"] = read_artifact("semantic-embeddings.json", output_dir)
    with contextlib.suppress(FileNotFoundError):
        artifacts["structural_patterns"] = read_artifact("structural-patterns.json", output_dir)
    return artifacts


# Map signal name → (function, artifact keys)
_SIGNAL_FUNCS = {
    "semantic": lambda a, b, art: sig_semantic(a, b, art["embeddings"]),
    "typeSignature": lambda a, b, art: sig_type_signature(a, b, art["typesigs"]),
    "jsxStructure": lambda a, b, art: sig_jsx_structure(a, b, art["fps"], art["units_by_id"]),
    "hookProfile": lambda a, b, art: sig_hook_profile(a, b, art["fps"]),
    "imports": lambda a, b, art: sig_imports(a, b, art["fps"]),
    "dataAccess": lambda a, b, art: sig_data_access(a, b, art["fps"]),
    "behavior": lambda a, b, art: sig_behavior(a, b, art["fps"]),
    "calleeSet": lambda a, b, art: sig_callee_set(a, b, art["cg"]),
    "callSequence": lambda a, b, art: sig_call_sequence(a, b, art["cg"]),
    "consumerSet": lambda a, b, art: sig_consumer_set(a, b, art["units_by_id"]),
    "coOccurrence": lambda a, b, art: sig_cooccurrence(a, b, art["dc"]),
    "neighborhood": lambda a, b, art: sig_neighborhood(a, b, art["dc"]),
    "structuralPattern": lambda a, b, art: sig_structural_pattern(a, b, art["structural_patterns"]),
}


def _score_pair(
    uid_a: str,
    uid_b: str,
    weights: dict[str, float],
    artifacts: dict,
) -> dict[str, float]:
    """Compute all applicable signal scores for a unit pair."""
    signals: dict[str, float] = {}
    for sig_name in weights:
        func = _SIGNAL_FUNCS.get(sig_name)
        if func:
            signals[sig_name] = func(uid_a, uid_b, artifacts)
    return signals


def compute_scores(output_dir: Path, threshold: float = 0.35) -> None:
    """Compute pairwise similarity scores and write similarity-matrix.json."""
    artifacts = _load_scoring_artifacts(output_dir)
    units = artifacts["units"]

    units_by_id: dict[str, dict] = {u["id"]: u for u in units if u.get("id")}
    artifacts["units_by_id"] = units_by_id

    has_embeddings = bool(artifacts["embeddings"])
    has_structural_patterns = bool(artifacts["structural_patterns"])

    candidate_ids = [uid for uid, u in units_by_id.items() if u.get("kind", "") not in _SKIP_KINDS]
    file_of = {uid: units_by_id[uid].get("filePath", "") for uid in candidate_ids}

    total_pairs = 0
    scored_pairs: list[dict] = []
    n = len(candidate_ids)
    max_pairs = n * (n - 1) // 2
    print(f"  Scoring {n} units ({max_pairs} potential pairs)...", file=sys.stderr)

    _last_pct = -1
    for i in range(n):
        uid_a = candidate_ids[i]
        kind_a = units_by_id[uid_a].get("kind", "")
        file_a = file_of[uid_a]

        # Progress: report every 10%
        pct = (i * 100) // n if n else 100
        if pct // 10 > _last_pct // 10:
            _last_pct = pct
            print(
                f"  ... {pct}% ({total_pairs} pairs scored, {len(scored_pairs)} above threshold)",
                file=sys.stderr,
            )

        for j in range(i + 1, n):
            uid_b = candidate_ids[j]
            kind_b = units_by_id[uid_b].get("kind", "")

            if file_a and file_of[uid_b] and file_a == file_of[uid_b]:
                continue
            if not _is_comparable(kind_a, kind_b):
                continue

            total_pairs += 1
            weights = _get_weights(has_embeddings, has_structural_patterns, kind_a, kind_b)
            signals = _score_pair(uid_a, uid_b, weights, artifacts)

            score = sum(weights.get(s, 0.0) * v for s, v in signals.items())
            if score >= threshold:
                dominant = max(signals, key=lambda s: signals[s]) if signals else ""
                scored_pairs.append(
                    {
                        "unitA": uid_a,
                        "unitB": uid_b,
                        "score": round(score, 4),
                        "signals": {k: round(v, 4) for k, v in signals.items()},
                        "dominantSignal": dominant,
                    }
                )

    scored_pairs.sort(key=lambda p: p["score"], reverse=True)
    print(
        f"  Compared {total_pairs} pairs, {len(scored_pairs)} above threshold {threshold}.",
        file=sys.stderr,
    )
    write_artifact("similarity-matrix.json", scored_pairs, output_dir)
