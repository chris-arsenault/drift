"""Tests for CSS pairwise similarity scoring."""

from collections import Counter

from drift_semantic.css_score import (
    _dice_coefficient,
    sig_rule_exact_match,
    sig_rule_set_match,
    sig_property_frequency,
    sig_category_profile,
    sig_custom_property_vocab,
    sig_selector_prefix_overlap,
    _score_pair,
)


class TestDiceCoefficient:
    def test_identical(self):
        c = Counter({"a": 2, "b": 3})
        assert _dice_coefficient(c, c) == 1.0

    def test_disjoint(self):
        a = Counter({"a": 1})
        b = Counter({"b": 1})
        assert _dice_coefficient(a, b) == 0.0

    def test_partial_overlap(self):
        a = Counter({"a": 2, "b": 1})
        b = Counter({"a": 1, "c": 1})
        # intersection: min(2,1)=1 for 'a' -> 1
        # total_a=3, total_b=2
        # dice = 2*1 / (3+2) = 0.4
        assert abs(_dice_coefficient(a, b) - 0.4) < 0.001

    def test_empty(self):
        assert _dice_coefficient(Counter(), Counter()) == 0.0


class TestSignals:
    def _make_unit(self, **kwargs):
        """Helper to create a minimal CSS unit dict."""
        base = {
            "id": "test.css",
            "rules": [],
            "propertyFrequency": {},
            "categoryProfile": [],
            "customPropertyReferences": [],
            "selectorPrefixes": [],
        }
        base.update(kwargs)
        return base

    def test_exact_match_identical(self):
        rules = [
            {"propertyValueHash": "abc123", "propertySetHash": "xyz"},
            {"propertyValueHash": "def456", "propertySetHash": "xyz"},
        ]
        ua = self._make_unit(rules=rules)
        ub = self._make_unit(rules=rules)
        assert sig_rule_exact_match(ua, ub) == 1.0

    def test_exact_match_disjoint(self):
        ua = self._make_unit(rules=[{"propertyValueHash": "aaa", "propertySetHash": "x"}])
        ub = self._make_unit(rules=[{"propertyValueHash": "bbb", "propertySetHash": "y"}])
        assert sig_rule_exact_match(ua, ub) == 0.0

    def test_set_match_same_props_different_values(self):
        # Same propertySetHash means same properties, different values
        ua = self._make_unit(rules=[
            {"propertyValueHash": "val-a", "propertySetHash": "shared-hash"},
        ])
        ub = self._make_unit(rules=[
            {"propertyValueHash": "val-b", "propertySetHash": "shared-hash"},
        ])
        assert sig_rule_set_match(ua, ub) == 1.0
        assert sig_rule_exact_match(ua, ub) == 0.0

    def test_property_frequency_cosine(self):
        ua = self._make_unit(propertyFrequency={"color": 3, "display": 2})
        ub = self._make_unit(propertyFrequency={"color": 3, "display": 2})
        assert sig_property_frequency(ua, ub) == 1.0

    def test_property_frequency_orthogonal(self):
        ua = self._make_unit(propertyFrequency={"color": 1})
        ub = self._make_unit(propertyFrequency={"display": 1})
        assert sig_property_frequency(ua, ub) == 0.0

    def test_category_profile_identical(self):
        profile = [5, 3, 2, 4, 1, 0, 0]
        ua = self._make_unit(categoryProfile=profile)
        ub = self._make_unit(categoryProfile=profile)
        assert sig_category_profile(ua, ub) == 1.0

    def test_category_profile_empty(self):
        ua = self._make_unit(categoryProfile=[])
        ub = self._make_unit(categoryProfile=[1, 0, 0, 0, 0, 0, 0])
        assert sig_category_profile(ua, ub) == 0.0

    def test_custom_property_vocab(self):
        ua = self._make_unit(customPropertyReferences=["--primary", "--bg", "--text"])
        ub = self._make_unit(customPropertyReferences=["--primary", "--bg", "--accent"])
        # Jaccard: |{primary,bg}| / |{primary,bg,text,accent}| = 2/4 = 0.5
        assert abs(sig_custom_property_vocab(ua, ub) - 0.5) < 0.001

    def test_selector_prefix_overlap(self):
        ua = self._make_unit(selectorPrefixes=["btn", "card", "modal"])
        ub = self._make_unit(selectorPrefixes=["btn", "card", "panel"])
        # Jaccard: 2/4 = 0.5
        assert abs(sig_selector_prefix_overlap(ua, ub) - 0.5) < 0.001


class TestScorePair:
    def _make_unit(self, **kwargs):
        base = {
            "id": "test.css",
            "rules": [],
            "propertyFrequency": {},
            "categoryProfile": [],
            "customPropertyReferences": [],
            "selectorPrefixes": [],
        }
        base.update(kwargs)
        return base

    def test_identical_units_score_high(self):
        rules = [
            {"propertyValueHash": "h1", "propertySetHash": "s1"},
            {"propertyValueHash": "h2", "propertySetHash": "s2"},
        ]
        unit = self._make_unit(
            rules=rules,
            propertyFrequency={"color": 2, "display": 1},
            categoryProfile=[2, 1, 0, 1, 0, 0, 0],
            customPropertyReferences=["--primary"],
            selectorPrefixes=["btn"],
        )
        score, signals = _score_pair(unit, unit)
        assert score > 0.9
        assert all(v >= 0.99 for v in signals.values())

    def test_disjoint_units_score_low(self):
        ua = self._make_unit(
            rules=[{"propertyValueHash": "a", "propertySetHash": "x"}],
            propertyFrequency={"color": 1},
            categoryProfile=[0, 0, 0, 1, 0, 0, 0],
            customPropertyReferences=["--a"],
            selectorPrefixes=["btn"],
        )
        ub = self._make_unit(
            rules=[{"propertyValueHash": "b", "propertySetHash": "y"}],
            propertyFrequency={"display": 1},
            categoryProfile=[1, 0, 0, 0, 0, 0, 0],
            customPropertyReferences=["--b"],
            selectorPrefixes=["card"],
        )
        score, signals = _score_pair(ua, ub)
        assert score < 0.1
