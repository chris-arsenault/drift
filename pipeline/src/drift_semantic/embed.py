"""Stage 2b: Semantic embedding of purpose statements.

Embeds each purpose statement into a vector for pairwise semantic comparison.
Uses built-in TF-IDF by default (no external dependencies). Optionally uses
Ollama for higher-quality embeddings when available.

Writes semantic-embeddings.json: { unitId: [float, ...] }
"""

import math
import re
import sys
from collections import Counter
from pathlib import Path

from .io_utils import read_artifact, write_artifact

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

# Stopwords for TF-IDF tokenization (common English words that add noise)
_STOPWORDS = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "this", "to", "was", "were", "which", "with",
])


# ---------------------------------------------------------------------------
# TF-IDF embedding (built-in, no external dependencies)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alpha, remove stopwords and short tokens."""
    tokens = re.findall(r"[a-z][a-z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


def _build_tfidf_embeddings(purposes: list[dict]) -> dict[str, list[float]]:
    """Compute TF-IDF vectors for all purpose statements.

    Returns a dict mapping unitId → dense float vector.
    """
    # Tokenize all documents
    docs: list[tuple[str, list[str]]] = []
    for entry in purposes:
        unit_id = entry.get("unitId", "")
        purpose = entry.get("purpose", "")
        if unit_id and purpose:
            docs.append((unit_id, _tokenize(purpose)))

    if not docs:
        return {}

    # Build vocabulary and document frequencies
    doc_freq: Counter[str] = Counter()
    for _, tokens in docs:
        doc_freq.update(set(tokens))

    n_docs = len(docs)
    # Filter to terms appearing in at least 2 docs (useful for comparison)
    # but keep all if corpus is very small
    _min_df_threshold = 5
    min_df = 2 if n_docs > _min_df_threshold else 1
    vocab = sorted(t for t, df in doc_freq.items() if df >= min_df)

    if not vocab:
        # Fallback: use all terms
        vocab = sorted(doc_freq.keys())

    vocab_index = {term: i for i, term in enumerate(vocab)}
    n_terms = len(vocab)

    # Compute IDF
    idf = {term: math.log(n_docs / df) for term, df in doc_freq.items() if term in vocab_index}

    # Compute TF-IDF vectors
    embeddings: dict[str, list[float]] = {}
    for unit_id, tokens in docs:
        tf = Counter(tokens)
        vec = [0.0] * n_terms
        for term, count in tf.items():
            idx = vocab_index.get(term)
            if idx is not None:
                vec[idx] = count * idf.get(term, 0.0)

        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]

        embeddings[unit_id] = vec

    return embeddings


# ---------------------------------------------------------------------------
# Ollama embedding (optional, higher quality)
# ---------------------------------------------------------------------------


def _connect_ollama(ollama_url: str):
    """Connect to Ollama and return (client, base_url). Exits on failure."""
    if httpx is None:
        print(
            "Error: httpx is required for Ollama embedding. "
            "Install with: pip install drift-semantic[ollama]",
            file=sys.stderr,
        )
        sys.exit(1)

    url = ollama_url.rstrip("/")
    try:
        client = httpx.Client(timeout=30.0)
        client.get(f"{url}/api/tags")
    except httpx.ConnectError:
        print(f"Error: Cannot connect to Ollama at {url}.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error connecting to Ollama at {url}: {e}", file=sys.stderr)
        sys.exit(1)
    return client, url


def _build_ollama_embeddings(
    purposes: list[dict], ollama_url: str, model: str
) -> dict[str, list[float]]:
    """Embed purpose statements via Ollama API."""
    client, url = _connect_ollama(ollama_url)
    embed_url = f"{url}/api/embeddings"

    embeddings: dict[str, list[float]] = {}
    total = len(purposes)

    for i, entry in enumerate(purposes):
        unit_id = entry.get("unitId", "")
        purpose = entry.get("purpose", "")
        if not unit_id or not purpose:
            continue

        print(
            f"  Embedding {i + 1}/{total}: {unit_id[:60]}...",
            file=sys.stderr,
            end="\r",
        )

        try:
            resp = client.post(
                embed_url,
                json={"model": model, "prompt": purpose},
            )
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embedding", [])
            if embedding:
                embeddings[unit_id] = embedding
        except httpx.HTTPStatusError as e:
            print(
                f"\nWarning: Ollama returned {e.response.status_code} for "
                f"unit {unit_id}. Skipping.",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"\nWarning: Failed to embed unit {unit_id}: {e}",
                file=sys.stderr,
            )

    client.close()
    print(f"\n  Embedded {len(embeddings)}/{total} purpose statements via Ollama.", file=sys.stderr)
    return embeddings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_purposes(
    output_dir: Path,
    ollama_url: str | None = None,
    model: str = "nomic-embed-text",
) -> None:
    """Embed purpose statements and write semantic-embeddings.json.

    Uses built-in TF-IDF by default. If ollama_url is provided, uses Ollama
    for higher-quality embeddings instead.
    """
    purposes_path = output_dir / "purpose-statements.json"
    if not purposes_path.exists():
        print(
            "Error: purpose-statements.json not found in output directory. "
            "Run 'ingest-purposes' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    purposes = read_artifact("purpose-statements.json", output_dir)
    if not isinstance(purposes, list):
        print("Error: purpose-statements.json must be a JSON array.", file=sys.stderr)
        sys.exit(1)

    if ollama_url:
        embeddings = _build_ollama_embeddings(purposes, ollama_url, model)
    else:
        embeddings = _build_tfidf_embeddings(purposes)
        print(
            f"  Embedded {len(embeddings)} purpose statements via TF-IDF "
            f"({len(next(iter(embeddings.values()), []))} dimensions).",
            file=sys.stderr,
        )

    write_artifact("semantic-embeddings.json", embeddings, output_dir)


def embed_if_available(output_dir: Path) -> None:
    """Run embedding if purpose-statements.json exists, skip otherwise.

    Used by the `run` pipeline to include embed without failing when
    purpose statements haven't been generated yet.
    """
    purposes_path = output_dir / "purpose-statements.json"
    if not purposes_path.exists():
        print("  No purpose-statements.json found — skipping embed.", file=sys.stderr)
        return
    embed_purposes(output_dir)
