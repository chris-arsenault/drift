#!/usr/bin/env bash
# audit-orchestrate.sh — Deterministic orchestrator for the drift audit phase.
#
# Runs the full audit as a sequence of deterministic steps and gated Claude -p
# calls.  Each analytical step must produce specific artifacts before the next
# step can begin.
#
# Usage:
#   drift audit <project-root> [options]
#
# Options:
#   --model <model>        Override Claude model for analytical steps
#   --skip-to <N>          Skip to step N (verifies prior gates)
#   --max-budget <USD>     Max budget per Claude call (default: 5.00)
#   --verbose              Show full Claude -p output
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

step_header() { printf "\n${_BOLD}${_B}=== STEP %s: %s ===${_R}\n" "$1" "$2" >&2; }
gate_pass()   { printf "${_G}  GATE: %s${_R}\n" "$*" >&2; }
gate_fail()   { printf "${_RED}  GATE FAILED: %s${_R}\n" "$*" >&2; }
info()        { printf "${_B}[*]${_R} %s\n" "$*" >&2; }
success()     { printf "${_G}[+]${_R} %s\n" "$*" >&2; }
warn()        { printf "${_Y}[!]${_R} %s\n" "$*" >&2; }
error()       { printf "${_RED}[-]${_R} %s\n" "$*" >&2; }

usage() {
    cat >&2 <<'USAGE'
Usage: drift audit <project-root> [options]

Run the full audit phase with deterministic gates between steps.

Options:
  --model <model>        Override Claude model for analytical steps
  --skip-to <N>          Skip to step N (verifies prior gates pass)
  --max-budget <USD>     Max budget per Claude -p call (default: 5.00)
  --verbose              Show full Claude -p output
  --dry-run              Print what would run without executing
  -h, --help             Show this help
USAGE
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

    # System prompt — strip frontmatter and inject
    if [[ -n "$system_prompt_file" ]]; then
        local sys_prompt
        sys_prompt="$(_strip_frontmatter "$system_prompt_file")"
        cmd+=(--append-system-prompt "$sys_prompt")
    fi

    # Model override
    if [[ -n "${MODEL:-}" ]]; then
        cmd+=(--model "$MODEL")
    fi

    cmd+=(--permission-mode acceptEdits)
    cmd+=(--max-budget-usd "${MAX_BUDGET:-5.00}")
    cmd+=(--allowedTools "Read,Glob,Grep,Bash,Write,Edit,Agent")
    cmd+=(--add-dir "$PROJECT_ROOT")

    info "Claude call: $step_name"

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        info "[DRY RUN] claude -p $session_flag"
        info "[DRY RUN]   --append-system-prompt <${system_prompt_file:-none}>"
        info "[DRY RUN]   --permission-mode acceptEdits"
        info "[DRY RUN]   --max-budget-usd ${MAX_BUDGET:-5.00}"
        info "[DRY RUN]   --allowedTools Read,Glob,Grep,Bash,Write,Edit,Agent"
        info "[DRY RUN]   prompt: $(echo "$user_prompt" | head -3)..."
        return 0
    fi

    # Log all claude output; show on terminal only in verbose mode
    local safe_name="${step_name// /-}"
    local log_file="$AUDIT_DIR/claude-${safe_name}.log"
    mkdir -p "$AUDIT_DIR"
    local exit_code=0

    if [[ "${VERBOSE:-0}" -eq 1 ]]; then
        "${cmd[@]}" "$user_prompt" 2>&1 | tee "$log_file" || exit_code=$?
    else
        "${cmd[@]}" "$user_prompt" > "$log_file" 2>&1 || exit_code=$?
    fi

    if [[ "$exit_code" -ne 0 ]]; then
        error "Claude call failed: $step_name (exit code: $exit_code)"
        error "Log: $log_file"
        return 1
    fi

    success "Claude completed: $step_name"
    info "Log: $log_file"
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
        (cd "$PROJECT_ROOT" && "$DRIFT_HOME/bin/drift" library pull) || warn "Library pull failed (continuing)"
    else
        info "Offline mode — skipping library pull."
    fi
}

