#!/usr/bin/env bash
# audit-orchestrate.sh — Deterministic orchestrator for the drift audit phase.
#
# Runs the full audit as a sequence of deterministic steps and gated Claude -p
# calls.  Each analytical step must produce specific artifacts before the next
# step can begin.
#
# Workflow:
#   Step 0: Library pull                              (deterministic)
#   Step 1: Extract + feature extraction              (deterministic)
#   Step 2: Purpose statements                        (claude -p)
#   Step 3: Structural + behavioral audit             (claude -p)
#   Step 4: Score + cluster (with purpose embeddings) (deterministic)
#   Step 5: Cluster verification + semantic entries   (claude -p)
#   Step 6: Validate manifest                         (deterministic)
#
# Usage:
#   drift audit <project-root> [options]
#
# Options:
#   --model <model>        Override Claude model for analytical steps
#   --skip-to <N>          Skip to step N (verifies prior gates)
#   --max-turns <N>        Max agentic turns per Claude call (default: 200)
#   --verbose              Stream all output to terminal (always logged to audit.log)
#   --dry-run              Print what would run without executing

set -euo pipefail

DRIFT_HOME="${DRIFT_SEMANTIC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

if [[ -t 2 ]]; then
    _R='\033[0m' _G='\033[0;32m' _Y='\033[0;33m' _B='\033[0;34m'
    _RED='\033[0;31m' _BOLD='\033[1m'
else
    _R='' _G='' _Y='' _B='' _RED='' _BOLD=''
fi

# All status messages go to terminal (stderr) AND log file if available.
_to_log() { [[ -n "${LOG_FILE:-}" ]] && printf "%s\n" "$*" >> "$LOG_FILE"; }

step_header() {
    local msg="=== STEP $1: $2 ==="
    printf "\n${_BOLD}${_B}%s${_R}\n" "$msg" >&2
    _to_log ""; _to_log "$msg"
}
gate_pass() {
    printf "${_G}  GATE: %s${_R}\n" "$*" >&2
    _to_log "  GATE: $*"
}
gate_fail() {
    printf "${_RED}  GATE FAILED: %s${_R}\n" "$*" >&2
    _to_log "  GATE FAILED: $*"
}
info() {
    printf "${_B}[*]${_R} %s\n" "$*" >&2
    _to_log "[*] $*"
}
success() {
    printf "${_G}[+]${_R} %s\n" "$*" >&2
    _to_log "[+] $*"
}
warn() {
    printf "${_Y}[!]${_R} %s\n" "$*" >&2
    _to_log "[!] $*"
}
error() {
    printf "${_RED}[-]${_R} %s\n" "$*" >&2
    _to_log "[-] $*"
}

