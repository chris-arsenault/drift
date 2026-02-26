"""Similarity functions for Stage 3 scoring.

Each function returns a float in [0, 1] where 1 means identical.
"""

from .vectors import SparseVector, cosine_sim, jaccard_sim


def cosine_similarity(a: SparseVector, b: SparseVector) -> float:
    """Cosine similarity between two sparse vectors."""
    return cosine_sim(a, b)


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    return jaccard_sim(set_a, set_b)


def normalized_hamming(a: list[int], b: list[int]) -> float:
    """Normalized Hamming similarity: 1 - (hamming_distance / len).

    Both vectors must have the same length.  Returns 1.0 for two empty vectors.
    """
    if not a and not b:
        return 1.0
    if len(a) != len(b):
        min_len = min(len(a), len(b))
        max_len = max(len(a), len(b))
        mismatches = max_len - min_len
        for i in range(min_len):
            if a[i] != b[i]:
                mismatches += 1
        return 1.0 - (mismatches / max_len)
    distance = sum(1 for x, y in zip(a, b) if x != y)
    return 1.0 - (distance / len(a))


def lcs_ratio(seq_a: list[str], seq_b: list[str]) -> float:
    """Longest common subsequence length divided by max(len(a), len(b)).

    Returns 0.0 when both sequences are empty.
    """
    if not seq_a or not seq_b:
        return 0.0
    n = len(seq_a)
    m = len(seq_b)
    # DP table — only need two rows
    prev = [0] * (m + 1)
    curr = [0] * (m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if seq_a[i - 1] == seq_b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (m + 1)
    lcs_len = prev[m]
    return lcs_len / max(n, m)


def _count_tree_nodes(tree: dict | None) -> int:
    """Recursively count nodes in a JSX-style tree."""
    if tree is None:
        return 0
    count = 1
    for child in tree.get("children", []):
        if isinstance(child, dict):
            count += _count_tree_nodes(child)
    return count


def _count_matching_nodes(tree_a: dict | None, tree_b: dict | None) -> int:
    """Recursively count nodes that match between two trees.

    Matching: same tag name at the same structural position.
    Children are matched greedily in order.
    """
    if tree_a is None or tree_b is None:
        return 0

    matching = 0
    tag_a = tree_a.get("tag", "")
    tag_b = tree_b.get("tag", "")
    if tag_a == tag_b:
        matching = 1

    children_a = [c for c in tree_a.get("children", []) if isinstance(c, dict)]
    children_b = [c for c in tree_b.get("children", []) if isinstance(c, dict)]

    # Greedy ordered matching: pair children by index
    for ca, cb in zip(children_a, children_b):
        matching += _count_matching_nodes(ca, cb)

    return matching


def tree_edit_distance_normalized(tree_a: dict | None, tree_b: dict | None) -> float:
    """Simplified tree similarity: matching_nodes / total_nodes.

    Returns 0.0 when both trees are None.
    """
    if tree_a is None and tree_b is None:
        return 0.0
    total_a = _count_tree_nodes(tree_a)
    total_b = _count_tree_nodes(tree_b)
    total = total_a + total_b
    if total == 0:
        return 0.0
    matching = _count_matching_nodes(tree_a, tree_b)
    # matching counts once per matched pair; total counts each tree separately.
    # Normalize so perfect match = 1.0: 2 * matching / total
    return min(1.0, (2.0 * matching) / total)


def hash_match(
    h1: str | None,
    h2: str | None,
    strict_score: float = 1.0,
    loose_score: float = 0.0,
) -> float:
    """Score based on exact hash string comparison.

    Returns *strict_score* on match, *loose_score* otherwise.
    Returns 0.0 if either hash is None.
    """
    if h1 is None or h2 is None:
        return 0.0
    if h1 == h2:
        return strict_score
    return loose_score


def sequence_similarity(seq_a: list[str], seq_b: list[str]) -> float:
    """LCS-based similarity between two string sequences."""
    return lcs_ratio(seq_a, seq_b)
