"""Tests for call graph vector computation."""

import math

from drift_semantic.callgraph import (
    _compute_callee_idf,
    callee_set_vector,
    chain_pattern_hashes,
    depth_profile,
    sequence_hashes,
)


class TestCalleeIdf:
    def test_single_callee_one_unit(self):
        units = [{"callees": [{"target": "foo"}]}]
        idf = _compute_callee_idf(units)
        assert idf["foo"] == 0.0  # log(1/1)

    def test_rare_callee_higher_idf(self):
        units = [
            {"callees": [{"target": "common"}, {"target": "rare"}]},
            {"callees": [{"target": "common"}]},
        ]
        idf = _compute_callee_idf(units)
        assert idf["rare"] > idf["common"]
        assert abs(idf["common"] - math.log(2 / 2)) < 1e-9  # log(1) = 0
        assert abs(idf["rare"] - math.log(2 / 1)) < 1e-9

    def test_deduplicates_within_unit(self):
        # Same callee appearing twice in one unit only counts as 1 doc
        units = [{"callees": [{"target": "foo"}, {"target": "foo"}]}]
        idf = _compute_callee_idf(units)
        assert abs(idf["foo"] - 0.0) < 1e-9

    def test_string_format(self):
        units = [{"callees": ["foo", "bar"]}]
        idf = _compute_callee_idf(units)
        assert "foo" in idf
        assert "bar" in idf


class TestCalleeSetVector:
    def test_basic(self):
        idf = {"foo": 1.0, "bar": 2.0}
        unit = {"callees": [{"target": "foo"}, {"target": "bar"}]}
        vec = callee_set_vector(unit, idf)
        assert vec["foo"] == 1.0
        assert vec["bar"] == 2.0

    def test_missing_callee_ignored(self):
        idf = {"foo": 1.0}
        unit = {"callees": [{"target": "unknown"}]}
        vec = callee_set_vector(unit, idf)
        assert len(vec) == 0

    def test_repeated_callee_accumulates(self):
        idf = {"foo": 1.5}
        unit = {"callees": [{"target": "foo"}, {"target": "foo"}]}
        vec = callee_set_vector(unit, idf)
        assert vec["foo"] == 3.0


class TestSequenceHashes:
    def test_empty(self):
        assert sequence_hashes({}) == {}
        assert sequence_hashes({"calleeSequence": "invalid"}) == {}

    def test_hashes_per_context(self):
        unit = {"calleeSequence": {"render": ["a", "b"], "effect": ["c"]}}
        result = sequence_hashes(unit)
        assert "render" in result
        assert "effect" in result
        assert result["render"] != result["effect"]

    def test_same_sequence_same_hash(self):
        u1 = {"calleeSequence": {"render": ["a", "b"]}}
        u2 = {"calleeSequence": {"render": ["a", "b"]}}
        assert sequence_hashes(u1)["render"] == sequence_hashes(u2)["render"]

    def test_different_sequence_different_hash(self):
        u1 = {"calleeSequence": {"render": ["a", "b"]}}
        u2 = {"calleeSequence": {"render": ["b", "a"]}}
        assert sequence_hashes(u1)["render"] != sequence_hashes(u2)["render"]

    def test_empty_list_skipped(self):
        unit = {"calleeSequence": {"render": [], "effect": ["a"]}}
        result = sequence_hashes(unit)
        assert "render" not in result
        assert "effect" in result


class TestChainPatternHashes:
    def test_empty(self):
        assert chain_pattern_hashes({}) == []
        assert chain_pattern_hashes({"chainPatterns": "invalid"}) == []

    def test_hashes(self):
        unit = {"chainPatterns": ["db.*.where().toArray()", "fetch().then()"]}
        result = chain_pattern_hashes(unit)
        assert len(result) == 2
        assert result[0] != result[1]

    def test_falsy_patterns_skipped(self):
        unit = {"chainPatterns": ["", None, "foo().bar()"]}
        result = chain_pattern_hashes(unit)
        assert len(result) == 1


class TestDepthProfile:
    def test_from_call_depth_dict(self):
        unit = {"callDepth": {"1": 5, "2": 3, "3": 1}}
        result = depth_profile(unit)
        assert result == [5, 3, 1]

    def test_deep_calls_summed(self):
        unit = {"callDepth": {"1": 2, "2": 1, "3": 3, "4": 2, "5": 1}}
        result = depth_profile(unit)
        assert result == [2, 1, 6]  # depth3plus = 3+2+1

    def test_int_keys(self):
        unit = {"callDepth": {1: 4, 2: 2}}
        result = depth_profile(unit)
        assert result == [4, 2, 0]

    def test_fallback_from_callees(self):
        unit = {"callees": [{"target": "a"}, {"target": "b"}, {"target": "a"}]}
        result = depth_profile(unit)
        assert result == [2, 0, 0]  # 2 unique callees

    def test_empty(self):
        result = depth_profile({})
        assert result == [0, 0, 0]