usage() {
    cat >&2 <<'USAGE'
Usage: drift audit <project-root> [options]

Run the full audit phase with deterministic gates between steps.

Steps:
  0  Library pull (if online)
  1  Extract + feature extraction (no scoring yet)
  2  Purpose statements (claude -p)
  3  Structural + behavioral audit (claude -p)
  4  Score + cluster with purpose embeddings
  5  Cluster verification + semantic manifest entries (claude -p)
  6  Validate manifest

Options:
  --model <model>        Override Claude model for analytical steps
  --skip-to <N>          Skip to step N (verifies prior gates pass)
  --max-turns <N>        Max agentic turns per Claude call (default: 200)
  --verbose              Stream all output to terminal (always logged to audit.log)
  --dry-run              Print what would run without executing
  -h, --help             Show this help
USAGE
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_log() {
    # Pipe all command output to log file; with --verbose also to terminal.
    if [[ "${VERBOSE:-0}" -eq 1 ]]; then
        tee -a "$LOG_FILE"
    else
        cat >> "$LOG_FILE"
    fi
}

_strip_frontmatter() {
    # Strip YAML frontmatter (--- ... ---) from a markdown file.
    local file="$1"
    python3 -c "
import sys
with open(sys.argv[1]) as f:
    content = f.read()
if content.startswith('---'):
    end = content.find('---', 3)
    if end != -1:
        content = content[end+3:].lstrip('\n')
print(content, end='')
" "$file"
}

_gen_uuid() {
    python3 -c "import uuid; print(uuid.uuid4())"
}

_read_config_mode() {
    python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    print(json.load(f).get('mode', 'offline'))
" "$1" 2>/dev/null || echo "offline"
}

# ---------------------------------------------------------------------------
# Gate functions
# ---------------------------------------------------------------------------

gate_file_exists() {
    local path="$1" label="${2:-$(basename "$1")}"
    if [[ -f "$path" ]]; then
        gate_pass "$label exists"
        return 0
    else
        gate_fail "$label does not exist"
        return 1
    fi
}

gate_json_nonempty_array() {
    local path="$1" key="$2" label="${3:-$2 in $(basename "$1")}"
    if [[ ! -f "$path" ]]; then
        gate_fail "$(basename "$path") does not exist"
        return 1
    fi
    local count
    count="$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
arr = d
for k in sys.argv[2].split('.'):
    if k:
        arr = arr.get(k, []) if isinstance(arr, dict) else []
print(len(arr) if isinstance(arr, list) else 0)
" "$path" "$key" 2>/dev/null || echo "0")"
    if [[ "$count" -gt 0 ]]; then
        gate_pass "$label has $count entries"
        return 0
    else
        gate_fail "$label is empty"
        return 1
    fi
}

gate_manifest_has_type() {
    local manifest="$1" type_val="$2"
    local count
    count="$(python3 -c "
import json, sys
m = json.load(open(sys.argv[1]))
t = sys.argv[2]
# 'structural' is the default when type is absent
if t == 'structural':
    print(sum(1 for a in m.get('areas', []) if a.get('type', 'structural') == t))
else:
    print(sum(1 for a in m.get('areas', []) if a.get('type') == t))
" "$manifest" "$type_val" 2>/dev/null || echo "0")"
    if [[ "$count" -gt 0 ]]; then
        gate_pass "manifest has $count type=$type_val entries"
        return 0
    else
        gate_fail "manifest has no type=$type_val entries"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Claude call wrapper
# ---------------------------------------------------------------------------

_claude_call() {
    local step_name="$1"
    local system_prompt_file="$2"   # empty string if none
    local user_prompt="$3"
    local session_flag="$4"         # e.g. "--session-id UUID" or "--resume UUID"

    local -a cmd=(claude -p)

    # Session management
    if [[ -n "$session_flag" ]]; then
        local flag value
        read -r flag value <<< "$session_flag"
        cmd+=("$flag" "$value")
    fi

    # System prompt — strip frontmatter, write to temp file, pass via --append-system-prompt-file
    local sys_prompt_tmpfile=""
    if [[ -n "$system_prompt_file" ]]; then
        sys_prompt_tmpfile="$(mktemp)"
        _strip_frontmatter "$system_prompt_file" > "$sys_prompt_tmpfile"
        cmd+=(--append-system-prompt-file "$sys_prompt_tmpfile")
    fi

    # Model override
    if [[ -n "${MODEL:-}" ]]; then
        cmd+=(--model "$MODEL")
    fi

    cmd+=(--permission-mode acceptEdits)
    cmd+=(--max-turns "${MAX_TURNS:-200}")
    cmd+=(--allowedTools "Read,Glob,Grep,Bash,Write,Edit,Agent")
    cmd+=(--add-dir "$PROJECT_ROOT")

    info "Claude call: $step_name"

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        info "[DRY RUN] claude -p $session_flag"
        info "[DRY RUN]   --append-system-prompt-file <${system_prompt_file:-none}>"
        info "[DRY RUN]   --permission-mode acceptEdits"
        info "[DRY RUN]   --max-turns ${MAX_TURNS:-200}"
        info "[DRY RUN]   --allowedTools Read,Glob,Grep,Bash,Write,Edit,Agent"
        info "[DRY RUN]   prompt: $(echo "$user_prompt" | head -3)..."
        return 0
    fi

    local exit_code=0

    if [[ "${VERBOSE:-0}" -eq 1 ]]; then
        # Verbose: stream everything to terminal + log
        echo "$user_prompt" | "${cmd[@]}" --verbose 2>&1 | tee -a "$LOG_FILE" || exit_code=$?
    else
        # Non-verbose: output to log only, heartbeat on terminal
        (while true; do sleep 15; printf "." >&2; done) &
        local heartbeat_pid=$!
        echo "$user_prompt" | "${cmd[@]}" >> "$LOG_FILE" 2>&1 || exit_code=$?
        kill "$heartbeat_pid" 2>/dev/null; wait "$heartbeat_pid" 2>/dev/null
        printf "\n" >&2
    fi

    [[ -n "$sys_prompt_tmpfile" ]] && rm -f "$sys_prompt_tmpfile"

    if [[ "$exit_code" -ne 0 ]]; then
        error "Claude call failed: $step_name (exit code: $exit_code)"
        return 1
    fi

    success "Claude completed: $step_name"
    return 0
}

# ---------------------------------------------------------------------------
# Step functions
# ---------------------------------------------------------------------------

step_0_library_pull() {
    step_header 0 "Library Pull"

    local config="$AUDIT_DIR/config.json"
    if [[ ! -f "$config" ]]; then
        info "No config.json — skipping library pull."
        return 0
    fi

    local mode
    mode="$(_read_config_mode "$config")"

    if [[ "$mode" == "online" ]]; then
        if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
            info "[DRY RUN] drift library pull"
            return 0
        fi
        info "Online mode — pulling from library..."
        (cd "$PROJECT_ROOT" && "$DRIFT_HOME/bin/drift" library pull) 2>&1 | _log || warn "Library pull failed (continuing)"
    else
        info "Offline mode — skipping library pull."
    fi
}

step_1_extract() {
    step_header 1 "Extract + Feature Extraction"

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        info "[DRY RUN] extract → ast-grep → fingerprint → typesig → callgraph → depcontext"
        return 0
    fi

    # Extract code units
    info "Extracting code units..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" extract --project "$PROJECT_ROOT") 2>&1 | _log

    gate_file_exists "$CODE_UNITS" "code-units.json" || {
        error "Extraction failed: no code-units.json produced."
        exit 1
    }

    # ast-grep structural patterns (optional)
    info "Running ast-grep..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" ast-grep --project "$PROJECT_ROOT") 2>&1 | _log || warn "ast-grep failed (continuing)"

    # Feature extraction stages — no scoring yet
    info "Computing fingerprints..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" fingerprint) 2>&1 | _log
    info "Computing type signatures..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" typesig) 2>&1 | _log
    info "Computing call graph..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" callgraph) 2>&1 | _log
    info "Computing dependency context..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" depcontext) 2>&1 | _log

    local unit_count
    unit_count="$(python3 -c "import json; d=json.load(open('$CODE_UNITS')); print(len(d.get('units',d)) if isinstance(d,dict) else len(d))" 2>/dev/null || echo "?")"
    success "Extracted $unit_count code units with features. Ready for purpose statements."
}

