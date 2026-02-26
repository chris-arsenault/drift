"""Stage 4: Clustering from similarity matrix.

Builds a graph from scored pairs, detects communities, enriches clusters
with metadata, and ranks them.
"""

import sys
from pathlib import Path

import networkx as nx

from .io_utils import read_artifact, read_code_units, write_artifact


def _build_graph(scored_pairs: list[dict], threshold: float) -> nx.Graph:
    """Build a NetworkX graph from scored pairs above threshold."""
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
    return G


def detect_communities(G: nx.Graph) -> list[set[str]]:
    """Detect communities using connected components.

    For large components (>5 members), attempt sub-clustering using
    greedy modularity optimization.
    """
    communities: list[set[str]] = []

    for component in nx.connected_components(G):
        if len(component) <= 5:
            communities.append(component)
        else:
            # Sub-cluster large components
            subgraph = G.subgraph(component).copy()
            try:
                sub_communities = nx.community.greedy_modularity_communities(
                    subgraph, weight="weight"
                )
                for sc in sub_communities:
                    if len(sc) >= 2:
                        communities.append(set(sc))
                    # Singletons from sub-clustering are dropped
            except Exception:
                # Fallback: keep as one cluster
                communities.append(component)

    return communities


def _get_signal_breakdown(members: set[str], scored_pairs: list[dict]) -> dict[str, float]:
    """Compute signal breakdown: fraction of total weight per signal."""
    signal_totals: dict[str, float] = {}
    edge_count = 0
    for pair in scored_pairs:
        if pair["unitA"] in members and pair["unitB"] in members:
            edge_count += 1
            for sig_name, sig_val in pair.get("signals", {}).items():
                signal_totals[sig_name] = signal_totals.get(sig_name, 0.0) + sig_val
    if edge_count == 0:
        return {}
    return {k: round(v / edge_count, 4) for k, v in signal_totals.items()}


def enrich_cluster(
    members: set[str],
    scored_pairs: list[dict],
    units_by_id: dict[str, dict],
) -> dict:
    """Enrich a cluster with metadata for ranking and reporting.

    Returns a dict with: members, avg_similarity, signal_breakdown,
    directory_spread, kind_mix, shared_callees, consumer_overlap.
    """
    member_list = sorted(members)

    # Average similarity (mean edge weight within cluster)
    weights: list[float] = []
    for pair in scored_pairs:
        if pair["unitA"] in members and pair["unitB"] in members:
            weights.append(pair["score"])
    avg_similarity = sum(weights) / len(weights) if weights else 0.0

    # Signal breakdown
    signal_breakdown = _get_signal_breakdown(members, scored_pairs)

    # Directory spread
    directories: set[str] = set()
    for uid in members:
        fp = units_by_id.get(uid, {}).get("filePath", "")
        if "/" in fp:
            # Use the app-level directory (first two path segments after apps/)
            parts = fp.split("/")
            if "apps" in parts:
                idx = parts.index("apps")
                if idx + 1 < len(parts):
                    directories.add(parts[idx + 1])
                else:
                    directories.add(fp.rsplit("/", 1)[0])
            else:
                directories.add(parts[0] if parts else fp)
    directory_spread = len(directories)

    # Kind mix
    kind_counts: dict[str, int] = {}
    for uid in members:
        kind = units_by_id.get(uid, {}).get("kind", "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    # Shared callees: callees appearing in >50% of members
    callee_counts: dict[str, int] = {}
    for uid in members:
        unit = units_by_id.get(uid, {})
        seen: set[str] = set()
        for callee in unit.get("callees", []):
            target = callee.get("target", callee) if isinstance(callee, dict) else str(callee)
            if target and target not in seen:
                seen.add(target)
                callee_counts[target] = callee_counts.get(target, 0) + 1
    threshold_count = len(members) / 2.0
    shared_callees = sorted(
        name for name, count in callee_counts.items() if count > threshold_count
    )

    # Consumer overlap: fraction of consumers shared between any two members
    all_consumer_sets: list[set[str]] = []
    for uid in members:
        unit = units_by_id.get(uid, {})
        consumers = unit.get("consumers", [])
        cids: set[str] = set()
        for c in consumers:
            if isinstance(c, dict):
                cid = c.get("id", c.get("unitId", ""))
            else:
                cid = str(c)
            if cid:
                cids.add(cid)
        all_consumer_sets.append(cids)

    consumer_overlap = 0.0
    overlap_count = 0
    for i in range(len(all_consumer_sets)):
        for j in range(i + 1, len(all_consumer_sets)):
            a = all_consumer_sets[i]
            b = all_consumer_sets[j]
            union = a | b
            if union:
                consumer_overlap += len(a & b) / len(union)
                overlap_count += 1
    if overlap_count > 0:
        consumer_overlap /= overlap_count

    return {
        "members": member_list,
        "memberCount": len(members),
        "avgSimilarity": round(avg_similarity, 4),
        "signalBreakdown": signal_breakdown,
        "directorySpread": directory_spread,
        "kindMix": kind_counts,
        "sharedCallees": shared_callees,
        "consumerOverlap": round(consumer_overlap, 4),
    }


def rank_clusters(clusters: list[dict]) -> list[dict]:
    """Rank clusters by: memberCount * avgSimilarity * directorySpread * kindBonus.

    Mixed-kind clusters get a 1.2x bonus.
    """
    for cluster in clusters:
        member_count = cluster["memberCount"]
        avg_sim = cluster["avgSimilarity"]
        dir_spread = max(cluster["directorySpread"], 1)
        kind_bonus = 1.2 if len(cluster["kindMix"]) > 1 else 1.0
        cluster["rankScore"] = round(member_count * avg_sim * dir_spread * kind_bonus, 4)

    clusters.sort(key=lambda c: c["rankScore"], reverse=True)

    # Assign IDs
    for i, cluster in enumerate(clusters):
        cluster["id"] = f"cluster-{i + 1:03d}"

    return clusters


def compute_clusters(output_dir: Path, threshold: float = 0.35) -> None:
    """Read similarity-matrix.json, cluster, enrich, rank, and write clusters.json."""
    scored_pairs = read_artifact("similarity-matrix.json", output_dir)
    units = read_code_units(output_dir)

    units_by_id: dict[str, dict] = {}
    for u in units:
        uid = u.get("id", "")
        if uid:
            units_by_id[uid] = u

    G = _build_graph(scored_pairs, threshold)
    print(
        f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.",
        file=sys.stderr,
    )

    communities = detect_communities(G)
    # Filter out singletons
    communities = [c for c in communities if len(c) >= 2]
    print(f"  Found {len(communities)} clusters.", file=sys.stderr)

    clusters: list[dict] = []
    for community in communities:
        enriched = enrich_cluster(community, scored_pairs, units_by_id)
        clusters.append(enriched)

    clusters = rank_clusters(clusters)
    write_artifact("clusters.json", clusters, output_dir)
