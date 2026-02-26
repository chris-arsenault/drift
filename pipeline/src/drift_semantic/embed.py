"""Stage 2b: Semantic embedding via Ollama (optional).

Only runs if purpose-statements.json exists and an Ollama URL is provided.
Embeds each purpose statement using a local Ollama instance and writes
semantic-embeddings.json.
"""

import sys
from pathlib import Path

from .io_utils import read_artifact, write_artifact

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


def _load_purposes(output_dir: Path) -> list:
    """Load and validate purpose-statements.json."""
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
    return purposes


def _connect_ollama(ollama_url: str):
    """Connect to Ollama and return (client, base_url). Exits on failure."""
    if httpx is None:
        print(
            "Error: httpx is required for embedding. "
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


def embed_purposes(
    output_dir: Path,
    ollama_url: str,
    model: str = "nomic-embed-text",
) -> None:
    """Embed purpose statements via Ollama API."""
    purposes = _load_purposes(output_dir)
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
    print(f"\n  Embedded {len(embeddings)}/{total} purpose statements.", file=sys.stderr)
    write_artifact("semantic-embeddings.json", embeddings, output_dir)