step_2_purpose_statements() {
    step_header 2 "Purpose Statements (Claude)"

    SESSION_SEMANTIC="$(_gen_uuid)"

    local unit_count
    unit_count="$(python3 -c "import json; d=json.load(open('$CODE_UNITS')); print(len(d.get('units',d)) if isinstance(d,dict) else len(d))" 2>/dev/null || echo "?")"

    local prompt="You are writing purpose statements for code units in: $PROJECT_ROOT

Artifacts from Step 1:
- Code units ($unit_count): $CODE_UNITS

YOUR TASK:
1. Read $CODE_UNITS to understand the extracted units
2. For every component and hook, read the actual source code
3. Write a one-sentence purpose statement describing what each unit DOES functionally
4. Purpose statements should capture the semantic intent, not just restate the name
5. Cover ALL components and hooks at minimum — functions and constants if time allows
6. Save to $PURPOSES as a JSON array of {\"unitId\": \"...\", \"purpose\": \"...\"}

IMPORTANT:
- Focus on functional purpose (\"renders a modal for bulk image tagging\") not structure (\"a React component\")
- These statements will be embedded and used for semantic similarity scoring
- Zero purpose statements is a failure — do not stop until the file is written
- Do NOT run any pipeline commands or modify any other files

Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLE:
- $PURPOSES with purpose statements for all components/hooks"

    _claude_call "purpose statements" \
        "$DRIFT_HOME/skill/drift-audit-semantic/SKILL.md" \
        "$prompt" \
        "--session-id $SESSION_SEMANTIC"

    gate_file_exists "$PURPOSES" "purpose-statements.json" || {
        error "Step 2 failed: no purpose-statements.json produced"
        error "Re-run: drift audit $PROJECT_ROOT --skip-to 2"
        exit 1
    }
    gate_json_nonempty_array "$PURPOSES" "" "purpose statements" || {
        error "Step 2 failed: purpose-statements.json is empty"
        exit 1
    }

    local purpose_count
    purpose_count="$(python3 -c "import json; print(len(json.load(open('$PURPOSES'))))" 2>/dev/null || echo "?")"
    success "$purpose_count purpose statements written."
}

step_3_structural_behavioral() {
    step_header 3 "Structural + Behavioral Audit (Claude)"

    # Check for re-audit
    if [[ -f "$MANIFEST" ]]; then
        info "Existing manifest found — running regression check..."
        ("$DRIFT_HOME/bin/drift" plan-update "$PROJECT_ROOT" --check-regressions) 2>&1 | _log || true
    fi

    # Build combined system prompt from two skill files
    local combined_skill
    combined_skill="$(mktemp)"
    _strip_frontmatter "$DRIFT_HOME/skill/drift-audit/SKILL.md" > "$combined_skill"
    printf '\n\n---\n\n' >> "$combined_skill"
    _strip_frontmatter "$DRIFT_HOME/skill/drift-audit-ux/SKILL.md" >> "$combined_skill"

    SESSION_STRUCTURAL="$(_gen_uuid)"

    local unit_count
    unit_count="$(python3 -c "import json; d=json.load(open('$CODE_UNITS')); print(len(d.get('units',d)) if isinstance(d,dict) else len(d))" 2>/dev/null || echo "?")"

    local prompt="You are running a structural and behavioral drift audit on: $PROJECT_ROOT

Available artifacts:
- Code units ($unit_count units): $CODE_UNITS
- Purpose statements: $PURPOSES

YOUR TASK:
1. Run: bash \"\$DRIFT_SEMANTIC/scripts/discover.sh\" \"$PROJECT_ROOT\"
2. Read the discovery output and explore the codebase — identify structural drift areas
3. Work through all 7 behavioral domain checklists (modals, shared components, workflows, loading/error states, forms, keyboard/a11y, notifications)
4. For EVERY finding: read representative files, extract code excerpts, write 3+ sentence analysis
5. Write ALL findings to $MANIFEST — structural entries with \"type\": \"structural\", behavioral with \"type\": \"behavioral\"
6. Write human-readable report to $AUDIT_DIR/drift-report.md

Use the pipeline's code-units.json to cross-reference extracted units.

IMPORTANT:
- Do NOT perform semantic audit — that is a separate step
- Do NOT re-run the semantic pipeline
- Do NOT write findings.json
- Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLES (must exist when done):
- $MANIFEST with structural + behavioral entries
- $AUDIT_DIR/drift-report.md"

    _claude_call "structural+behavioral audit" "$combined_skill" "$prompt" "--session-id $SESSION_STRUCTURAL"

    rm -f "$combined_skill"

    gate_file_exists "$MANIFEST" "drift-manifest.json" || {
        error "Step 3 failed: no drift-manifest.json produced"
        error "Re-run: drift audit $PROJECT_ROOT --skip-to 3"
        exit 1
    }
    gate_json_nonempty_array "$MANIFEST" "areas" "manifest areas" || {
        error "Step 3 failed: manifest has no areas"
        exit 1
    }
}

step_4_score_cluster() {
    step_header 4 "Score + Cluster (with purpose embeddings)"

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        info "[DRY RUN] ingest-purposes → embed → score → cluster → css-extract → css-score → report"
        return 0
    fi

    info "Ingesting purpose statements..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" ingest-purposes --file "$PURPOSES") 2>&1 | _log
    info "Embedding purpose statements..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" embed) 2>&1 | _log
    info "Scoring pairwise similarity..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" score) 2>&1 | _log
    info "Clustering..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" cluster) 2>&1 | _log
    info "Extracting CSS units..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" css-extract --project "$PROJECT_ROOT") 2>&1 | _log
    info "Scoring CSS similarity..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" css-score) 2>&1 | _log
    info "Generating report..."
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" report --manifest "$MANIFEST_PATH") 2>&1 | _log || {
        (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" report) 2>&1 | _log || warn "Report generation failed (continuing)"
    }

    gate_file_exists "$CLUSTERS" "clusters.json" || {
        error "Step 4 failed: no clusters.json produced"
        exit 1
    }

    local cluster_count
    cluster_count="$(python3 -c "import json; print(len(json.load(open('$CLUSTERS'))))" 2>/dev/null || echo "?")"
    success "$cluster_count clusters found (purpose-informed scoring)."
}

