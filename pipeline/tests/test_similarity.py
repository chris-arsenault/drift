"""Tests for similarity functions — hamming, LCS, tree edit distance."""

from drift_semantic.similarity import (
    lcs_ratio,
    normalized_hamming,
    sequence_similarity,
    tree_edit_distance_normalized,
)


class TestNormalizedHamming:
    def test_identical(self):
        assert normalized_hamming([1, 0, 1], [1, 0, 1]) == 1.0

    def test_completely_different(self):
        assert normalized_hamming([1, 1, 1], [0, 0, 0]) == 0.0

    def test_one_mismatch(self):
        # 1 of 4 differ → 0.75
        assert normalized_hamming([1, 0, 1, 0], [1, 0, 1, 1]) == 0.75

    def test_both_empty(self):
        assert normalized_hamming([], []) == 1.0

    def test_different_lengths(self):
        # [1, 0] vs [1, 0, 1] — 1 mismatch (position 2) out of max_len=3
        result = normalized_hamming([1, 0], [1, 0, 1])
        assert abs(result - 2 / 3) < 1e-9

    def test_single_element(self):
        assert normalized_hamming([1], [1]) == 1.0
        assert normalized_hamming([1], [0]) == 0.0


class TestLcsRatio:
    def test_identical(self):
        assert lcs_ratio(["a", "b", "c"], ["a", "b", "c"]) == 1.0

    def test_no_common(self):
        assert lcs_ratio(["a", "b"], ["c", "d"]) == 0.0

    def test_empty(self):
        assert lcs_ratio([], ["a"]) == 0.0
        assert lcs_ratio([], []) == 0.0

    def test_subsequence(self):
        # LCS of [a,b,c] and [a,c] is [a,c] length 2, max length 3 → 2/3
        result = lcs_ratio(["a", "b", "c"], ["a", "c"])
        assert abs(result - 2 / 3) < 1e-9

    def test_reversed(self):
        # LCS of [a,b,c] and [c,b,a] is length 1 (any single element), max 3 → 1/3
        result = lcs_ratio(["a", "b", "c"], ["c", "b", "a"])
        assert abs(result - 1 / 3) < 1e-9

    def test_interleaved(self):
        # [a, c, e] and [a, b, c, d, e] → LCS is [a, c, e] = 3, max = 5 → 3/5
        result = lcs_ratio(["a", "c", "e"], ["a", "b", "c", "d", "e"])
        assert abs(result - 3 / 5) < 1e-9

    def test_sequence_similarity_is_alias(self):
        a = ["x", "y", "z"]
        b = ["x", "z"]
        assert sequence_similarity(a, b) == lcs_ratio(a, b)


class TestTreeEditDistance:
    def test_identical_trees(self):
        tree = {"tag": "div", "children": [{"tag": "span", "children": []}]}
        assert tree_edit_distance_normalized(tree, tree) == 1.0

    def test_both_none(self):
        assert tree_edit_distance_normalized(None, None) == 0.0

    def test_one_none(self):
        tree = {"tag": "div", "children": []}
        assert tree_edit_distance_normalized(tree, None) == 0.0
        assert tree_edit_distance_normalized(None, tree) == 0.0

    def test_same_tag_no_children(self):
        a = {"tag": "div", "children": []}
        b = {"tag": "div", "children": []}
        # 1 matching node, total = 1+1 = 2, normalized = 2*1/2 = 1.0
        assert tree_edit_distance_normalized(a, b) == 1.0

    def test_different_tag_no_children(self):
        a = {"tag": "div", "children": []}
        b = {"tag": "span", "children": []}
        # 0 matching, total = 2, normalized = 0
        assert tree_edit_distance_normalized(a, b) == 0.0

    def test_partial_match(self):
        # div>span vs div>p — root matches, children don't
        a = {"tag": "div", "children": [{"tag": "span", "children": []}]}
        b = {"tag": "div", "children": [{"tag": "p", "children": []}]}
        # Matching: root div (1). Total nodes: 2+2=4. Score: 2*1/4 = 0.5
        assert tree_edit_distance_normalized(a, b) == 0.5

    def test_extra_children_ignored(self):
        # div>[span, p] vs div>[span] — greedy matching pairs by index
        a = {
            "tag": "div",
            "children": [
                {"tag": "span", "children": []},
                {"tag": "p", "children": []},
            ],
        }
        b = {"tag": "div", "children": [{"tag": "span", "children": []}]}
        # Matching: div(1) + span(1) = 2. Total: 3+2=5. Score: 4/5=0.8
        assert abs(tree_edit_distance_normalized(a, b) - 0.8) < 1e-9

    def test_nested_match(self):
        # div>section>span vs div>section>span — fully identical
        a = {
            "tag": "div",
            "children": [
                {"tag": "section", "children": [{"tag": "span", "children": []}]}
            ],
        }
        assert tree_edit_distance_normalized(a, a) == 1.0

    def test_text_children_ignored(self):
        # Non-dict children (text nodes) are not counted
        a = {"tag": "div", "children": ["hello", {"tag": "span", "children": []}]}
        b = {"tag": "div", "children": ["world", {"tag": "span", "children": []}]}
        assert tree_edit_distance_normalized(a, b) == 1.0
