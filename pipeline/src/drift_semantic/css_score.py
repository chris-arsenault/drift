"""Stage 3b: CSS pairwise similarity scoring and clustering.

Reads css-units.json, computes pairwise similarity across 6 signals,
filters by threshold, and clusters via the existing cluster machinery.

Output: css-similarity.json, css-clusters.json
"""

import sys
import time
from collections import Counter
from pathlib import Path

from .io_utils import read_artifact, write_artifact
from .vectors import SparseVector, cosine_sim, jaccard_sim

# ---------------------------------------------------------------------------
# Signal weights
# ---------------------------------------------------------------------------

WEIGHTS: dict[str, float] = {
    "ruleExactMatch": 0.30,
    "ruleSetMatch": 0.25,
    "propertyFrequency": 0.20,
    "categoryProfile": 0.10,
    "customPropertyVocab": 0.10,
    "selectorPrefixOverlap": 0.05,
}

MIN_RULES = 3  # Skip files with fewer rules


# ---------------------------------------------------------------------------
# Signal functions — each returns float in [0, 1]
# ---------------------------------------------------------------------------


def _dice_coefficient(a: Counter, b: Counter) -> float:
    """Dice coefficient on two multisets (Counters).

    Dice = 2 * |intersection| / (|A| + |B|)
    where intersection counts min(countA, countB) for each element.
    """
    total_a = sum(a.values())
    total_b = sum(b.values())
    if total_a == 0 and total_b == 0:
        return 0.0
    intersection = 0
    for key in a:
        if key in b:
            intersection += min(a[key], b[key])
    return 2.0 * intersection / (total_a + total_b)


def sig_rule_exact_match(unit_a: dict, unit_b: dict) -> float:
    """Dice coefficient on propertyValueHash multisets.

    Catches exact copy-paste with renamed selectors.
    """
    hashes_a: Counter[str] = Counter()
    hashes_b: Counter[str] = Counter()
    for rule in unit_a.get("rules", []):
        h = rule.get("propertyValueHash")
        if h:
            hashes_a[h] += 1
    for rule in unit_b.get("rules", []):
        h = rule.get("propertyValueHash")
        if h:
            hashes_b[h] += 1
    return _dice_coefficient(hashes_a, hashes_b)


def sig_rule_set_match(unit_a: dict, unit_b: dict) -> float:
    """Dice coefficient on propertySetHash multisets.

    Catches same properties with different values (e.g. different CSS vars).
    """
    hashes_a: Counter[str] = Counter()
    hashes_b: Counter[str] = Counter()
    for rule in unit_a.get("rules", []):
        h = rule.get("propertySetHash")
        if h:
            hashes_a[h] += 1
    for rule in unit_b.get("rules", []):
        h = rule.get("propertySetHash")
        if h:
            hashes_b[h] += 1
    return _dice_coefficient(hashes_a, hashes_b)


def sig_property_frequency(unit_a: dict, unit_b: dict) -> float:
    """Cosine similarity on property-name frequency vectors."""
    pf_a: SparseVector = {k: float(v) for k, v in unit_a.get("propertyFrequency", {}).items()}
    pf_b: SparseVector = {k: float(v) for k, v in unit_b.get("propertyFrequency", {}).items()}
    return cosine_sim(pf_a, pf_b)


def sig_category_profile(unit_a: dict, unit_b: dict) -> float:
    """Cosine similarity on 7-element category profile vectors."""
    cp_a = unit_a.get("categoryProfile", [])
    cp_b = unit_b.get("categoryProfile", [])
    if not cp_a or not cp_b:
        return 0.0
    vec_a: SparseVector = {str(i): float(v) for i, v in enumerate(cp_a) if v}
    vec_b: SparseVector = {str(i): float(v) for i, v in enumerate(cp_b) if v}
    return cosine_sim(vec_a, vec_b)


def sig_custom_property_vocab(unit_a: dict, unit_b: dict) -> float:
    """Jaccard similarity on custom property reference sets.

    Files consuming the same design tokens.
    """
    refs_a = set(unit_a.get("customPropertyReferences", []))
    refs_b = set(unit_b.get("customPropertyReferences", []))
    return jaccard_sim(refs_a, refs_b)


def sig_selector_prefix_overlap(unit_a: dict, unit_b: dict) -> float:
    """Jaccard similarity on BEM prefix sets.

    Naming convention similarity.
    """
    prefs_a = set(unit_a.get("selectorPrefixes", []))
    prefs_b = set(unit_b.get("selectorPrefixes", []))
    return jaccard_sim(prefs_a, prefs_b)