step_5_cluster_verification() {
    step_header 5 "Cluster Verification + Semantic Manifest Entries (Claude)"

    local cluster_count
    cluster_count="$(python3 -c "import json; print(len(json.load(open('$CLUSTERS'))))" 2>/dev/null || echo "?")"

    local prompt="You are verifying semantic clusters and adding findings for: $PROJECT_ROOT

These clusters were scored WITH purpose statement embeddings — they are
semantically informed, not just structurally similar.

CONTEXT:
- Clusters ($cluster_count, purpose-informed): $CLUSTERS
- Purpose statements: $PURPOSES
- Current manifest: $MANIFEST

PHASE 1 — VERIFY CLUSTERS (mandatory):
1. Read $CLUSTERS
2. For the top 10-20 ranked clusters, read the source code of each member
3. Classify each cluster: DUPLICATE / OVERLAPPING / RELATED / FALSE_POSITIVE
4. Include code_excerpts (5-15 lines) for each member in your verdicts
5. Write verdicts to $FINDINGS (JSON array)

PHASE 2 — ADD SEMANTIC MANIFEST ENTRIES:
1. For each DUPLICATE or OVERLAPPING cluster, add a type:semantic entry to $MANIFEST
2. Each semantic entry MUST include code_excerpts and reference the purpose statements
   that reveal the duplication
3. Update the manifest summary counts after adding entries

Do NOT duplicate existing manifest entries. Only add NEW semantic findings.
Do NOT remove or modify structural/behavioral entries.

Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLES:
- $FINDINGS with cluster verdicts
- $MANIFEST updated with type:semantic entries"

    _claude_call "cluster verification" \
        "$DRIFT_HOME/skill/drift-audit-semantic/SKILL.md" \
        "$prompt" \
        "--resume $SESSION_SEMANTIC"

    gate_file_exists "$FINDINGS" "findings.json" || {
        error "Step 5 failed: no findings.json produced"
        error "Re-run: drift audit $PROJECT_ROOT --skip-to 5"
        exit 1
    }

    # Soft gate — warn but don't fail
    if ! gate_manifest_has_type "$MANIFEST" "semantic"; then
        warn "No type=semantic entries in manifest."
        warn "This may be valid for small codebases with no semantic duplication."
        warn "If the project has significant duplication, re-run: drift audit $PROJECT_ROOT --skip-to 5"
    fi
}

