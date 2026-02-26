# Semantic Drift Detection Pipeline

## Design Document v4

### Problem

A large TypeScript/React codebase contains semantic duplication — the same
functional concept implemented independently under different names, APIs, and
structures. Detection requires understanding what code DOES, not what it's named.

### Design Principles

**The tool is deterministic.** It parses code, computes structural features,
builds graphs, calculates similarity scores, and produces clusters. It makes
zero LLM calls by default. Same input → same output, every time.

**Claude Code is the semantic layer.** Purpose statements, semantic verification,
and architectural interpretation happen in the Claude Code session — where the
user is already paying for inference and where the LLM already has full project
context. The skill orchestrates: run tool → read structured output → Claude
interprets → optionally feed interpretation back to tool.

**No per-token API costs.** The tool requires no API keys in its default
configuration. If the user wants embedding-based similarity, they configure
a local Ollama URL. Everything else is pure computation.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  CLAUDE CODE SESSION                                             │
│                                                                  │
│  ┌──────────────────────┐     ┌───────────────────────────────┐  │
│  │  SKILL: drift-       │     │  SKILL: drift-                │  │
│  │  semantic-audit      │     │  semantic-explore             │  │
│  │                      │     │                               │  │
│  │  1. Invokes CLI      │     │  Queries index, Claude        │  │
│  │  2. Reads artifacts  │     │  interprets results           │  │
│  │  3. Claude interprets│     │  conversationally             │  │
│  │     clusters         │     │                               │  │
│  │  4. Optionally feeds │     │                               │  │
│  │     purpose stmts    │     │                               │  │
│  │     back to CLI      │     │                               │  │
│  └──────────┬───────────┘     └───────────────────────────────┘  │
│             │                                                    │
│             │  invoke / read / write                              │
│             │                                                    │
│  ┌──────────▼────────────────────────────────────────────────┐   │
│  │  CLI: drift-semantic                                      │   │
│  │  Fully deterministic. No API keys. No LLM calls.          │   │
│  │                                                           │   │
│  │  extract → fingerprint → typesig → callgraph → depctx    │   │
│  │                    ↓                                      │   │
│  │              score → cluster → report                     │   │
│  │                                                           │   │
│  │  Optional: embed (requires Ollama URL)                    │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## What the Tool Does vs What Claude Does

| Concern | Tool (deterministic) | Claude Code (semantic) |
|---------|---------------------|----------------------|
| Parse AST, resolve types | ✓ | |
| Extract call graph | ✓ | |
| Build consumer/co-occurrence graph | ✓ | |
| Structural fingerprinting | ✓ | |
| Type signature normalization | ✓ | |
| Pairwise similarity scoring | ✓ | |
| Clustering | ✓ | |
| Generate purpose statements | | ✓ (reads code, writes statements) |
| Embed purpose statements | ✓ (Ollama) or skip | |
| Verify cluster equivalence | | ✓ (reads cluster + source code) |
| Present findings to user | | ✓ |
| Decide what to consolidate | | ✓ (with user) |

---

## Pipeline Stages

### Stage 1: EXTRACT (tool)

ts-morph parses the full codebase and extracts all exported code units.

**Extracts per unit:**

```
Identity:
  - id, name, kind, filePath, lineRange, sourceCode

Type Information:
  - parameters/props (name, resolved type, optionality)
  - returnType (resolved)
  - generics, type alias chain

Structure (components):
  - jsxTree: tag nesting with map/conditional markers, attributes stripped
  - jsxLeafElements, jsxDepth

Hooks & State:
  - hookCalls (ordered, with counts)
  - customHookCalls (project-internal use* calls)
  - stateVariableCount

Dependencies:
  - imports (external + internal, categorized)
  - storeAccess (reads + writes)
  - dataSourceAccess

Call Graph (outbound):
  - callees: ordered list with resolved target, call expression, position,
    and context (render | effect | handler | init | conditional)
  - calleeSequence: ordered target ids per context
  - callDepth, uniqueCallees
  - chainPatterns: method chains with identifiers wildcarded
    e.g., "db.*.where().equals().toArray()"

Dependency Context (inbound):
  - consumers: units that import and reference this unit
  - consumerCount, consumerKinds, consumerDirectories
  - coOccurrences: units frequently imported alongside this one,
    with count and ratio

Behavior Markers:
  - isAsync, hasErrorHandling, hasLoadingState, hasEmptyState,
    hasRetryLogic, rendersIteration, rendersConditional, sideEffects
```

**Output:** `code-units.json`

**Performance:** 10-30 seconds for 200K lines. The call graph and consumer
graph reuse the same AST traversal and add marginal time.

### Stage 2a: STRUCTURAL FINGERPRINT (tool)

Computed per unit from Stage 1 data:

- **JSX structure hash** (exact + fuzzy with custom tags wildcarded)
- **Hook profile vector** (fixed-length, React built-in hook call counts)
- **Import constellation vector** (sparse, auto-weighted by specificity)
- **Behavior flag vector** (binary)
- **Data access pattern** (sparse vector over store/db vocabulary)

