"""Tests for dependency context computation."""

import math

from drift_semantic.depcontext import (
    _shannon_entropy,
    cooccurrence_vector,
    consumer_profile,
    neighborhood_hash,
)


class TestShannonEntropy:
    def test_single_category(self):
        assert _shannon_entropy({"a": 10}) == 0.0

    def test_uniform_two(self):
        # 2 categories equally distributed → log2(2) = 1.0
        assert abs(_shannon_entropy({"a": 5, "b": 5}) - 1.0) < 1e-9

    def test_uniform_four(self):
        # 4 equal → log2(4) = 2.0
        assert abs(_shannon_entropy({"a": 1, "b": 1, "c": 1, "d": 1}) - 2.0) < 1e-9

    def test_empty(self):
        assert _shannon_entropy({}) == 0.0

    def test_skewed(self):
        # 99:1 split should be close to 0
        result = _shannon_entropy({"a": 99, "b": 1})
        assert result < 0.1


class TestConsumerProfile:
    def test_no_consumers(self):
        result = consumer_profile({})
        assert result == [0.0, 0.0, 0.0]

    def test_normalized_count_caps_at_1(self):
        # 100 consumers → capped at 1.0
        unit = {"consumerCount": 100}
        result = consumer_profile(unit)
        assert result[0] == 1.0

    def test_normalized_count_linear(self):
        # 25 consumers → 25/50 = 0.5
        unit = {"consumerCount": 25}
        result = consumer_profile(unit)
        assert result[0] == 0.5

    def test_kind_entropy(self):
        unit = {
            "consumerCount": 4,
            "consumerKinds": {"component": 2, "hook": 2},
        }
        result = consumer_profile(unit)
        assert abs(result[1] - 1.0) < 1e-9  # 2 equal kinds → entropy 1.0

    def test_kind_entropy_list_format(self):
        unit = {
            "consumerCount": 3,
            "consumerKinds": ["component", "component", "hook"],
        }
        result = consumer_profile(unit)
        # 2 component, 1 hook → -2/3*log2(2/3) - 1/3*log2(1/3)
        expected = -(2 / 3) * math.log2(2 / 3) - (1 / 3) * math.log2(1 / 3)
        assert abs(result[1] - expected) < 1e-9

    def test_directory_spread(self):
        unit = {
            "consumerCount": 3,
            "consumerDirectories": ["src/a", "src/b", "src/a"],
        }
        result = consumer_profile(unit)
        # 2 distinct dirs / 3 consumers = 0.667
        assert abs(result[2] - 2 / 3) < 1e-9


class TestCooccurrenceVector:
    def test_list_format(self):
        unit = {
            "coOccurrences": [
                {"unitId": "u1", "ratio": 0.8},
                {"unitId": "u2", "count": 3},
            ]
        }
        vec = cooccurrence_vector(unit)
        assert vec["u1"] == 0.8
        assert vec["u2"] == 3.0

    def test_dict_format(self):
        unit = {"coOccurrences": {"u1": 0.5, "u2": {"ratio": 0.7}}}
        vec = cooccurrence_vector(unit)
        assert vec["u1"] == 0.5
        assert vec["u2"] == 0.7

    def test_empty(self):
        assert cooccurrence_vector({}) == {}
        assert cooccurrence_vector({"coOccurrences": {}}) == {}


class TestNeighborhoodHash:
    def test_no_neighbors(self):
        graph = {"a": set()}
        h = neighborhood_hash("a", graph, 1)
        # Neighborhood is empty (self excluded)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256

    def test_radius_1(self):
        graph = {"a": {"b", "c"}, "b": {"a"}, "c": {"a"}}
        h1 = neighborhood_hash("a", graph, 1)
        # Should include b and c
        assert isinstance(h1, str)

    def test_radius_2_expands(self):
        graph = {"a": {"b"}, "b": {"c"}, "c": set()}
        h1 = neighborhood_hash("a", graph, 1)
        h2 = neighborhood_hash("a", graph, 2)
        # Radius 2 reaches c through b, so hash differs
        assert h1 != h2

    def test_same_neighborhood_same_hash(self):
        graph = {"a": {"b", "c"}, "b": set(), "c": set(), "x": {"b", "c"}, "y": set()}
        # a and x both connect to {b, c}
        assert neighborhood_hash("a", graph, 1) == neighborhood_hash("x", graph, 1)

    def test_self_excluded(self):
        # Node should not appear in its own neighborhood
        graph = {"a": {"a", "b"}}  # self-loop
        h_no_loop = neighborhood_hash("a", {"a": {"b"}}, 1)
        h_self_loop = neighborhood_hash("a", graph, 1)
        assert h_no_loop == h_self_loop
