# CLI Reference

drift has two entry points: `drift` (wrapper CLI for management) and `cli.sh` (pipeline orchestrator). The wrapper passes unrecognized commands through to `cli.sh`, so in practice you always use `drift`.

## Management Commands

### `drift version`

Show version info: git SHA, date, pyproject version, and install path.

### `drift upgrade` / `drift self-update`

Pull latest changes. If `package.json` or `pyproject.toml` changed, clears cached dependencies (they reinstall on next run).

### `drift install-skill [target-dir]`

Install all drift Claude Code skills to a project. Default: current directory.

- Copies all 6 skills to `.claude/skills/<name>/SKILL.md`
- Copies drift-guard reference files to `.claude/skills/drift-guard/references/`
- Appends drift config block to `.claude/CLAUDE.md` if not present
- Creates `.drift-audit/config.json` with default library settings
- Idempotent: SKILL.md files always overwritten (latest version), CLAUDE.md only appended once

Skills installed: `drift`, `drift-audit`, `drift-audit-ux`, `drift-audit-semantic`, `drift-unify`, `drift-guard`.

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
drift css-extract --project <path> # Stage 1b: CSS rule extraction
drift css-score                   # Stage 3b: CSS pairwise similarity + clustering
drift report                      # Stage 6: generate report + manifest
```

### Embedding

```bash
# Embed purpose statements using built-in TF-IDF (default, no external services)
drift embed

# Embed via Ollama for higher-quality embeddings (optional)
drift embed --ollama-url http://localhost:11434 --model nomic-embed-text
```

The `run` command includes embed automatically — it skips gracefully if no purpose statements exist yet.

### Optional Stages

```bash
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

## Sync Mode Commands

### `drift online`

Enable auto-pull/push mode for the current project. In online mode, the CLAUDE.md instructions tell Claude to automatically run `drift library pull` before audits and `drift library push` after guard phases.

Updates `.drift-audit/config.json` (`mode: "online"`) and refreshes the CLAUDE.md block.

### `drift offline`

Disable auto-pull/push (default). Library push and pull must be run manually.

Updates `.drift-audit/config.json` (`mode: "offline"`) and refreshes the CLAUDE.md block.

## Library Commands

Manage the centralized drift artifact library. See [docs/library.md](library.md) for the full guide.

### `drift library init [path]`

Initialize the library directory. Default: `~/.drift/library`.

Creates the directory structure, an empty `library.json` manifest, and initializes a git repository.

### `drift library push`

Push guard artifacts from the current project to the library.

Reads `.drift-audit/config.json` to find artifact directories (via `sync` mappings), computes checksums, and copies new/changed files to the library.

### `drift library pull`

Pull artifacts from the library into the current project.

Syncs all artifacts that have a matching sync mapping in the project config. Only copies files where the library version differs from the local version.

### `drift library list`

Show all artifacts in the library, grouped by type.

### `drift library status`

Compare library artifacts vs the current project. Shows which artifacts are in sync, which are newer in the library, which are newer in the project, and which haven't been synced.

### `drift library commit`

Stage all changes in the library and commit with an auto-generated message.

### `drift library remote [url]`

With no arguments, show the current remote origin URL. With a URL argument, set or update the origin.

### `drift library remote-push`

Push committed library changes to the remote origin.

### `drift library remote-pull`

Pull latest changes from the remote origin (fast-forward only).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DRIFT_SEMANTIC` | `~/.drift-semantic` | Install directory |
| `DRIFT_OUTPUT_DIR` | `.drift-audit/semantic` | Artifact output directory |
| `DRIFT_MANIFEST` | `.drift-audit/drift-manifest.json` | Manifest file path |
