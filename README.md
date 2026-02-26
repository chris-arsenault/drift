# drift-semantic

[![CI](https://github.com/chris-arsenault/drift/actions/workflows/ci.yml/badge.svg)](https://github.com/chris-arsenault/drift/actions/workflows/ci.yml)

Deterministic semantic drift detection for TypeScript/React codebases. Parses ASTs, computes structural fingerprints, scores pairwise similarity across 13 signals, and clusters similar code units.

Designed as the computational backbone for an LLM-driven semantic audit: the tool does the math, the LLM verifies clusters and interprets results.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/chris-arsenault/drift/main/install.sh | bash
```

Or clone manually:

```bash
git clone https://github.com/chris-arsenault/drift.git ~/.drift-semantic
~/.drift-semantic/bin/drift version
```

Then install the Claude Code skill in any project:

```bash
cd /path/to/your/project
drift install-skill
```

### Management

```bash
drift upgrade        # pull latest + refresh dependencies
drift version        # show version and install path
drift install-skill  # install/update skill in current project
```

### Uninstall

```bash
rm -rf ~/.drift-semantic
```

Remove the `# --- drift-semantic ---` block from your shell profile (`~/.bashrc`, `~/.zshrc`).

## What it does

Finds **the same functional concept implemented independently under different names** — the kind of duplication that grep, ESLint, and traditional DRY tools miss entirely. Three components named `ButtonHeader`, `ToolBar`, and `GridComponent` that all render "a horizontal bar of contextual action buttons." Three functions named `loadWorldData()`, `fetchEntities()`, and `buildStateForSlot()` that all load entity data from persistence.

## Requirements

- **Node.js** (for the TypeScript extractor, ts-morph)
- **Python 3.10+** (for the pipeline: numpy, scipy, networkx, click)
- **ast-grep** (`sg`) — optional, adds structural pattern matching signal

Dependencies auto-install on first run. No API keys, no databases, no Docker.

## Usage

```bash
# Full pipeline against a project
drift run --project /path/to/your/project

# Individual stages
drift extract --project /path/to/project
drift fingerprint
drift typesig
drift callgraph
drift depcontext
drift score
drift cluster
drift report

# Inspect results
drift inspect unit "src/components/ToolBar.tsx::ToolBar"
drift inspect similar "src/components/ToolBar.tsx::ToolBar" --top 10
drift inspect cluster cluster-001
drift inspect consumers "src/hooks/useDataLoader.ts::useDataLoader"

# Search the index
drift search calls "src/lib/api.ts::fetchEntities"
drift search type-like "src/hooks/useDataLoader.ts::useDataLoader"
drift search co-occurs-with "src/components/Modal.tsx::Modal"

# Optional: embed purpose statements via local Ollama
drift embed --ollama-url http://localhost:11434 --model nomic-embed-text
```

Output goes to `.drift-audit/semantic/` by default.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  cli.sh (bash orchestrator)                                      │
│                                                                  │
│  extract → fingerprint → typesig → callgraph → depcontext        │
│                    ↓                                             │
│              score → cluster → report                            │
│                                                                  │
│  Optional: embed (requires Ollama)                               │
└──────────────────────────────────────────────────────────────────┘
```

Three components:

### extractor/ — TypeScript (ts-morph)

Parses the full codebase AST and extracts all exported code units with:
- Type information (parameters, return types, generics)
- JSX structure (tree with map/conditional markers)
- Hook usage (React built-in + custom hooks)
- Import analysis (categorized: framework/external/internal)
- Call graph (outbound callees with context classification)
- Consumer graph (inbound: who imports this unit)
- Behavior markers (async, error handling, loading state, etc.)

### pipeline/ — Python (numpy, scipy, networkx, click)

Processes extracted units through:
- **Fingerprinting** — JSX hash, hook profile vector, import constellation (IDF-weighted), behavior flags, data access patterns
- **Type signatures** — normalized hashes with identifiers stripped (strict/loose/arity matching)
- **Call graph vectors** — callee sets (IDF-weighted), sequence hashes, chain pattern hashes, depth profiles
- **Dependency context** — consumer profiles, co-occurrence vectors, neighborhood hashes at radius 1 and 2
- **Scoring** — pairwise similarity across all signals with adaptive weight matrix (adapts to available signals and unit kinds)
- **Clustering** — graph-based community detection (connected components + greedy modularity for large clusters)
- **Reporting** — markdown report, drift manifest entries, dependency atlas for visualization

### ast-grep/ — YAML rules + bash runner

Structural pattern matching as an additive scoring signal. Detects: button bars, list-with-map, modal wrappers, detail panels, Zustand stores, multi-useState, Dexie queries, fetch-with-state, store selectors, error handling, worker messages, async callbacks, promise chains.

## Similarity Signals

| Signal | Method | Notes |
|--------|--------|-------|
| typeSignature | Hash match (strict→1.0, loose→0.7, arity→0.4) | |
| jsxStructure | Tree similarity (exact hash, fuzzy hash, or node matching) | Components only |
| hookProfile | Cosine similarity on hook call count vectors | Components/hooks only |
| importConstellation | Cosine similarity on IDF-weighted import vectors | |
| dataAccess | Jaccard on data source/store sets | |
| behaviorFlags | Normalized Hamming distance | |
| calleeSet | Cosine similarity on IDF-weighted callee vectors | |
| callSequence | LCS-based or hash match on ordered call sequences | |
| consumerSet | Jaccard on consumer sets + cross-directory bonus | |
| coOccurrence | Cosine similarity on co-occurrence vectors | |
| neighborhood | Hash match at radius 1 (1.0) or radius 2 (0.6) | |
| structuralPattern | Jaccard on ast-grep pattern tags | Optional |
| semantic | Cosine similarity on Ollama embeddings | Optional, requires Ollama |

Weights adapt automatically based on available signals (embeddings present or not) and unit kind pairs (component-only signals drop for non-component pairs, remaining weights renormalize).

## LLM Integration

The tool is fully deterministic by default — same input, same output. The LLM layer is optional and handled externally:

1. **Tool writes** `clusters.json` — structurally similar groups
2. **LLM reads** cluster members' source code, assesses semantic equivalence
3. **LLM writes** `findings.json` with verdicts (DUPLICATE/OVERLAPPING/RELATED/FALSE_POSITIVE)
4. **Tool reads** findings via `ingest-findings`, regenerates report with verdicts

Purpose statements follow the same pattern: LLM writes them, tool embeds via Ollama (if available), and incorporates as an additional scoring signal.

See `skill/SKILL.md` for the full LLM-facing instruction set that orchestrates the tool.

## Design

See `docs/design.md` for the full architecture document including data flow, weight matrices, and interaction patterns.