step_6_validate() {
    step_header 6 "Validate Manifest"

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        info "[DRY RUN] drift validate $PROJECT_ROOT --fix-summary"
        success "Audit dry-run complete."
        return 0
    fi

    info "Running quality gate..."
    ("$DRIFT_HOME/bin/drift" validate "$PROJECT_ROOT" --fix-summary) 2>&1 | _log || {
        warn "Quality gate found failures — some areas may need richer evidence."
    }

    success "Audit complete."
    echo "" >&2
    info "Artifacts:"
    info "  Manifest:  $MANIFEST"
    info "  Report:    $AUDIT_DIR/drift-report.md"
    info "  Clusters:  $CLUSTERS"
    info "  Findings:  $FINDINGS"
    info "  Purposes:  $PURPOSES"
    info "  Log:       $LOG_FILE"
    echo "" >&2
    info "Next steps:"
    info "  drift plan $PROJECT_ROOT      — build prioritized attack plan"
    info "  drift validate $PROJECT_ROOT  — re-run quality gate"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

PROJECT_ROOT=""
MODEL=""
SKIP_TO=0
MAX_TURNS="200"
VERBOSE=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)      MODEL="$2"; shift 2 ;;
        --skip-to)    SKIP_TO="$2"; shift 2 ;;
        --max-turns)  MAX_TURNS="$2"; shift 2 ;;
        --verbose)    VERBOSE=1; shift ;;
        --dry-run)    DRY_RUN=1; shift ;;
        -h|--help)    usage; exit 0 ;;
        *)
            if [[ -z "$PROJECT_ROOT" ]]; then
                PROJECT_ROOT="$1"
            else
                error "Unknown argument: $1"
                usage
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$PROJECT_ROOT" ]]; then
    error "project-root argument is required"
    usage
    exit 1
