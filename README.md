# drift-semantic

[![CI](https://github.com/chris-arsenault/drift/actions/workflows/ci.yml/badge.svg)](https://github.com/chris-arsenault/drift/actions/workflows/ci.yml)

Find and fix technical drift — places where the same concept is implemented in multiple inconsistent ways. The kind of duplication that grep, ESLint, and traditional DRY tools miss entirely.

Three components named `ButtonHeader`, `ToolBar`, and `GridComponent` that all render "a horizontal bar of contextual action buttons." Three functions named `loadWorldData()`, `fetchEntities()`, and `buildStateForSlot()` that all load entity data from persistence.

Drift works as a set of Claude Code skills that orchestrate the full lifecycle: **discover** drift, **plan** a prioritized attack order, **unify** toward canonical patterns, and **guard** against regression with ESLint rules and ADRs.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/chris-arsenault/drift/main/install.sh | bash
```

Then install the skills into your project:

```bash
cd /path/to/your/project
drift install-skill
```

This installs six skills into `.claude/skills/` and configures your project's `.claude/CLAUDE.md`.

### Prerequisites

- **Claude Code** — the skills are the primary interface
- **Node.js** — for the TypeScript extractor (used by semantic audit)
- **Python 3.10+** — for the scoring pipeline and library management
- **ast-grep** (`sg`) — optional, adds structural pattern matching

Dependencies auto-install on first run. No API keys, no external services, no Docker.

## Usage

In Claude Code, use `/drift` to run the full pipeline:

```
/drift                    Full pipeline: audit → plan → unify → guard
/drift audit              Run all three audits (structural, behavioral, semantic)
/drift plan               Prioritize findings into an attack order
/drift unify              Refactor toward canonical patterns
/drift guard              Generate ESLint rules, ADRs, pattern docs
```

The orchestrator (`/drift`) runs all four phases in sequence. The plan phase is the human checkpoint — you review and approve the prioritized attack order before unify and guard proceed autonomously.

### Individual Skills

Each phase is also available as a standalone skill for focused work:

| Skill | Invoke | What it does |
|-------|--------|-------------|
| `drift` | `/drift` | Orchestrator: coordinates all phases |
| `drift-audit` | `/drift-audit` | Structural drift discovery via codebase scanning |
| `drift-audit-ux` | `/drift-audit-ux` | Behavioral drift across 7 UX domains |
| `drift-audit-semantic` | `/drift-audit-semantic` | Semantic duplication detection (tool-assisted) |
| `drift-unify` | `/drift-unify` | Batch refactoring toward a chosen canonical pattern |
| `drift-guard` | `/drift-guard` | Generate ESLint rules, ADRs, pattern docs, checklists |

### What Each Phase Produces

**Audit** writes to `.drift-audit/`:
- `drift-manifest.json` — machine-readable findings (all drift areas, variants, impact ratings)
- `drift-report.md` — human-readable report with priority matrix and detailed analysis

**Plan** writes to `.drift-audit/`:
- `attack-plan.json` — dependency-aware prioritized order with phase tracking

**Unify** writes to the project:
- Refactored source files aligned to canonical patterns
- `UNIFICATION_LOG.md` — what changed, shared utilities created, exceptions
- `DRIFT_BACKLOG.md` — remaining work for future sessions

**Guard** writes to the project:
- ESLint rules in `eslint-rules/` (or project convention)
- ADRs in `docs/adr/`
- Pattern usage guides in `docs/patterns/`
- Updated review checklist

## Artifact Library

Guard artifacts (ESLint rules, ADRs, pattern docs) can be centralized and synced across projects.

```bash
drift library init       # initialize ~/.drift/library
drift library publish    # push guard artifacts from project to library
drift library sync       # pull matching artifacts into project
drift library list       # show library contents
drift library status     # compare library vs project
```

Artifacts are scoped by **tags**. Set tags in `.drift-audit/config.json`:

```json
{
  "tags": ["react", "zustand"],
  "sync": {
    "eslint-rule": "eslint-rules/",
    "adr": "docs/adr/"
  }
}
```

The library is local-first (`~/.drift/library/`). Optionally back it with git for team sharing.

Enable **online mode** so Claude handles sync transparently as part of the pipeline:

```bash
drift online         # auto-sync before audits, auto-publish after guard
drift offline        # back to manual sync (default)
```

See [docs/library.md](docs/library.md) for details.

## How It Works

The semantic analysis pipeline (used by `/drift-audit-semantic`) combines deterministic structural analysis with Claude's semantic understanding:

```
extract → fingerprint → typesig → callgraph → depcontext
                                                    ↓
                Claude writes purpose statements → embed
                                                    ↓
                                              score → cluster → report
```

1. **Extract** — TypeScript AST parsing via ts-morph. Extracts all exported code units with type info, JSX structure, hook usage, imports, call graph, consumer graph, and behavior markers.
2. **Fingerprint** — Computes structural fingerprints: JSX hashes, hook profile vectors, import constellations (IDF-weighted), behavior flags.
3. **Embed** — Claude reads source code and writes purpose statements describing what each unit does. The pipeline embeds these via built-in TF-IDF for semantic comparison.
4. **Score** — Pairwise similarity across 13+ signals with adaptive weight matrix. When purpose statements are available, semantic similarity is weighted at 20%.
5. **Cluster** — Graph-based community detection (connected components + greedy modularity).
6. **Report** — Markdown report, drift manifest, dependency atlas.

The other two audit types (structural and behavioral) are agent-driven — Claude reads your source files directly, using `scripts/discover.sh` for initial inventory.

See [docs/architecture.md](docs/architecture.md) for pipeline details.

## CLI Reference

The `drift` CLI handles installation, library management, and the low-level analysis pipeline. Skills invoke these commands under the hood.

```bash
# Management
drift version        # show version and install path
drift upgrade        # pull latest + refresh dependencies
drift install-skill  # install/update skills in a project

# Library
drift library init | publish | sync | list | status

# Mode
drift online         # enable auto-sync
drift offline        # disable auto-sync (default)

# Low-level pipeline (typically invoked by skills, not directly)
drift run --project .              # full semantic analysis
drift extract --project .          # just extraction
drift inspect unit "src/Foo.tsx::Foo"
drift search type-like "src/Foo.tsx::Foo"
```

See [docs/cli-reference.md](docs/cli-reference.md) for the full command list.

## Uninstall

```bash
rm -rf ~/.drift-semantic
```

Remove the `# --- drift-semantic ---` block from your shell profile (`~/.bashrc`, `~/.zshrc`).

## Documentation

- [Architecture](docs/architecture.md) — pipeline stages, similarity signals, output artifacts
- [CLI Reference](docs/cli-reference.md) — full command list with examples
- [Library](docs/library.md) — centralized artifact library
- [Development](docs/development.md) — linting, testing, conventions
- [Design Document](docs/design.md) — problem statement, design principles, data flow
