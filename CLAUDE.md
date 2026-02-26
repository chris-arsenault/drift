# drift-semantic

## Critical Rules

- Weights MUST sum to 1.0 — after dropping inapplicable signals, renormalize remaining weights
- Unit IDs use the format `relative/path.ts::ExportName` — never change this convention
- `G` is the idiomatic variable name for networkx graphs — do not rename
- Internal helpers use `_` prefix — they are not part of the public API
- Do not add unit tests for the TypeScript extractor — all functions take ts-morph AST nodes and fixture cost outweighs value
- Pipeline tests target complicated logic only: branching, regexes, math, similarity functions, hashing. No coverage targets.

## Quick Reference

```bash
make lint          # ESLint + Ruff
make format        # Prettier + Ruff format
make test          # pytest (pipeline only)
```

## Documentation Index

- [docs/architecture.md](docs/architecture.md) — pipeline stages, similarity signals, weight adaptation, output artifacts
- [docs/cli-reference.md](docs/cli-reference.md) — all commands with examples, environment variables
- [docs/development.md](docs/development.md) — linting setup, testing philosophy, conventions
- [docs/design.md](docs/design.md) — problem statement, design principles, full data flow
