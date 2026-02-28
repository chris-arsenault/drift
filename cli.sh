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
# Python discovery
# ---------------------------------------------------------------------------
#
# Finds a working python3 (>=3.10) that can create venvs. Searches:
#   1. Existing venv in pipeline/.venv (already set up)
#   2. System python3 (if it has venv support)
#   3. uv-managed python (uv python find / uv venv)
#   4. pyenv-managed python
#   5. conda python
#   6. Versioned binaries (python3.14, python3.13, ... python3.10)
#   7. mise/asdf shims
#
# Sets PYTHON3 to the discovered interpreter path. Caches the result for the
# session in _DRIFT_PYTHON3 to avoid re-discovery on every command.

_DRIFT_PYTHON3=""

_python_version_ok() {
    # Check if a python binary exists and is >= 3.10
    local py="$1"
    "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null
}

_python_can_venv() {
    # Check if a python binary can actually create a working venv with pip.
    # On Debian/Ubuntu minimal installs, `import venv` succeeds but
    # `python3 -m venv` fails because ensurepip is missing. The error
    # message is printed by a subprocess, so 2>/dev/null doesn't catch it.
    # We check for ensurepip directly instead.
    local py="$1"
    "$py" -c "import ensurepip" 2>/dev/null
}

discover_python() {
    # Return cached result if available
    if [[ -n "$_DRIFT_PYTHON3" ]]; then
        PYTHON3="$_DRIFT_PYTHON3"
        return 0
    fi

    local VENV_DIR="$PIPELINE_DIR/.venv"

    # 1. Existing venv — fastest path
    if [[ -x "$VENV_DIR/bin/python3" ]] && _python_version_ok "$VENV_DIR/bin/python3"; then
        PYTHON3="$VENV_DIR/bin/python3"
        _DRIFT_PYTHON3="$PYTHON3"
        return 0
    fi

    # 2. System python3
    if command -v python3 &>/dev/null && _python_version_ok python3 && _python_can_venv python3; then
        PYTHON3="python3"
        _DRIFT_PYTHON3="$PYTHON3"
        return 0
    fi

    # 3. uv-managed python
    if command -v uv &>/dev/null; then
        local uv_py
        uv_py="$(uv python find '>=3.10' 2>/dev/null)" || true
        if [[ -n "$uv_py" ]] && _python_version_ok "$uv_py"; then
            # uv python may not have venv module, but uv can create venvs directly
            PYTHON3="$uv_py"
            _DRIFT_PYTHON3="$PYTHON3"
            _DRIFT_HAS_UV=1
            return 0
        fi
    fi

    # 4. pyenv
    if command -v pyenv &>/dev/null; then
        local pyenv_root
        pyenv_root="$(pyenv root 2>/dev/null)"
        if [[ -n "$pyenv_root" ]]; then
            for ver_dir in "$pyenv_root"/versions/3.*/bin/python3; do
                if [[ -x "$ver_dir" ]] && _python_version_ok "$ver_dir"; then
                    PYTHON3="$ver_dir"
                    _DRIFT_PYTHON3="$PYTHON3"
                    return 0
                fi
            done
        fi
    fi

    # 5. conda
    if [[ -n "${CONDA_PREFIX:-}" ]] && [[ -x "$CONDA_PREFIX/bin/python3" ]]; then
        if _python_version_ok "$CONDA_PREFIX/bin/python3"; then
            PYTHON3="$CONDA_PREFIX/bin/python3"
            _DRIFT_PYTHON3="$PYTHON3"
            return 0
        fi
    fi

    # 6. Versioned binaries (try newest first)
    local ver
    for ver in 14 13 12 11 10; do
        if command -v "python3.$ver" &>/dev/null && _python_version_ok "python3.$ver"; then
            if _python_can_venv "python3.$ver"; then
                PYTHON3="python3.$ver"
                _DRIFT_PYTHON3="$PYTHON3"
                return 0
            fi
        fi
    done

    # 7. mise/asdf shims
    for shimdir in "$HOME/.local/share/mise/shims" "$HOME/.asdf/shims"; do
        if [[ -x "$shimdir/python3" ]] && _python_version_ok "$shimdir/python3"; then
            PYTHON3="$shimdir/python3"
            _DRIFT_PYTHON3="$PYTHON3"
            return 0
        fi
    done

    # 8. Last resort: system python3 without venv (uv can still create venvs)
    if command -v python3 &>/dev/null && _python_version_ok python3; then
        if command -v uv &>/dev/null; then
            PYTHON3="python3"
            _DRIFT_PYTHON3="$PYTHON3"
            _DRIFT_HAS_UV=1
            return 0
        fi
    fi

    echo "ERROR: Python 3.10+ is required but not found." >&2
    echo "" >&2
    echo "Install Python via one of:" >&2
    echo "  uv:    curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.12" >&2
    echo "  apt:   sudo apt install python3 python3-venv" >&2
    echo "  brew:  brew install python@3.12" >&2
    echo "  pyenv: pyenv install 3.12" >&2
    exit 1
}

