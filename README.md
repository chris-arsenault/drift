# drift-semantic

[![CI](https://github.com/chris-arsenault/drift/actions/workflows/ci.yml/badge.svg)](https://github.com/chris-arsenault/drift/actions/workflows/ci.yml)

Deterministic semantic drift detection for TypeScript/React codebases. Finds the same functional concept implemented independently under different names — the kind of duplication that grep, ESLint, and traditional DRY tools miss entirely.

Three components named `ButtonHeader`, `ToolBar`, and `GridComponent` that all render "a horizontal bar of contextual action buttons." Three functions named `loadWorldData()`, `fetchEntities()`, and `buildStateForSlot()` that all load entity data from persistence.

## Prerequisites

- **Node.js** (for the TypeScript extractor)
- **Python 3.10+** (for the scoring pipeline)
- **ast-grep** (`sg`) — optional, adds structural pattern matching

Dependencies auto-install on first run. No API keys, no databases, no Docker.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/chris-arsenault/drift/main/install.sh | bash
```

Or clone manually:

```bash
git clone https://github.com/chris-arsenault/drift.git ~/.drift-semantic
export PATH="$HOME/.drift-semantic/bin:$PATH"
```

## Quick Start

```bash
# Install the Claude Code skill in your project
cd /path/to/your/project
drift install-skill

# Run the full pipeline
drift run --project .
```

The tool writes structured output to `.drift-audit/semantic/`. The Claude Code skill reads this output and verifies whether clusters represent genuine semantic duplication.

## Usage

```bash
# Full pipeline
drift run --project /path/to/project

# Individual stages
drift extract --project /path/to/project
drift fingerprint
drift score
drift cluster
drift report

# Inspect results
drift inspect unit "src/components/ToolBar.tsx::ToolBar"
drift inspect similar "src/components/ToolBar.tsx::ToolBar" --top 10
drift inspect cluster cluster-001

# Search the index
drift search calls "src/lib/api.ts::fetchEntities"
drift search type-like "src/hooks/useDataLoader.ts::useDataLoader"
```

See [docs/cli-reference.md](docs/cli-reference.md) for the full command list.

## How It Works

```
extract → fingerprint → typesig → callgraph → depcontext
                              ↓
                        score → cluster → report
```

1. **Extract** — TypeScript AST parsing via ts-morph. Extracts all exported code units with type info, JSX structure, hook usage, imports, call graph, consumer graph, and behavior markers.
2. **Fingerprint** — Computes structural fingerprints: JSX hashes, hook profile vectors, import constellations (IDF-weighted), behavior flags.
3. **Score** — Pairwise similarity across 13 signals with adaptive weight matrix. Weights adjust based on available signals and unit kinds.
4. **Cluster** — Graph-based community detection (connected components + greedy modularity).
5. **Report** — Markdown report, drift manifest, dependency atlas.

The tool is fully deterministic — same input, same output. The LLM layer (Claude Code skill) is optional and external: it reads the tool's structured output, verifies clusters, and writes findings back.

See [docs/architecture.md](docs/architecture.md) for pipeline details, similarity signals, and output artifacts.

## Management

```bash
drift version        # Show version and install path
drift upgrade        # Pull latest + refresh dependencies
drift install-skill  # Install/update skill in current project
```

## Uninstall

```bash
rm -rf ~/.drift-semantic
```

Remove the `# --- drift-semantic ---` block from your shell profile (`~/.bashrc`, `~/.zshrc`).

## Documentation

- [Architecture](docs/architecture.md) — pipeline stages, similarity signals, output artifacts
- [CLI Reference](docs/cli-reference.md) — full command list with examples
- [Development](docs/development.md) — linting, testing, conventions
- [Design Document](docs/design.md) — problem statement, design principles, data flow
- [Skill Definition](skill/SKILL.md) — Claude Code agent instructions
