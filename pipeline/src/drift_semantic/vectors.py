"""Sparse vector utilities using plain dicts.

Numpy is reserved for batch operations in score.py. These functions operate
on individual sparse vectors represented as ``dict[str, float]``.
"""

import math

SparseVector = dict[str, float]


def dot(a: SparseVector, b: SparseVector) -> float:
    """Dot product of two sparse vectors.

    Only iterates over keys present in the smaller vector for efficiency.
    """
    if len(a) > len(b):
        a, b = b, a
    total = 0.0
    for k, v in a.items():
        if k in b:
            total += v * b[k]
    return total


def magnitude(v: SparseVector) -> float:
    """Euclidean magnitude (L2 norm) of a sparse vector."""
    if not v:
        return 0.0
    return math.sqrt(sum(val * val for val in v.values()))


def normalize(v: SparseVector) -> SparseVector:
    """Return a unit-length copy of *v*.  Returns empty dict for zero vectors."""
    mag = magnitude(v)
    if mag == 0.0:
        return {}
    return {k: val / mag for k, val in v.items()}


def cosine_sim(a: SparseVector, b: SparseVector) -> float:
    """Cosine similarity in [0, 1].

    Returns 0.0 when either vector is zero-length.
    """
    if not a or not b:
        return 0.0
    d = dot(a, b)
    ma = magnitude(a)
    mb = magnitude(b)
    if ma == 0.0 or mb == 0.0:
        return 0.0
    sim = d / (ma * mb)
    # Clamp to [0, 1] to handle floating-point drift
    return max(0.0, min(1.0, sim))


def jaccard_sim(a: set, b: set) -> float:
    """Jaccard similarity between two sets.  Returns 0.0 for two empty sets."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return intersection / union
