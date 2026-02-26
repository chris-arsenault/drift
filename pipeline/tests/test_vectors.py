"""Tests for sparse vector math."""

import math

from drift_semantic.vectors import cosine_sim, dot, jaccard_sim, magnitude, normalize


class TestDot:
    def test_orthogonal(self):
        assert dot({"a": 1.0}, {"b": 1.0}) == 0.0

    def test_parallel(self):
        assert dot({"a": 2.0, "b": 3.0}, {"a": 4.0, "b": 5.0}) == 23.0

    def test_empty(self):
        assert dot({}, {"a": 1.0}) == 0.0
        assert dot({}, {}) == 0.0

    def test_partial_overlap(self):
        assert dot({"a": 1.0, "b": 2.0}, {"b": 3.0, "c": 4.0}) == 6.0

    def test_swaps_for_efficiency(self):
        # Iterates over the smaller vector — result must be the same
        big = {str(i): 1.0 for i in range(100)}
        small = {"0": 2.0, "50": 3.0}
        assert dot(big, small) == dot(small, big) == 5.0


class TestMagnitude:
    def test_unit_vector(self):
        assert magnitude({"a": 1.0}) == 1.0

    def test_3_4_5(self):
        assert magnitude({"a": 3.0, "b": 4.0}) == 5.0

    def test_empty(self):
        assert magnitude({}) == 0.0


class TestNormalize:
    def test_unit_length(self):
        v = normalize({"a": 3.0, "b": 4.0})
        assert abs(v["a"] - 0.6) < 1e-9
        assert abs(v["b"] - 0.8) < 1e-9

    def test_zero_vector(self):
        assert normalize({}) == {}

    def test_result_has_unit_magnitude(self):
        v = normalize({"x": 7.0, "y": 24.0})
        assert abs(magnitude(v) - 1.0) < 1e-9


class TestCosineSim:
    def test_identical(self):
        v = {"a": 1.0, "b": 2.0}
        assert abs(cosine_sim(v, v) - 1.0) < 1e-9

    def test_orthogonal(self):
        assert cosine_sim({"a": 1.0}, {"b": 1.0}) == 0.0

    def test_empty(self):
        assert cosine_sim({}, {"a": 1.0}) == 0.0
        assert cosine_sim({}, {}) == 0.0

    def test_antiparallel_clamped(self):
        # Negative cosine should be clamped to 0
        assert cosine_sim({"a": 1.0}, {"a": -1.0}) == 0.0

    def test_scaled_vectors(self):
        # Same direction, different magnitude → cosine = 1.0
        a = {"x": 1.0, "y": 2.0}
        b = {"x": 100.0, "y": 200.0}
        assert abs(cosine_sim(a, b) - 1.0) < 1e-9

    def test_known_angle(self):
        # 45 degrees: cos(pi/4) ≈ 0.7071
        a = {"x": 1.0, "y": 0.0}
        b = {"x": 1.0, "y": 1.0}
        expected = 1.0 / math.sqrt(2)
        assert abs(cosine_sim(a, b) - expected) < 1e-9


class TestJaccardSim:
    def test_identical(self):
        assert jaccard_sim({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert jaccard_sim({"a"}, {"b"}) == 0.0

    def test_empty(self):
        assert jaccard_sim(set(), set()) == 0.0

    def test_partial_overlap(self):
        # {a,b} ∩ {b,c} = {b}, union = {a,b,c} → 1/3
        assert abs(jaccard_sim({"a", "b"}, {"b", "c"}) - 1 / 3) < 1e-9

    def test_subset(self):
        # {a} ∩ {a,b} = {a}, union = {a,b} → 1/2
        assert jaccard_sim({"a"}, {"a", "b"}) == 0.5