step_1_pipeline() {
    step_header 1 "Semantic Pipeline"

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        info "[DRY RUN] bash cli.sh run --project $PROJECT_ROOT"
        return 0
    fi

    # Run from project root so relative OUTPUT_DIR resolves correctly
    (cd "$PROJECT_ROOT" && bash "$DRIFT_HOME/cli.sh" run --project "$PROJECT_ROOT")

    gate_file_exists "$CODE_UNITS" "code-units.json" || {
        error "Pipeline failed: no code-units.json produced."
        error "Run 'cd $PROJECT_ROOT && bash \$DRIFT_SEMANTIC/cli.sh run --project .' to diagnose."
        exit 1
    }
    gate_file_exists "$CLUSTERS" "clusters.json" || {
        warn "clusters.json not produced — running stages individually..."
        (cd "$PROJECT_ROOT" && \
            bash "$DRIFT_HOME/cli.sh" fingerprint && \
            bash "$DRIFT_HOME/cli.sh" typesig && \
            bash "$DRIFT_HOME/cli.sh" callgraph && \
            bash "$DRIFT_HOME/cli.sh" depcontext && \
            bash "$DRIFT_HOME/cli.sh" score && \
            bash "$DRIFT_HOME/cli.sh" cluster && \
            bash "$DRIFT_HOME/cli.sh" css-extract --project "$PROJECT_ROOT" && \
            bash "$DRIFT_HOME/cli.sh" css-score && \
            bash "$DRIFT_HOME/cli.sh" report)
        gate_file_exists "$CLUSTERS" "clusters.json" || {
            error "Pipeline failed even with individual stages."
            exit 1
        }
    }
}

step_2_structural_behavioral() {
    step_header 2 "Structural + Behavioral Audit (Claude)"

    # Check for re-audit
    if [[ -f "$MANIFEST" ]]; then
        info "Existing manifest found — running regression check..."
        "$DRIFT_HOME/bin/drift" plan-update "$PROJECT_ROOT" --check-regressions || true
    fi

    # Build combined system prompt from two skill files
    local combined_skill
    combined_skill="$(mktemp)"
    _strip_frontmatter "$DRIFT_HOME/skill/drift-audit/SKILL.md" > "$combined_skill"
    printf '\n\n---\n\n' >> "$combined_skill"
    _strip_frontmatter "$DRIFT_HOME/skill/drift-audit-ux/SKILL.md" >> "$combined_skill"

    SESSION_STRUCTURAL="$(_gen_uuid)"

    local unit_count cluster_count
    unit_count="$(python3 -c "import json; d=json.load(open('$CODE_UNITS')); print(len(d.get('units',d)) if isinstance(d,dict) else len(d))" 2>/dev/null || echo "?")"
    cluster_count="$(python3 -c "import json; print(len(json.load(open('$CLUSTERS'))))" 2>/dev/null || echo "?")"

    local prompt="You are running a structural and behavioral drift audit on: $PROJECT_ROOT

The semantic pipeline has already run and produced:
- Code units ($unit_count units): $CODE_UNITS
- Clusters ($cluster_count clusters): $CLUSTERS
- Report: $SEMANTIC_DIR/semantic-drift-report.md

YOUR TASK:
1. Run: bash \"\$DRIFT_SEMANTIC/scripts/discover.sh\" \"$PROJECT_ROOT\"
2. Read the discovery output and explore the codebase — identify structural drift areas
3. Work through all 7 behavioral domain checklists (modals, shared components, workflows, loading/error states, forms, keyboard/a11y, notifications)
4. For EVERY finding: read representative files, extract code excerpts, write 3+ sentence analysis
5. Write ALL findings to $MANIFEST — structural entries with \"type\": \"structural\", behavioral with \"type\": \"behavioral\"
6. Write human-readable report to $AUDIT_DIR/drift-report.md

Use the pipeline's code-units.json and clusters to cross-reference extracted units.

IMPORTANT:
- Do NOT perform semantic audit — that is a separate step
- Do NOT re-run the semantic pipeline
- Do NOT write purpose statements or findings.json
- Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLES (must exist when done):
- $MANIFEST with structural + behavioral entries
- $AUDIT_DIR/drift-report.md"

    _claude_call "structural+behavioral audit" "$combined_skill" "$prompt" "--session-id $SESSION_STRUCTURAL"

    rm -f "$combined_skill"

    gate_file_exists "$MANIFEST" "drift-manifest.json" || {
        error "Step 2 failed: no drift-manifest.json produced"
        error "Re-run: drift audit $PROJECT_ROOT --skip-to 2"
        exit 1
    }
    gate_json_nonempty_array "$MANIFEST" "areas" "manifest areas" || {
        error "Step 2 failed: manifest has no areas"
        exit 1
    }
}

