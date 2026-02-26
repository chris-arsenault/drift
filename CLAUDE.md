# drift-semantic

Semantic drift detection tool for TypeScript/React codebases. Finds duplicate functionality implemented under different names.

## Architecture

Three components composed by `cli.sh`:

- **extractor/** — TypeScript (ts-morph). Parses AST, extracts semantic units and fingerprints. `npm run build && node dist/index.js`
- **pipeline/** — Python (numpy, scipy, networkx). Pairwise scoring, clustering, report generation. `drift-semantic-pipeline`
- **ast-grep/** — YAML rules. Structural pattern detection via `sg scan`

## Development

```bash
make lint          # ESLint (extractor) + Ruff (pipeline)
make lint-fix      # Auto-fix both
make format        # Prettier (extractor) + Ruff format (pipeline)
make test          # pytest (pipeline)
```

## Testing Philosophy

Tests target **complicated logic only** — branching, regexes, math, similarity functions, hashing. Do not test:

- Things clearly correct by inspection (simple getters, trivial mappings)
- Code that requires expensive mocking (ts-morph AST nodes in the extractor)
- Integration/E2E flows (the CLI orchestrator handles this)

No coverage targets. The extractor has no unit tests because every exported function takes ts-morph `Node`/`SourceFile` objects — the cost of fixture setup outweighs the value. Pipeline tests live in `pipeline/tests/` and cover: vector math, similarity metrics, fingerprinting, type signature normalization, call graph analysis, dependency context, scoring/weight adaptation, and clustering.

Run tests: `make test` or `cd pipeline && python3 -m pytest tests/ -v`

## Conventions

- Python: Ruff for linting and formatting, line length 100, target py310
- TypeScript: ESLint 9 flat config + Prettier, cognitive-complexity raised to 30 for AST walkers
- `G` is idiomatic for networkx graphs (suppressed N803/N806)
- Pipeline uses `_` prefix for internal helpers (e.g., `_classify_type`, `_shannon_entropy`)
