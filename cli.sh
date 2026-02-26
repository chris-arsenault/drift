#!/usr/bin/env bash
# drift-semantic -- Semantic drift detection CLI.
#
# Orchestrates the full pipeline: TypeScript extraction (ts-morph), ast-grep
# structural pattern matching, Python fingerprinting/scoring/clustering, and
# report generation.
#
# Usage:
#   bash cli.sh run --project <path>          Full pipeline
#   bash cli.sh extract --project <path>      TypeScript extraction only
#   bash cli.sh ast-grep --project <path>     Structural pattern matching only
#   bash cli.sh <stage>                       Individual Python stage
#   bash cli.sh inspect <subcommand> [args]   Inspection commands
#   bash cli.sh search <subcommand> [args]    Search commands
#
# Environment:
#   DRIFT_OUTPUT_DIR  -- artifact directory (default: .drift-audit/semantic)
#   DRIFT_MANIFEST    -- manifest path (default: .drift-audit/drift-manifest.json)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTRACTOR_DIR="$SCRIPT_DIR/extractor"
PIPELINE_DIR="$SCRIPT_DIR/pipeline"
AST_GREP_DIR="$SCRIPT_DIR/ast-grep"

OUTPUT_DIR="${DRIFT_OUTPUT_DIR:-.drift-audit/semantic}"
MANIFEST_PATH="${DRIFT_MANIFEST:-.drift-audit/drift-manifest.json}"

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------

check_node() {
    command -v node >/dev/null 2>&1 || {
        echo "ERROR: Node.js is required but not found." >&2
        exit 1
    }
}

check_python() {
    python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null || {
        echo "ERROR: Python 3.10+ is required." >&2
        exit 1
    }
}

ensure_node_deps() {
    if [ ! -d "$EXTRACTOR_DIR/node_modules" ]; then
        echo "Installing extractor dependencies..." >&2
        (cd "$EXTRACTOR_DIR" && npm install --no-audit --no-fund 2>&1 | tail -1) >&2
    fi
}

ensure_python_deps() {
    VENV_DIR="$PIPELINE_DIR/.venv"
    if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python3" ]; then
        export PATH="$VENV_DIR/bin:$PATH"
        if ! "$VENV_DIR/bin/python3" -c "import drift_semantic" 2>/dev/null; then
            echo "Installing pipeline into venv..." >&2
            "$VENV_DIR/bin/pip" install -e "$PIPELINE_DIR" --quiet 2>&1 | tail -1 >&2
        fi
    else
        echo "Creating Python venv for pipeline..." >&2
        python3 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/pip" install --upgrade pip --quiet 2>&1 | tail -1 >&2
        "$VENV_DIR/bin/pip" install -e "$PIPELINE_DIR" --quiet 2>&1 | tail -1 >&2
        export PATH="$VENV_DIR/bin:$PATH"
    fi
}

# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

run_extract() {
    local project_path="${1:-.}"
    check_node
    ensure_node_deps
    mkdir -p "$OUTPUT_DIR"
    echo "=== Stage 1: EXTRACT (TypeScript) ===" >&2
    npx --prefix "$EXTRACTOR_DIR" tsx "$EXTRACTOR_DIR/src/extract.ts" \
        --project "$project_path" \
        --output "$OUTPUT_DIR/code-units.json"
}

run_ast_grep() {
    local project_path="${1:-.}"
    mkdir -p "$OUTPUT_DIR"
    if command -v sg &>/dev/null; then
        echo "=== ast-grep: Structural pattern matching ===" >&2
        bash "$AST_GREP_DIR/run-patterns.sh" "$project_path" "$OUTPUT_DIR"
    else
        echo "  Skipping ast-grep (sg not found on PATH)." >&2
        echo '{}' > "$OUTPUT_DIR/structural-patterns.json"
    fi
}

run_pipeline() {
    local cmd="$1"
    shift
    check_python
    ensure_python_deps
    python3 -m drift_semantic "$cmd" --output-dir "$OUTPUT_DIR" "$@"
}

# ---------------------------------------------------------------------------
# Parse common flags
# ---------------------------------------------------------------------------

COMMAND="${1:-help}"
shift || true

# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