# Map signal name to function
_SIGNAL_FUNCS: dict[str, callable] = {
    "ruleExactMatch": sig_rule_exact_match,
    "ruleSetMatch": sig_rule_set_match,
    "propertyFrequency": sig_property_frequency,
    "categoryProfile": sig_category_profile,
    "customPropertyVocab": sig_custom_property_vocab,
    "selectorPrefixOverlap": sig_selector_prefix_overlap,
}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_pair(unit_a: dict, unit_b: dict) -> tuple[float, dict[str, float]]:
    """Compute weighted similarity score for a CSS file pair."""
    signals: dict[str, float] = {}
    for sig_name, func in _SIGNAL_FUNCS.items():
        signals[sig_name] = func(unit_a, unit_b)

    score = sum(WEIGHTS.get(s, 0.0) * v for s, v in signals.items())
    return score, signals


def compute_css_scores(output_dir: Path, threshold: float = 0.40) -> None:
    """Score all CSS file pairs and write css-similarity.json."""
    t0 = time.time()
    raw = read_artifact("css-units.json", output_dir)
    units = raw.get("units", []) if isinstance(raw, dict) else raw

    # Filter out tiny files
    candidates = [u for u in units if u.get("ruleCount", 0) >= MIN_RULES]
    n = len(candidates)
    print(f"  Scoring {n} CSS files ({n * (n - 1) // 2} potential pairs)...", file=sys.stderr)

    scored_pairs: list[dict] = []
    total_compared = 0

    for i in range(n):
        ua = candidates[i]
        id_a = ua["id"]

        for j in range(i + 1, n):
            ub = candidates[j]
            id_b = ub["id"]

            total_compared += 1
            score, signals = _score_pair(ua, ub)

            if score >= threshold:
                dominant = max(signals, key=lambda s: signals[s]) if signals else ""
                scored_pairs.append(
                    {
                        "unitA": id_a,
                        "unitB": id_b,
                        "score": round(score, 4),
                        "signals": {k: round(v, 4) for k, v in signals.items()},
                        "dominantSignal": dominant,
                    }
                )

    scored_pairs.sort(key=lambda p: p["score"], reverse=True)
    elapsed = time.time() - t0
    print(
        f"  Compared {total_compared} pairs, {len(scored_pairs)} above threshold {threshold} "
        f"in {elapsed:.2f}s.",
        file=sys.stderr,
    )
    write_artifact("css-similarity.json", scored_pairs, output_dir)


# ---------------------------------------------------------------------------
# Clustering (reuses the existing cluster machinery)
# ---------------------------------------------------------------------------


def compute_css_clusters(output_dir: Path, threshold: float = 0.40) -> None:
    """Cluster CSS files from css-similarity.json and write css-clusters.json."""
    import networkx as nx

    scored_pairs = read_artifact("css-similarity.json", output_dir)
    raw = read_artifact("css-units.json", output_dir)
    units = raw.get("units", []) if isinstance(raw, dict) else raw
    units_by_id = {u["id"]: u for u in units if u.get("id")}

    # Build graph
    G = nx.Graph()
    for pair in scored_pairs:
        if pair["score"] >= threshold:
            G.add_edge(
                pair["unitA"],
                pair["unitB"],
                weight=pair["score"],
                signals=pair.get("signals", {}),
                dominantSignal=pair.get("dominantSignal", ""),
            )

    print(
        f"  CSS graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.",
        file=sys.stderr,
    )

    # Detect communities
    from .cluster import MIN_COMMUNITY_SIZE, detect_communities

    communities = detect_communities(G)
    communities = [c for c in communities if len(c) >= MIN_COMMUNITY_SIZE]
    print(f"  Found {len(communities)} CSS clusters.", file=sys.stderr)

    # Enrich clusters
    clusters: list[dict] = []
    for community in communities:
        enriched = _enrich_css_cluster(community, scored_pairs, units_by_id)
        clusters.append(enriched)

    # Rank and assign IDs
    for cluster in clusters:
        member_count = cluster["memberCount"]
        avg_sim = cluster["avgSimilarity"]
        dir_spread = max(cluster.get("directorySpread", 1), 1)
        cluster["rankScore"] = round(member_count * avg_sim * dir_spread, 4)

    clusters.sort(key=lambda c: c["rankScore"], reverse=True)
    for i, cluster in enumerate(clusters):
        cluster["id"] = f"css-cluster-{i + 1:03d}"

    write_artifact("css-clusters.json", clusters, output_dir)