step_3_semantic() {
    step_header 3 "Semantic Audit — Clusters + Purpose Statements (Claude)"

    SESSION_SEMANTIC="$(_gen_uuid)"

    local unit_count cluster_count
    unit_count="$(python3 -c "import json; d=json.load(open('$CODE_UNITS')); print(len(d.get('units',d)) if isinstance(d,dict) else len(d))" 2>/dev/null || echo "?")"
    cluster_count="$(python3 -c "import json; print(len(json.load(open('$CLUSTERS'))))" 2>/dev/null || echo "?")"

    local prompt="You are running a semantic drift audit on: $PROJECT_ROOT

Artifacts from earlier steps:
- Code units ($unit_count): $CODE_UNITS
- Clusters ($cluster_count): $CLUSTERS
- Existing manifest: $MANIFEST

PHASE 1 — VERIFY CLUSTERS (mandatory):
1. Read $CLUSTERS
2. For the top 10-20 ranked clusters, read the source code of each member
3. Classify each cluster: DUPLICATE / OVERLAPPING / RELATED / FALSE_POSITIVE
4. Include code_excerpts (5-15 lines) for each member in your verdicts
5. Write verdicts to $FINDINGS (JSON array)

PHASE 2 — PURPOSE STATEMENTS (mandatory — do NOT skip):
1. Read $CODE_UNITS
2. For every component and hook, read the source code
3. Write a one-sentence purpose statement describing what each unit DOES functionally
4. Cover ALL components and hooks at minimum
5. Save to $PURPOSES as JSON array of {\"unitId\": \"...\", \"purpose\": \"...\"}

Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLES (both must exist when done):
- $FINDINGS with cluster verdicts
- $PURPOSES with purpose statements for all components/hooks

Zero purpose statements is a failure. Do not stop until both files are written."

    _claude_call "semantic audit" \
        "$DRIFT_HOME/skill/drift-audit-semantic/SKILL.md" \
        "$prompt" \
        "--session-id $SESSION_SEMANTIC"

    gate_file_exists "$FINDINGS" "findings.json" || {
        error "Step 3 failed: no findings.json produced"
        error "Re-run: drift audit $PROJECT_ROOT --skip-to 3"
        exit 1
    }
    gate_file_exists "$PURPOSES" "purpose-statements.json" || {
        error "Step 3 failed: no purpose-statements.json produced"
        error "This is the most commonly skipped artifact."
        error "Re-run: drift audit $PROJECT_ROOT --skip-to 3"
        exit 1
    }
    gate_json_nonempty_array "$PURPOSES" "" "purpose statements" || {
        error "Step 3 failed: purpose-statements.json is empty"
        exit 1
    }
}

step_4_rerun_pipeline() {
    step_header 4 "Re-run Pipeline with Purpose Statements"

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        info "[DRY RUN] ingest-purposes → embed → score → cluster → report"
        return 0
    fi

    (cd "$PROJECT_ROOT" && \
        info "Ingesting purpose statements..." && \
        bash "$DRIFT_HOME/cli.sh" ingest-purposes --file "$PURPOSES" && \
        info "Embedding..." && \
        bash "$DRIFT_HOME/cli.sh" embed && \
        info "Re-scoring..." && \
        bash "$DRIFT_HOME/cli.sh" score && \
        info "Re-clustering..." && \
        bash "$DRIFT_HOME/cli.sh" cluster && \
        info "Re-generating report..." && \
        bash "$DRIFT_HOME/cli.sh" report)

    gate_file_exists "$CLUSTERS" "updated clusters.json" || {
        error "Step 4 failed: re-run did not produce updated clusters"
        exit 1
    }
}

step_5_review_refined() {
    step_header 5 "Review Refined Clusters + Semantic Manifest Entries (Claude)"

    local cluster_count
    cluster_count="$(python3 -c "import json; print(len(json.load(open('$CLUSTERS'))))" 2>/dev/null || echo "?")"

    local prompt="You are reviewing REFINED semantic clusters for: $PROJECT_ROOT

The pipeline was re-run with purpose statement embeddings.

CONTEXT:
- Updated clusters ($cluster_count): $CLUSTERS
- Your previous findings: $FINDINGS
- Your purpose statements: $PURPOSES
- Current manifest: $MANIFEST

INSTRUCTIONS:
1. Read the updated $CLUSTERS
2. Compare with your previous $FINDINGS — note new clusters or rank changes
3. For each DUPLICATE or OVERLAPPING cluster, add a type:semantic entry to $MANIFEST
4. Each semantic entry MUST include code_excerpts and reference the purpose statements that reveal the duplication
5. Update the manifest summary counts after adding entries

Do NOT duplicate existing manifest entries. Only add NEW semantic findings.
Do NOT remove or modify structural/behavioral entries.

Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLES:
- $MANIFEST updated with type:semantic entries"

    _claude_call "review refined clusters" \
        "$DRIFT_HOME/skill/drift-audit-semantic/SKILL.md" \
        "$prompt" \
        "--resume $SESSION_SEMANTIC"

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
    "$DRIFT_HOME/bin/drift" validate "$PROJECT_ROOT" --fix-summary || {
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
MAX_BUDGET="5.00"
VERBOSE=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)      MODEL="$2"; shift 2 ;;
        --skip-to)    SKIP_TO="$2"; shift 2 ;;
        --max-budget) MAX_BUDGET="$2"; shift 2 ;;
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
FINDINGS="$SEMANTIC_DIR/findings.json"
PURPOSES="$SEMANTIC_DIR/purpose-statements.json"
CLUSTERS="$SEMANTIC_DIR/clusters.json"
CODE_UNITS="$SEMANTIC_DIR/code-units.json"

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
[[ -n "$MODEL" ]] && info "Model:   $MODEL"
[[ "$SKIP_TO" -gt 0 ]] && info "Skip to: step $SKIP_TO"
echo "" >&2