**Output:** `structural-fingerprints.json`

### Stage 2b: SEMANTIC EMBED (tool, optional, requires Ollama)

**Only runs if Ollama URL is configured AND purpose statements exist.**

The skill generates purpose statements (Claude reads code, writes one-sentence
descriptions). The tool embeds them via Ollama. This stage is not required —
the scoring stage adapts its weights based on available signals.

```bash
# Skill writes purpose-statements.json, then:
drift-semantic embed --ollama-url http://localhost:11434 --model nomic-embed-text
```

**Input:** `purpose-statements.json` (written by skill)
**Output:** `semantic-embeddings.json`

### Stage 2c: TYPE SIGNATURE (tool)

Normalized type hashes with identifiers stripped:

- **Strict hash:** exact structural match after name stripping
- **Loose hash:** arity + primitives + function shape only
- **Canonical string:** human-readable normalized form

Applied to both parameter types and return types.

**Output:** `type-signatures.json`

### Stage 2d: CALL GRAPH (tool)

Computed per unit from Stage 1 call data:

- **Callee set vector** (sparse, specificity-weighted like imports)
- **Call sequences per context** (render, effect, handler — ordered target lists)
- **Sequence hashes** (for exact match)
- **Chain pattern hashes** (wildcarded method chains)
- **Depth profile** ([direct, depth-2, depth-3+] call counts)
- **Consumer-caller overlap** (does this unit call things its consumers also call directly?)

**Output:** `call-graph.json`

### Stage 2e: DEPENDENCY CONTEXT (tool)

Computed per unit from Stage 1 consumer/co-occurrence data:

- **Consumer profile vector** (normalized count, kind entropy, directory spread)
- **Co-occurrence vector** (sparse, over all units — which units appear alongside this one)
- **Neighborhood hash** at radius 1 and radius 2

**Output:** `dependency-context.json`

### Stage 3: SCORE (tool)

Pairwise similarity across all units using all available signals.

**Signals and similarity functions:**

| Signal | Function | Notes |
|--------|----------|-------|
| semantic | cosine similarity on embeddings | Only if embeddings exist |
| typeSignature | hash match (strict→1.0, loose→0.7, arity overlap→0.4) | |
| jsxStructure | tree edit distance, normalized | Components only |
| hookProfile | cosine similarity on hook vectors | Components/hooks only |
| importConstellation | cosine similarity on weighted import vectors | |
| dataAccess | Jaccard on data source sets | |
| behaviorFlags | normalized Hamming distance | |
| calleeSet | cosine similarity on weighted callee vectors | |
| callSequence | LCS length / max sequence length, per context | |
| consumerSet | Jaccard on consumer sets, bonus for cross-directory | |
| coOccurrence | cosine similarity on co-occurrence vectors | |
| neighborhood | hash match (r1→1.0, r2→0.6, else Jaccard fallback) | |

**Adaptive weight matrix:**

When all signals available (component):

```
semantic:       0.20    ←  only when embeddings present
typeSignature:  0.12
jsxStructure:   0.13
hookProfile:    0.05
imports:        0.05
dataAccess:     0.03
behavior:       0.02
calleeSet:      0.10
callSequence:   0.10
consumerSet:    0.08
coOccurrence:   0.07
neighborhood:   0.05
```

When semantic embeddings unavailable, the 0.20 redistributes:

```
typeSignature:  0.16  (+0.04)
jsxStructure:   0.16  (+0.03)
hookProfile:    0.06  (+0.01)
imports:        0.06  (+0.01)
dataAccess:     0.04  (+0.01)
behavior:       0.02
calleeSet:      0.13  (+0.03)
callSequence:   0.13  (+0.03)
consumerSet:    0.10  (+0.02)
coOccurrence:   0.08  (+0.01)
neighborhood:   0.06  (+0.01)
```

Cross-kind pairs (component↔hook, hook↔function) drop inapplicable signals
(jsx, hookProfile) and renormalize.

**Output:** `similarity-matrix.json` — pairs above threshold with per-signal
breakdown and dominant signal family tag.

### Stage 4: CLUSTER (tool)

Graph-based community detection over the similarity matrix:

1. Build graph: units as nodes, edges where similarity > threshold
2. Connected components for initial clusters
3. Sub-cluster large clusters (>5 members) by dominant signal
4. Enrich: avg similarity, signal family breakdown, directory spread,
   kind mix, shared callees, consumer overlap, call sequence alignment
5. Rank: memberCount × avgSimilarity × directorySpread × kindBonus

**Output:** `clusters.json`

### Stage 5: VERIFY (Claude Code, via skill)

**Not a tool stage.** The skill reads `clusters.json`, Claude reads the actual
source files of cluster members, assesses semantic equivalence, and writes
structured verdicts.

For each cluster, Claude produces:
- verdict: DUPLICATE | OVERLAPPING | RELATED | FALSE_POSITIVE
- confidence
- role description
- shared behavior, meaningful differences, accidental differences
- feature gaps
- shared workflow (from call graph data)
- architectural role (from dependency context data)
- consolidation complexity and reasoning
- consumer impact

