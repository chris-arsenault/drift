# CLI Reference

drift-semantic has two entry points: `drift` (wrapper CLI for management) and `cli.sh` (pipeline orchestrator). The wrapper passes unrecognized commands through to `cli.sh`, so in practice you always use `drift`.

## Management Commands

### `drift version`

Show version info: git SHA, date, pyproject version, and install path.

### `drift upgrade` / `drift self-update`

Pull latest changes. If `package.json` or `pyproject.toml` changed, clears cached dependencies (they reinstall on next run).

### `drift install-skill [target-dir]`

Install the Claude Code skill to a project. Default: current directory.

- Copies `skill/SKILL.md` to `.claude/skills/drift-audit-semantic/SKILL.md`
- Appends `DRIFT_SEMANTIC` env var block to `.claude/CLAUDE.md` if not present
- Idempotent: SKILL.md always overwritten (latest version), CLAUDE.md only appended once

## Pipeline Commands

### `drift run --project <path>`

Run the full pipeline: extract through report. Equivalent to running each stage in order.

```bash
drift run --project /path/to/your/project
```

### Individual Stages

Each stage reads from and writes to `$DRIFT_OUTPUT_DIR` (default: `.drift-audit/semantic/`).

```bash
drift extract --project <path>    # Stage 1: TypeScript AST extraction
drift fingerprint                 # Stage 2a: structural fingerprints
drift typesig                     # Stage 2c: type signature hashes
drift callgraph                   # Stage 2d: call graph vectors
drift depcontext                  # Stage 2e: dependency context
drift score                       # Stage 3: pairwise similarity
drift cluster                     # Stage 4: community detection
drift report                      # Stage 6: generate report + manifest
```

### Optional Stages

```bash
# Embed purpose statements via local Ollama
drift embed --ollama-url http://localhost:11434 --model nomic-embed-text

# Structural pattern matching (requires ast-grep/sg)
drift ast-grep --project <path>
```

### Ingestion

Feed Claude's analysis back into the tool:

```bash
drift ingest-findings --file findings.json
drift ingest-purposes --file purpose-statements.json
```

## Inspection Commands

Query the extracted data interactively.

```bash
drift inspect unit "src/components/ToolBar.tsx::ToolBar"
drift inspect similar "src/components/ToolBar.tsx::ToolBar" --top 10
drift inspect cluster cluster-001
drift inspect consumers "src/hooks/useDataLoader.ts::useDataLoader"
drift inspect callers "src/lib/api.ts::fetchEntities"
```

## Search Commands

Search across the index.

```bash
drift search calls "src/lib/api.ts::fetchEntities"
drift search called-by "src/hooks/useDataLoader.ts::useDataLoader"
drift search co-occurs-with "src/components/Modal.tsx::Modal"
drift search type-like "src/hooks/useDataLoader.ts::useDataLoader"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DRIFT_SEMANTIC` | `~/.drift-semantic` | Install directory |
| `DRIFT_OUTPUT_DIR` | `.drift-audit/semantic` | Artifact output directory |
| `DRIFT_MANIFEST` | `.drift-audit/drift-manifest.json` | Manifest file path |
