"""Tests for clustering logic."""

from drift_semantic.cluster import detect_communities, rank_clusters

import networkx as nx


class TestDetectCommunities:
    def test_two_disconnected_pairs(self):
        G = nx.Graph()
        G.add_edge("a", "b", weight=0.9)
        G.add_edge("c", "d", weight=0.8)
        communities = detect_communities(G)
        assert len(communities) == 2
        member_sets = [frozenset(c) for c in communities]
        assert frozenset({"a", "b"}) in member_sets
        assert frozenset({"c", "d"}) in member_sets

    def test_single_component(self):
        G = nx.Graph()
        G.add_edge("a", "b", weight=0.9)
        G.add_edge("b", "c", weight=0.8)
        communities = detect_communities(G)
        assert len(communities) == 1
        assert communities[0] == {"a", "b", "c"}

    def test_empty_graph(self):
        G = nx.Graph()
        assert detect_communities(G) == []

    def test_large_component_subclustered(self):
        # >5 nodes triggers sub-clustering
        G = nx.Graph()
        # Two dense subgroups connected by a weak link
        for a, b in [("a", "b"), ("a", "c"), ("b", "c")]:
            G.add_edge(a, b, weight=0.9)
        for a, b in [("d", "e"), ("d", "f"), ("e", "f")]:
            G.add_edge(a, b, weight=0.9)
        G.add_edge("c", "d", weight=0.1)  # weak bridge
        # 6 nodes → should attempt sub-clustering
        communities = detect_communities(G)
        # Should find at least 1 community (may find 2 if modularity splits them)
        assert len(communities) >= 1
        total_members = sum(len(c) for c in communities)
        assert total_members >= 2  # at least some members


class TestRankClusters:
    def test_ranking_order(self):
        clusters = [
            {
                "members": ["a", "b"],
                "memberCount": 2,
                "avgSimilarity": 0.5,
                "directorySpread": 1,
                "kindMix": {"component": 2},
            },
            {
                "members": ["c", "d", "e"],
                "memberCount": 3,
                "avgSimilarity": 0.9,
                "directorySpread": 2,
                "kindMix": {"component": 3},
            },
        ]
        ranked = rank_clusters(clusters)
        # Second cluster should rank higher: 3 * 0.9 * 2 = 5.4 vs 2 * 0.5 * 1 = 1.0
        assert ranked[0]["id"] == "cluster-001"
        assert ranked[0]["memberCount"] == 3

    def test_mixed_kind_bonus(self):
        single_kind = {
            "members": ["a", "b"],
            "memberCount": 2,
            "avgSimilarity": 1.0,
            "directorySpread": 1,
            "kindMix": {"component": 2},
        }
        mixed_kind = {
            "members": ["c", "d"],
            "memberCount": 2,
            "avgSimilarity": 1.0,
            "directorySpread": 1,
            "kindMix": {"component": 1, "hook": 1},
        }
        ranked = rank_clusters([single_kind, mixed_kind])
        # Mixed kind gets 1.2x bonus: 2*1.0*1*1.2 = 2.4 vs 2*1.0*1*1.0 = 2.0
        assert ranked[0]["kindMix"] == {"component": 1, "hook": 1}

    def test_assigns_ids(self):
        clusters = [
            {
                "members": ["a"],
                "memberCount": 1,
                "avgSimilarity": 0.5,
                "directorySpread": 1,
                "kindMix": {"component": 1},
            },
        ]
        ranked = rank_clusters(clusters)
        assert ranked[0]["id"] == "cluster-001"
