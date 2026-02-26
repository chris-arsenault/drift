"""Stage 4: Clustering from similarity matrix.

Builds a graph from scored pairs, detects communities, enriches clusters
with metadata, and ranks them.
"""

import sys
from pathlib import Path

import networkx as nx

from .io_utils import read_artifact, read_code_units, resolve_consumer_id, write_artifact

SUBCLUSTER_THRESHOLD = 5
MIN_COMMUNITY_SIZE = 2


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
        if len(component) <= SUBCLUSTER_THRESHOLD:
            communities.append(component)
        else:
            # Sub-cluster large components
            subgraph = G.subgraph(component).copy()
            try:
                sub_communities = nx.community.greedy_modularity_communities(
                    subgraph, weight="weight"
                )
                for sc in sub_communities:
                    if len(sc) >= MIN_COMMUNITY_SIZE:
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


def _avg_similarity(members: set[str], scored_pairs: list[dict]) -> float:
    """Mean edge weight within a cluster."""
    weights = [
        pair["score"]
        for pair in scored_pairs
        if pair["unitA"] in members and pair["unitB"] in members
    ]
    return sum(weights) / len(weights) if weights else 0.0


def _directory_spread(members: set[str], units_by_id: dict[str, dict]) -> int:
    """Count distinct top-level directories for cluster members."""
    directories: set[str] = set()
    for uid in members:
        fp = units_by_id.get(uid, {}).get("filePath", "")
        if "/" not in fp:
            continue
        parts = fp.split("/")
        if "apps" in parts:
            idx = parts.index("apps")
            directories.add(parts[idx + 1] if idx + 1 < len(parts) else fp.rsplit("/", 1)[0])
        else:
            directories.add(parts[0] if parts else fp)
    return len(directories)


def _kind_mix(members: set[str], units_by_id: dict[str, dict]) -> dict[str, int]:
    """Count unit kinds within a cluster."""
    counts: dict[str, int] = {}
    for uid in members:
        kind = units_by_id.get(uid, {}).get("kind", "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _shared_callees(members: set[str], units_by_id: dict[str, dict]) -> list[str]:
    """Callees appearing in >50% of cluster members."""
    callee_counts: dict[str, int] = {}
    for uid in members:
        seen: set[str] = set()
        for callee in units_by_id.get(uid, {}).get("callees", []):
            target = callee.get("target", callee) if isinstance(callee, dict) else str(callee)
            if target and target not in seen:
                seen.add(target)
                callee_counts[target] = callee_counts.get(target, 0) + 1
    threshold = len(members) / 2.0
    return sorted(name for name, count in callee_counts.items() if count > threshold)


def _consumer_overlap(members: set[str], units_by_id: dict[str, dict]) -> float:
    """Mean pairwise Jaccard of consumer sets across cluster members."""
    consumer_sets: list[set[str]] = []
    for uid in members:
        cids: set[str] = set()
        for c in units_by_id.get(uid, {}).get("consumers", []):
            cid = resolve_consumer_id(c)
            if cid:
                cids.add(cid)
        consumer_sets.append(cids)

    total, count = 0.0, 0
    for i in range(len(consumer_sets)):
        for j in range(i + 1, len(consumer_sets)):
            union = consumer_sets[i] | consumer_sets[j]
            if union:
                total += len(consumer_sets[i] & consumer_sets[j]) / len(union)
                count += 1
    return total / count if count > 0 else 0.0


def enrich_cluster(
    members: set[str],
    scored_pairs: list[dict],
    units_by_id: dict[str, dict],
) -> dict:
    """Enrich a cluster with metadata for ranking and reporting."""
    return {
        "members": sorted(members),
        "memberCount": len(members),
        "avgSimilarity": round(_avg_similarity(members, scored_pairs), 4),
        "signalBreakdown": _get_signal_breakdown(members, scored_pairs),
        "directorySpread": _directory_spread(members, units_by_id),
        "kindMix": _kind_mix(members, units_by_id),
        "sharedCallees": _shared_callees(members, units_by_id),
        "consumerOverlap": round(_consumer_overlap(members, units_by_id), 4),
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
    communities = [c for c in communities if len(c) >= MIN_COMMUNITY_SIZE]
    print(f"  Found {len(communities)} clusters.", file=sys.stderr)

    clusters: list[dict] = []
    for community in communities:
        enriched = enrich_cluster(community, scored_pairs, units_by_id)
        clusters.append(enriched)

    clusters = rank_clusters(clusters)
    write_artifact("clusters.json", clusters, output_dir)