# Verify skip-to gates
if [[ "$SKIP_TO" -ge 2 ]]; then
    info "Verifying gates for steps 0-1..."
    gate_file_exists "$CODE_UNITS" "code-units.json" || exit 1
    gate_file_exists "$CLUSTERS" "clusters.json" || exit 1
fi
if [[ "$SKIP_TO" -ge 3 ]]; then
    info "Verifying gates for step 2..."
    gate_file_exists "$MANIFEST" "drift-manifest.json" || exit 1
    gate_json_nonempty_array "$MANIFEST" "areas" "manifest areas" || exit 1
fi
if [[ "$SKIP_TO" -ge 4 ]]; then
    info "Verifying gates for step 3..."
    gate_file_exists "$FINDINGS" "findings.json" || exit 1
    gate_file_exists "$PURPOSES" "purpose-statements.json" || exit 1
fi

# Run steps
[[ "$SKIP_TO" -le 0 ]] && step_0_library_pull
[[ "$SKIP_TO" -le 1 ]] && step_1_pipeline
[[ "$SKIP_TO" -le 2 ]] && step_2_structural_behavioral
[[ "$SKIP_TO" -le 3 ]] && step_3_semantic
[[ "$SKIP_TO" -le 4 ]] && step_4_rerun_pipeline
[[ "$SKIP_TO" -le 5 ]] && step_5_review_refined
[[ "$SKIP_TO" -le 6 ]] && step_6_validate