fi

PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"

# Derived paths
AUDIT_DIR="$PROJECT_ROOT/.drift-audit"
SEMANTIC_DIR="$AUDIT_DIR/semantic"
MANIFEST="$AUDIT_DIR/drift-manifest.json"
MANIFEST_PATH="$MANIFEST"
FINDINGS="$SEMANTIC_DIR/findings.json"
PURPOSES="$SEMANTIC_DIR/purpose-statements.json"
CLUSTERS="$SEMANTIC_DIR/clusters.json"
CODE_UNITS="$SEMANTIC_DIR/code-units.json"

# Log file — all deterministic and claude output goes here
LOG_FILE="$AUDIT_DIR/audit.log"
mkdir -p "$AUDIT_DIR"
: > "$LOG_FILE"   # truncate on fresh run

# Session IDs (set by step functions)
SESSION_STRUCTURAL=""
SESSION_SEMANTIC=""

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

command -v claude &>/dev/null || {
    error "claude CLI not found in PATH"
    error "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
    exit 1
}

if [[ "${CLAUDECODE:-0}" == "1" ]]; then
    warn "Running inside an existing Claude session."
    warn "Claude -p calls will spawn separate subprocess sessions."
fi

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

info "Drift audit orchestrator"
info "Project: $PROJECT_ROOT"
info "Drift:   $DRIFT_HOME"
info "Log:     $LOG_FILE"
[[ -n "$MODEL" ]] && info "Model:   $MODEL"
[[ "$SKIP_TO" -gt 0 ]] && info "Skip to: step $SKIP_TO"
[[ "$VERBOSE" -eq 1 ]] && info "Verbose: on"
echo "" >&2

# Verify skip-to gates
if [[ "$SKIP_TO" -ge 2 ]]; then
    info "Verifying gates for step 1..."
    gate_file_exists "$CODE_UNITS" "code-units.json" || exit 1
fi
if [[ "$SKIP_TO" -ge 3 ]]; then
    info "Verifying gates for step 2..."
    gate_file_exists "$PURPOSES" "purpose-statements.json" || exit 1
    gate_json_nonempty_array "$PURPOSES" "" "purpose statements" || exit 1
fi
if [[ "$SKIP_TO" -ge 4 ]]; then
    info "Verifying gates for step 3..."
    gate_file_exists "$MANIFEST" "drift-manifest.json" || exit 1
    gate_json_nonempty_array "$MANIFEST" "areas" "manifest areas" || exit 1
fi
if [[ "$SKIP_TO" -ge 5 ]]; then
    info "Verifying gates for step 4..."
    gate_file_exists "$CLUSTERS" "clusters.json" || exit 1
fi
if [[ "$SKIP_TO" -ge 6 ]]; then
    info "Verifying gates for step 5..."
    gate_file_exists "$FINDINGS" "findings.json" || exit 1
fi

# Run steps
[[ "$SKIP_TO" -le 0 ]] && step_0_library_pull
[[ "$SKIP_TO" -le 1 ]] && step_1_extract
[[ "$SKIP_TO" -le 2 ]] && step_2_purpose_statements
[[ "$SKIP_TO" -le 3 ]] && step_3_structural_behavioral
[[ "$SKIP_TO" -le 4 ]] && step_4_score_cluster
[[ "$SKIP_TO" -le 5 ]] && step_5_cluster_verification
[[ "$SKIP_TO" -le 6 ]] && step_6_validate