def _enrich_css_cluster(  # noqa: C901, PLR0912
    members: set[str],
    scored_pairs: list[dict],
    units_by_id: dict[str, dict],
) -> dict:
    """Enrich a CSS cluster with metadata."""
    # Avg similarity
    weights = [
        pair["score"]
        for pair in scored_pairs
        if pair["unitA"] in members and pair["unitB"] in members
    ]
    avg_sim = sum(weights) / len(weights) if weights else 0.0

    # Signal breakdown
    signal_totals: dict[str, float] = {}
    edge_count = 0
    for pair in scored_pairs:
        if pair["unitA"] in members and pair["unitB"] in members:
            edge_count += 1
            for sig_name, sig_val in pair.get("signals", {}).items():
                signal_totals[sig_name] = signal_totals.get(sig_name, 0.0) + sig_val
    signal_breakdown = (
        {k: round(v / edge_count, 4) for k, v in signal_totals.items()} if edge_count else {}
    )

    # Directory spread
    directories: set[str] = set()
    for uid in members:
        fp = units_by_id.get(uid, {}).get("filePath", "")
        if "/" in fp:
            parts = fp.split("/")
            if "apps" in parts:
                idx = parts.index("apps")
                directories.add(parts[idx + 1] if idx + 1 < len(parts) else parts[0])
            else:
                directories.add(parts[0])

    # Linked components (from importedBy)
    linked_components: set[str] = set()
    for uid in members:
        for comp_id in units_by_id.get(uid, {}).get("importedBy", []):
            linked_components.add(comp_id)

    # Shared custom properties
    prop_sets: list[set[str]] = []
    for uid in members:
        refs = set(units_by_id.get(uid, {}).get("customPropertyReferences", []))
        if refs:
            prop_sets.append(refs)
    shared_props: set[str] = set()
    if len(prop_sets) >= 2:  # noqa: PLR2004
        shared_props = prop_sets[0]
        for ps in prop_sets[1:]:
            shared_props &= ps

    return {
        "members": sorted(members),
        "memberCount": len(members),
        "avgSimilarity": round(avg_sim, 4),
        "signalBreakdown": signal_breakdown,
        "directorySpread": len(directories),
        "linkedComponents": sorted(linked_components),
        "sharedCustomProperties": sorted(shared_props),
    }


# ---------------------------------------------------------------------------
# Intra-file scoring
# ---------------------------------------------------------------------------


def compute_intra_file_scores(output_dir: Path, threshold: float = 0.40) -> None:
    """Score prefix group pairs within each CSS file.

    Reads prefixGroups from css-units.json and compares groups within
    the same file using the same signal functions as inter-file scoring.
    Writes css-intra-similarity.json.
    """
    raw = read_artifact("css-units.json", output_dir)
    prefix_groups = raw.get("prefixGroups", []) if isinstance(raw, dict) else []

    if not prefix_groups:
        print("  No prefix groups for intra-file scoring.", file=sys.stderr)
        return

    # Group sub-units by file
    by_file: dict[str, list[dict]] = {}
    for pg in prefix_groups:
        fp = pg["filePath"]
        by_file.setdefault(fp, []).append(pg)

    scored_pairs: list[dict] = []
    total_compared = 0

    for file_path, groups in by_file.items():
        # Only score files with multiple groups
        n = len(groups)
        if n < 2:  # noqa: PLR2004
            continue

        for i in range(n):
            for j in range(i + 1, n):
                total_compared += 1
                score, signals = _score_pair(groups[i], groups[j])

                if score >= threshold:
                    dominant = max(signals, key=lambda s: signals[s]) if signals else ""
                    scored_pairs.append(
                        {
                            "unitA": groups[i]["id"],
                            "unitB": groups[j]["id"],
                            "prefixA": groups[i]["prefix"],
                            "prefixB": groups[j]["prefix"],
                            "rulesA": groups[i]["ruleCount"],
                            "rulesB": groups[j]["ruleCount"],
                            "score": round(score, 4),
                            "signals": {k: round(v, 4) for k, v in signals.items()},
                            "dominantSignal": dominant,
                            "filePath": file_path,
                        }
                    )

    scored_pairs.sort(key=lambda p: p["score"], reverse=True)
    print(
        f"  Intra-file: compared {total_compared} prefix pairs, "
        f"{len(scored_pairs)} above threshold {threshold}.",
        file=sys.stderr,
    )
    write_artifact("css-intra-similarity.json", scored_pairs, output_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(output_dir: Path, threshold: float = 0.40) -> None:
    """Entry point: score CSS pairs, intra-file groups, and cluster."""
    compute_css_scores(output_dir, threshold)
    compute_intra_file_scores(output_dir, threshold)
    compute_css_clusters(output_dir, threshold)