**Output:** `findings.json` (written by skill)

### Stage 6: REPORT (tool)

Reads all artifacts including `findings.json` (if present) and generates:

- `semantic-drift-report.md` — human-readable findings
- `drift-manifest.json` entries with `"type": "semantic"`
- `dependency-atlas.json` — graph structure for visualization

If findings don't exist, generates a preliminary report from clusters alone
that shows "these are structurally similar, pending semantic verification."

---

## Data Flow

```
                    Tool writes              Skill/Claude writes
                    ──────────               ──────────────────
Stage 1:            code-units.json
Stage 2a:           structural-fingerprints.json
Stage 2b:                                    purpose-statements.json
                    semantic-embeddings.json  (tool embeds via Ollama)
Stage 2c:           type-signatures.json
Stage 2d:           call-graph.json
Stage 2e:           dependency-context.json
Stage 3:            similarity-matrix.json
Stage 4:            clusters.json
Stage 5:                                     findings.json
Stage 6:            semantic-drift-report.md
                    drift-manifest.json
                    dependency-atlas.json
```

Two files flow FROM Claude TO the tool. Everything else flows FROM the tool
TO Claude. The tool has `ingest-purposes` and `ingest-findings` commands to
validate and incorporate the inbound files.

---

## CLI

```bash
# Full pipeline (deterministic stages only)
drift-semantic run --project .

# Individual stages
drift-semantic extract --project .
drift-semantic fingerprint
drift-semantic typesig
drift-semantic callgraph
drift-semantic depcontext
drift-semantic score
drift-semantic cluster
drift-semantic report

# Optional embedding (requires Ollama)
drift-semantic embed --ollama-url http://localhost:11434 --model nomic-embed-text

# Ingest from Claude
drift-semantic ingest-purposes --file purpose-statements.json
drift-semantic ingest-findings --file findings.json

# Inspection
drift-semantic inspect unit <unitId>
drift-semantic inspect similar <unitId> --top 10
drift-semantic inspect cluster <clusterId>
drift-semantic inspect graph <unitId> --radius 2
drift-semantic inspect consumers <unitId>
drift-semantic inspect callers <unitId>

# Structural search (no embeddings needed)
drift-semantic search --calls <unitId>
drift-semantic search --called-by <unitId>
drift-semantic search --co-occurs-with <unitId>
drift-semantic search --type-like <unitId>

# Semantic search (requires embeddings)
drift-semantic search --purpose "loads entities from persistence"
drift-semantic search --similar-to <unitId>

# Incremental
drift-semantic run --project . --incremental

# Export
drift-semantic export --format html
drift-semantic export --format dot
```

---

## Interaction Flows

### Full audit (no Ollama)

```
User: "Run a semantic drift analysis"

Skill:
  1. $ drift-semantic run --project .
     → extract, fingerprint, typesig, callgraph, depcontext, score, cluster, report

  2. Reads clusters.json
     For top N clusters: reads source files of members, assesses equivalence

  3. Writes findings.json

  4. $ drift-semantic report   (re-generates with findings)

  5. Reads semantic-drift-report.md, presents to user
```

### Full audit with embeddings (Ollama available)

```
Same as above, but between steps 1 and 2:

  1a. Reads code-units.json, generates purpose statements for units
      in candidate clusters (Claude reads source, writes descriptions)
  1b. Writes purpose-statements.json
  1c. $ drift-semantic ingest-purposes --file purpose-statements.json
  1d. $ drift-semantic embed --ollama-url http://localhost:11434
  1e. $ drift-semantic score   (re-score with embeddings included)
  1f. $ drift-semantic cluster (re-cluster with new scores)
```

### Targeted exploration

```
User: "What's similar to ToolBar?"

Skill:
  1. $ drift-semantic inspect similar "src/.../ToolBar.tsx::ToolBar" --top 10
  2. Reads results, reads source files of top matches
  3. Interprets and presents conversationally
```

### Incremental enrichment across sessions

```
Session 1: Run full pipeline, verify top 20 clusters
Session 2: "Continue verifying clusters" → verify next 20
Session 3: "Re-run with latest code changes" → incremental run,
           re-verify affected clusters
```

Purpose statements and findings accumulate in their JSON files across
sessions. The tool incorporates everything it's received.

---

## Dependencies

### Tool (Python)

```toml
[project]
name = "drift-semantic"
requires-python = ">=3.10"
dependencies = [
    "numpy",
    "scipy",
    "click",
    "networkx",
]

[project.optional-dependencies]
ollama = ["httpx"]
```

### Extractor (TypeScript)

```json
{
  "dependencies": {
    "ts-morph": "latest"
  }
}
```

### Total

5 packages. No API keys. No databases. No Docker. No background services.

---

## Cost

| Component | Cost |
|-----------|------|
| Tool execution | $0 |
| Ollama (if used) | $0 (local) |
| Claude Code session | Already paid for |
| **Total incremental cost** | **$0** |