case "$COMMAND" in
    run)
        PROJECT_PATH="."
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --project) PROJECT_PATH="$2"; shift 2 ;;
                --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
                --manifest) MANIFEST_PATH="$2"; shift 2 ;;
                *) shift ;;
            esac
        done

        START_TIME=$(date +%s)
        echo "=== drift-semantic: full pipeline ===" >&2
        echo "Project: $PROJECT_PATH" >&2
        echo "Output:  $OUTPUT_DIR" >&2
        echo "" >&2

        # Stage 1: Extract code units from TypeScript/JSX sources
        run_extract "$PROJECT_PATH"

        # ast-grep structural pattern matching (optional, additive signal)
        run_ast_grep "$PROJECT_PATH"

        # Stage 2: Fingerprinting and feature extraction
        echo "" >&2
        echo "=== Stage 2a: FINGERPRINT ===" >&2
        run_pipeline fingerprint

        echo "=== Stage 2c: TYPE SIGNATURES ===" >&2
        run_pipeline typesig

        echo "=== Stage 2d: CALL GRAPH ===" >&2
        run_pipeline callgraph

        echo "=== Stage 2e: DEPENDENCY CONTEXT ===" >&2
        run_pipeline depcontext

        # Stage 3: Pairwise similarity scoring
        echo "" >&2
        echo "=== Stage 3: SCORE ===" >&2
        run_pipeline score

        # Stage 4: Community detection / clustering
        echo "=== Stage 4: CLUSTER ===" >&2
        run_pipeline cluster

        # Stage 6: Report generation
        echo "" >&2
        echo "=== Stage 6: REPORT ===" >&2
        run_pipeline report --manifest "$MANIFEST_PATH"

        END_TIME=$(date +%s)
        ELAPSED=$((END_TIME - START_TIME))
        echo "" >&2
        echo "=== Complete in ${ELAPSED}s ===" >&2
        echo "Artifacts: $OUTPUT_DIR/" >&2
        echo "Report:    $OUTPUT_DIR/semantic-drift-report.md" >&2
        ;;

    extract)
        PROJECT_PATH="."
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --project) PROJECT_PATH="$2"; shift 2 ;;
                --output) OUTPUT_DIR="$(dirname "$2")"; shift 2 ;;
                *) shift ;;
            esac
        done
        run_extract "$PROJECT_PATH"
        ;;

    ast-grep|patterns)
        PROJECT_PATH="."
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --project) PROJECT_PATH="$2"; shift 2 ;;
                --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
                *) shift ;;
            esac
        done
        run_ast_grep "$PROJECT_PATH"
        ;;

    fingerprint|typesig|callgraph|depcontext|embed|score|cluster|report)
        run_pipeline "$COMMAND" "$@"
        ;;

    ingest-purposes|ingest-findings)
        run_pipeline "$COMMAND" "$@"
        ;;

    inspect|search)
        run_pipeline "$COMMAND" "$@"
        ;;

    help|--help|-h)
        cat >&2 <<'USAGE'
drift-semantic -- Semantic drift detection CLI

Usage: bash cli.sh <command> [options]

Pipeline commands:
  run              Run full pipeline (extract -> score -> cluster -> report)
  extract          Stage 1: Parse codebase with ts-morph
  ast-grep         Run structural pattern matching
  fingerprint      Stage 2a: Compute structural fingerprints
  typesig          Stage 2c: Normalize type signatures
  callgraph        Stage 2d: Compute call graph vectors
  depcontext       Stage 2e: Compute dependency context
  score            Stage 3: Pairwise similarity scoring
  cluster          Stage 4: Community detection
  report           Stage 6: Generate report

Optional:
  embed            Stage 2b: Embed purpose statements (requires Ollama)

Ingestion:
  ingest-purposes  Incorporate purpose statements from Claude
  ingest-findings  Incorporate verification findings from Claude

Inspection:
  inspect unit <id>         Show unit metadata
  inspect similar <id>      Find similar units
  inspect cluster <id>      Show cluster details
  inspect graph <id>        Show neighborhood graph
  inspect consumers <id>    Show who imports this unit
  inspect callers <id>      Show who calls this unit

Search:
  search calls <id>             Find all callers of a unit
  search called-by <id>         Find all callees of a unit
  search co-occurs-with <id>    Find co-occurring imports
  search type-like <id>         Find type-similar units

Options:
  --project <path>     Project root (default: .)
  --output-dir <path>  Output directory (default: .drift-audit/semantic)
  --manifest <path>    Manifest path (default: .drift-audit/drift-manifest.json)
USAGE
        ;;

    *)
        echo "Unknown command: $COMMAND. Run 'bash cli.sh help' for usage." >&2
        exit 1
        ;;
esac
