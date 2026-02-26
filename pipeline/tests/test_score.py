"""Tests for scoring logic — weight adaptation and signal functions."""

from drift_semantic.score import (
    _get_weights,
    _is_comparable,
    sig_behavior,
    sig_callee_set,
    sig_cooccurrence,
    sig_hook_profile,
    sig_imports,
    sig_jsx_structure,
    sig_neighborhood,
    sig_type_signature,
)


class TestIsComparable:
    def test_same_kind(self):
        assert _is_comparable("component", "component") is True
        assert _is_comparable("function", "function") is True

    def test_related_kinds(self):
        assert _is_comparable("component", "hook") is True
        assert _is_comparable("hook", "function") is True

    def test_unrelated_kinds(self):
        assert _is_comparable("component", "function") is False
        assert _is_comparable("type", "component") is False


class TestGetWeights:
    def test_sums_to_1(self):
        w = _get_weights(False, False, "component", "component")
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_sums_to_1_with_embeddings(self):
        w = _get_weights(True, False, "component", "component")
        assert abs(sum(w.values()) - 1.0) < 1e-6
        assert "semantic" in w

    def test_sums_to_1_with_patterns(self):
        w = _get_weights(False, True, "function", "function")
        assert abs(sum(w.values()) - 1.0) < 1e-6
        assert "structuralPattern" in w

    def test_jsx_dropped_for_non_components(self):
        w = _get_weights(False, False, "function", "function")
        assert "jsxStructure" not in w
        assert "hookProfile" not in w

    def test_jsx_present_for_components(self):
        w = _get_weights(False, False, "component", "component")
        assert "jsxStructure" in w

    def test_hooks_present_for_component_hook(self):
        w = _get_weights(False, False, "component", "hook")
        assert "hookProfile" in w
        # But jsxStructure dropped (not both components)
        assert "jsxStructure" not in w

    def test_no_embeddings_means_no_semantic(self):
        w = _get_weights(False, False, "component", "component")
        assert "semantic" not in w


class TestSigTypeSignature:
    def test_strict_match(self):
        sigs = {
            "a": {"strict_hash": "abc", "loose_hash": "xyz", "arity": 2},
            "b": {"strict_hash": "abc", "loose_hash": "xyz", "arity": 2},
        }
        assert sig_type_signature("a", "b", sigs) == 1.0

    def test_loose_match(self):
        sigs = {
            "a": {"strict_hash": "abc", "loose_hash": "xyz", "arity": 2},
            "b": {"strict_hash": "def", "loose_hash": "xyz", "arity": 2},
        }
        assert sig_type_signature("a", "b", sigs) == 0.7

    def test_arity_match(self):
        sigs = {
            "a": {"strict_hash": "abc", "loose_hash": "xyz", "arity": 3},
            "b": {"strict_hash": "def", "loose_hash": "uvw", "arity": 3},
        }
        assert sig_type_signature("a", "b", sigs) == 0.4

    def test_no_match(self):
        sigs = {
            "a": {"strict_hash": "abc", "loose_hash": "xyz", "arity": 1},
            "b": {"strict_hash": "def", "loose_hash": "uvw", "arity": 2},
        }
        assert sig_type_signature("a", "b", sigs) == 0.0

    def test_missing_unit(self):
        assert sig_type_signature("a", "b", {}) == 0.0

    def test_zero_arity_no_match(self):
        sigs = {
            "a": {"strict_hash": "abc", "loose_hash": "xyz", "arity": 0},
            "b": {"strict_hash": "def", "loose_hash": "uvw", "arity": 0},
        }
        assert sig_type_signature("a", "b", sigs) == 0.0


class TestSigJsxStructure:
    def test_exact_hash_match(self):
        fps = {
            "a": {"jsxHash": {"exact": "same", "fuzzy": "f1"}},
            "b": {"jsxHash": {"exact": "same", "fuzzy": "f2"}},
        }
        units = {
            "a": {"jsxTree": {"tag": "div", "children": []}},
            "b": {"jsxTree": {"tag": "div", "children": []}},
        }
        assert sig_jsx_structure("a", "b", fps, units) == 1.0

    def test_fuzzy_hash_match(self):
        fps = {
            "a": {"jsxHash": {"exact": "e1", "fuzzy": "same"}},
            "b": {"jsxHash": {"exact": "e2", "fuzzy": "same"}},
        }
        units = {
            "a": {"jsxTree": {"tag": "div", "children": []}},
            "b": {"jsxTree": {"tag": "div", "children": []}},
        }
        assert sig_jsx_structure("a", "b", fps, units) == 0.9

    def test_no_jsx_tree(self):
        fps = {"a": {"jsxHash": {}}, "b": {"jsxHash": {}}}
        units = {"a": {}, "b": {}}
        assert sig_jsx_structure("a", "b", fps, units) == 0.0


class TestSigHookProfile:
    def test_identical_profiles(self):
        fps = {
            "a": {"hookProfile": [3, 1, 0, 0, 0, 0, 0, 0, 0, 0]},
            "b": {"hookProfile": [3, 1, 0, 0, 0, 0, 0, 0, 0, 0]},
        }
        assert abs(sig_hook_profile("a", "b", fps) - 1.0) < 1e-9

    def test_empty_profiles(self):
        fps = {"a": {"hookProfile": []}, "b": {"hookProfile": []}}
        assert sig_hook_profile("a", "b", fps) == 0.0


class TestSigNeighborhood:
    def test_r1_match(self):
        dc = {
            "a": {"neighborhoodHash_r1": "same", "neighborhoodHash_r2": "x"},
            "b": {"neighborhoodHash_r1": "same", "neighborhoodHash_r2": "y"},
        }
        assert sig_neighborhood("a", "b", dc) == 1.0

    def test_r2_match(self):
        dc = {
            "a": {"neighborhoodHash_r1": "x", "neighborhoodHash_r2": "same"},
            "b": {"neighborhoodHash_r1": "y", "neighborhoodHash_r2": "same"},
        }
        assert sig_neighborhood("a", "b", dc) == 0.6

    def test_no_match(self):
        dc = {
            "a": {"neighborhoodHash_r1": "x", "neighborhoodHash_r2": "y"},
            "b": {"neighborhoodHash_r1": "p", "neighborhoodHash_r2": "q"},
        }
        assert sig_neighborhood("a", "b", dc) == 0.0


class TestSigBehavior:
    def test_identical(self):
        fps = {
            "a": {"behaviorFlags": [1, 0, 1, 0, 0, 0, 0, 1]},
            "b": {"behaviorFlags": [1, 0, 1, 0, 0, 0, 0, 1]},
        }
        assert sig_behavior("a", "b", fps) == 1.0

    def test_completely_different(self):
        fps = {
            "a": {"behaviorFlags": [1, 1, 1, 1, 0, 0, 0, 0]},
            "b": {"behaviorFlags": [0, 0, 0, 0, 1, 1, 1, 1]},
        }
        assert sig_behavior("a", "b", fps) == 0.0

    def test_both_empty(self):
        fps = {"a": {}, "b": {}}
        assert sig_behavior("a", "b", fps) == 1.0
