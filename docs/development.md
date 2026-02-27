# Development

## Prerequisites

- Node.js (any recent LTS)
- Python 3.10+
- ast-grep (`sg`) — optional

## Makefile Targets

```bash
make lint          # ESLint (extractor) + Ruff (pipeline)
make lint-fix      # Auto-fix both
make format        # Prettier (extractor) + Ruff format (pipeline)
make format-check  # Check without modifying
make test          # pytest (pipeline)
```

## Linting

**TypeScript (extractor/):** ESLint 9 flat config with typescript-eslint and sonarjs. Prettier for formatting. Cognitive complexity raised to 30 for AST walker code.

**Python (pipeline/):** Ruff for both linting and formatting. Key ignores:

- `C901`/`PLR0912` — AST processing and scoring pipeline are unavoidably complex
- `N803`/`N806` — `G` is idiomatic for networkx graphs
- `SIM105`/`SIM108` — explicit try/except and if/else are clearer in context
- `B905` — deliberate truncation in tree matching (no strict zip)

## Testing

Tests live in `pipeline/tests/`. Run with `make test` or `cd pipeline && python3 -m pytest tests/ -v`.

### Philosophy

Test **complicated logic only**: branching, regexes, math, similarity functions, hashing. Do not test:

- Things clearly correct by inspection (simple getters, trivial mappings)
- Code requiring expensive mocking (ts-morph AST nodes in the extractor)
- Integration/E2E flows (the CLI handles orchestration)

No coverage targets. The extractor has no unit tests — every exported function takes ts-morph `Node`/`SourceFile` objects, making fixture setup disproportionately expensive.

### What's Tested

| Module | What's tested |
|--------|---------------|
| `vectors.py` | dot product, cosine similarity, Jaccard, magnitude, normalize |
| `similarity.py` | normalized Hamming, LCS ratio, tree edit distance |
| `fingerprint.py` | JSX hash, hook profile, IDF, import constellation, behavior flags |
| `typesig.py` | type classification, normalize_type, strict/loose/arity hashing |
| `callgraph.py` | callee IDF, callee set vectors, sequence hashes, chain patterns |
| `depcontext.py` | Shannon entropy, consumer profile, co-occurrence, neighborhood hash |
| `score.py` | weight adaptation, comparability, all signal functions |
| `cluster.py` | community detection, cluster ranking |
| `css_extract.py` | comment stripping, declaration parsing, class/prefix extraction, rule parsing, fingerprinting, file aggregates |
| `css_score.py` | Dice coefficient, all 6 CSS signals, pairwise scoring |

## Conventions

- Python internal helpers use `_` prefix (e.g., `_classify_type`, `_shannon_entropy`)
- Line length: 100 for both Python and TypeScript
- Python target: 3.10
- Weights always sum to 1.0 — after dropping inapplicable signals, remaining weights renormalize
- Unit IDs follow the format `relative/path.ts::ExportName`