_DRIFT_HAS_UV=0

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
    discover_python
}

ensure_node_deps() {
    if [ ! -d "$EXTRACTOR_DIR/node_modules" ]; then
        echo "Installing extractor dependencies..." >&2
        (cd "$EXTRACTOR_DIR" && npm install --no-audit --no-fund 2>&1 | tail -1) >&2
    fi
}

ensure_python_deps() {
    discover_python

    VENV_DIR="$PIPELINE_DIR/.venv"
    if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python3" ]; then
        export PATH="$VENV_DIR/bin:$PATH"
        PYTHON3="$VENV_DIR/bin/python3"
        if ! "$PYTHON3" -c "import drift_semantic" 2>/dev/null; then
            echo "Installing pipeline into venv..." >&2
            "$VENV_DIR/bin/pip" install -e "$PIPELINE_DIR" --quiet 2>&1 | tail -1 >&2
        fi
    else
        echo "Creating Python venv for pipeline..." >&2
        if [[ "$_DRIFT_HAS_UV" -eq 1 ]] || ! _python_can_venv "$PYTHON3"; then
            # Use uv to create the venv (handles missing venv module)
            if command -v uv &>/dev/null; then
                uv venv "$VENV_DIR" --python ">=3.10" --seed 2>&1 | tail -1 >&2
            else
                echo "ERROR: Python's venv module is not available and uv is not installed." >&2
                echo "Fix with: sudo apt install python3-venv  OR  install uv" >&2
                exit 1
            fi
        else
            "$PYTHON3" -m venv "$VENV_DIR"
        fi
        "$VENV_DIR/bin/pip" install --upgrade pip --quiet 2>&1 | tail -1 >&2
        "$VENV_DIR/bin/pip" install -e "$PIPELINE_DIR" --quiet 2>&1 | tail -1 >&2
        export PATH="$VENV_DIR/bin:$PATH"
        PYTHON3="$VENV_DIR/bin/python3"
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
    "$PYTHON3" -m drift_semantic "$cmd" --output-dir "$OUTPUT_DIR" "$@"
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

        # Stage 2b: Embed purpose statements (if available)
        if [[ -f "$OUTPUT_DIR/purpose-statements.json" ]]; then
            echo "=== Stage 2b: EMBED ===" >&2
            run_pipeline embed
        else
            echo "  Skipping embed (no purpose-statements.json yet)." >&2
        fi

        # Stage 3: Pairwise similarity scoring
        echo "" >&2
        echo "=== Stage 3: SCORE ===" >&2
        run_pipeline score

        # Stage 4: Community detection / clustering
        echo "=== Stage 4: CLUSTER ===" >&2
        run_pipeline cluster

        # Stage 5: CSS pipeline — extract, score, cluster
        echo "" >&2
        echo "=== Stage 5a: CSS EXTRACT ===" >&2
        run_pipeline css-extract --project "$PROJECT_PATH"

        echo "=== Stage 5b: CSS SCORE ===" >&2
        run_pipeline css-score

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

    fingerprint|typesig|callgraph|depcontext|embed|score|cluster|report|css-extract|css-score)
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
  css-extract      Stage 5a: Extract CSS units from .css files
  css-score        Stage 5b: Score and cluster CSS file pairs
  report           Stage 6: Generate report

Optional:
  embed            Stage 2b: Embed purpose statements (built-in TF-IDF, or --ollama-url for Ollama)

Ingestion:
  ingest-purposes  Incorporate purpose statements from Claude
  ingest-findings  Incorporate verification findings from Claude

Inspection:
  inspect unit <id>         Show unit metadata
  inspect similar <id>      Find similar units
  inspect cluster <id>      Show cluster details
  inspect consumers <id>    Show who imports this unit
  inspect callers <id>      Show who calls this unit

Search:
  search calls <id>             Find all units that the given unit calls
  search called-by <id>         Find all units that call the given unit
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
