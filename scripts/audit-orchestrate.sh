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
    cmd+=(--output-format stream-json)
    cmd+=(--add-dir "$PROJECT_ROOT")

    info "Claude call: $step_name"

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        info "[DRY RUN] claude -p $session_flag"
        info "[DRY RUN]   --append-system-prompt-file <${system_prompt_file:-none}>"
        info "[DRY RUN]   --permission-mode acceptEdits"
        info "[DRY RUN]   --max-turns ${MAX_TURNS:-200}"
        info "[DRY RUN]   --output-format stream-json"
        info "[DRY RUN]   --allowedTools Read,Glob,Grep,Bash,Write,Edit,Agent"
        info "[DRY RUN]   prompt: $(echo "$user_prompt" | head -3)..."
        return 0
    fi

    local exit_code=0

    # stream-json outputs events in real-time.
    # Always: pipe through stream-progress.py (filters to human-readable on stderr, raw JSON to log).
    # Verbose: also pass --verbose to claude for turn-by-turn detail in the stream.
    if [[ "${VERBOSE:-0}" -eq 1 ]]; then
        cmd+=(--verbose)
    fi

    echo "$user_prompt" | "${cmd[@]}" 2>&1 \
        | python3 -u "$DRIFT_HOME/scripts/stream-progress.py" "$LOG_FILE" || exit_code=$?

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

    # Skip if code units already exist
    if [[ -f "$CODE_UNITS" ]]; then
        local existing_count
        existing_count="$(python3 -c "import json; d=json.load(open('$CODE_UNITS')); print(len(d.get('units',d)) if isinstance(d,dict) else len(d))" 2>/dev/null || echo "0")"
        if [[ "$existing_count" -gt 0 ]]; then
            success "Reusing $existing_count existing code units. Delete $CODE_UNITS to re-extract."
            return 0
        fi
    fi

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

    # Deterministically compute which units need purpose statements.
    # Writes a work file so Claude doesn't waste turns figuring out the diff.
    local work_file="$AUDIT_DIR/purpose-work.json"
    local work_result
    work_result="$(python3 -c "
import json, sys

units_path, purposes_path, work_path = sys.argv[1], sys.argv[2], sys.argv[3]

# Load all units
raw = json.load(open(units_path))
units = raw.get('units', raw) if isinstance(raw, dict) else raw

# Load existing purposes (if any)
existing = []
covered_ids = set()
try:
    existing = json.load(open(purposes_path))
    covered_ids = {p.get('unitId','') for p in existing if isinstance(p, dict)}
except (FileNotFoundError, json.JSONDecodeError):
    pass

# Find uncovered units — strip sourceCode to keep the file small
missing = []
for u in units:
    if not isinstance(u, dict):
        continue
    if u.get('id','') in covered_ids:
        continue
    slim = {k: u[k] for k in ('id','name','kind','filePath','lineRange') if k in u}
    missing.append(slim)

# Write work file
json.dump(missing, open(work_path, 'w'), indent=2)
print(f'{len(existing)}|{len(units)}|{len(missing)}')
" "$CODE_UNITS" "$PURPOSES" "$work_file" 2>/dev/null || echo "0|0|0")"

    local existing_count unit_count missing_count
    IFS='|' read -r existing_count unit_count missing_count <<< "$work_result"

    if [[ "$missing_count" == "0" ]]; then
        success "All $existing_count purpose statements present ($unit_count units). Nothing to add."
        rm -f "$work_file"
        return 0
    fi

    info "$existing_count existing, $missing_count units need purpose statements (of $unit_count total)."

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        info "[DRY RUN] Would call Claude to write $missing_count purpose statements"
        rm -f "$work_file"
        return 0
    fi

    # Build prompt — Claude gets the pre-computed work file, not the full code-units.json
    local output_file="$AUDIT_DIR/purpose-new.json"
    local prompt="You are writing purpose statements for code units in: $PROJECT_ROOT

INPUT:
- Units needing statements ($missing_count): $work_file
  Each entry has: id, name, kind, filePath, lineRange
- Full code units (for source reference): $CODE_UNITS

YOUR TASK:
1. Read $work_file — this lists EXACTLY the $missing_count units that need statements
2. For each unit, read its source code at the filePath/lineRange shown
3. Write a one-sentence purpose statement describing what it DOES functionally
4. Save to $output_file as a JSON array of {\"unitId\": \"...\", \"purpose\": \"...\"}

IMPORTANT:
- Focus on functional purpose (\"renders a modal for bulk image tagging\") not structure (\"a React component\")
- These statements will be embedded and used for semantic similarity scoring
- Write statements for ALL $missing_count units in $work_file — do not skip any
- Do NOT read or modify $PURPOSES — the orchestrator handles merging
- Do NOT run any pipeline commands or modify any other files

Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLE:
- $output_file with $missing_count purpose statements"

    _claude_call "purpose statements" \
        "$DRIFT_HOME/skill/drift-audit-semantic/SKILL.md" \
        "$prompt" \
        "--session-id $SESSION_SEMANTIC"

    # Deterministic merge: combine existing + new
    if [[ -f "$output_file" ]]; then
        python3 -c "
import json, sys
existing_path, new_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

existing = []
try:
    existing = json.load(open(existing_path))
except (FileNotFoundError, json.JSONDecodeError):
    pass

new = json.load(open(new_path))
if not isinstance(new, list):
    new = []

# Deduplicate by unitId (existing wins on conflict)
seen = {p.get('unitId','') for p in existing if isinstance(p, dict)}
for p in new:
    if isinstance(p, dict) and p.get('unitId','') not in seen:
        existing.append(p)
        seen.add(p.get('unitId',''))

json.dump(existing, open(out_path, 'w'), indent=2)
print(f'Merged: {len(existing)} total ({len(new)} new)')
" "$PURPOSES" "$output_file" "$PURPOSES" 2>&1 | _log
        rm -f "$output_file"
    fi

    rm -f "$work_file"

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
    success "$purpose_count total purpose statements ($missing_count new)."
}

step_3_structural_behavioral() {
    step_header 3 "Structural + Behavioral Audit (Claude)"

    # Check for re-audit
    if [[ -f "$MANIFEST" ]]; then
        info "Existing manifest found — running regression check..."
        ("$DRIFT_HOME/bin/drift" plan-update "$PROJECT_ROOT" --check-regressions) 2>&1 | _log || true
    fi

    local unit_count
    unit_count="$(python3 -c "import json; d=json.load(open('$CODE_UNITS')); print(len(d.get('units',d)) if isinstance(d,dict) else len(d))" 2>/dev/null || echo "?")"

    local partials_dir="$AUDIT_DIR/partials"
    mkdir -p "$partials_dir"

    # ---- Step 3a: Discovery + structural audit (one call) ----
    info "Step 3a: Structural audit..."

    local structural_skill
    structural_skill="$(mktemp)"
    _strip_frontmatter "$DRIFT_HOME/skill/drift-audit/SKILL.md" > "$structural_skill"

    local structural_prompt="You are running a STRUCTURAL drift audit on: $PROJECT_ROOT

Available artifacts:
- Code units ($unit_count units): $CODE_UNITS
- Purpose statements: $PURPOSES

YOUR TASK:
1. Run: bash \"\$DRIFT_SEMANTIC/scripts/discover.sh\" \"$PROJECT_ROOT\"
2. Read the discovery output and explore the codebase
3. Identify structural drift areas: inconsistent project structure, naming conventions,
   file organization, import patterns, TypeScript vs JavaScript migration state, etc.
4. For EVERY finding: read representative files, extract code excerpts, write 3+ sentence analysis
5. Write findings to $partials_dir/structural.json as a JSON array of manifest area objects
   (each with \"type\": \"structural\")

IMPORTANT:
- ONLY structural drift — do NOT audit behavioral domains (modals, forms, etc.)
- Do NOT write to $MANIFEST directly — write to $partials_dir/structural.json
- Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLE:
- $partials_dir/structural.json (JSON array of manifest area entries)"

    _claude_call "structural audit" "$structural_skill" "$structural_prompt" "--session-id $(_gen_uuid)"
    rm -f "$structural_skill"

    gate_file_exists "$partials_dir/structural.json" "structural.json" || {
        warn "Structural audit produced no output — continuing with behavioral domains"
    }

    # ---- Step 3b: Behavioral domain audits (one call per domain) ----
    # Each domain gets its own session and writes to its own partial file.

    local ux_skill
    ux_skill="$(mktemp)"
    _strip_frontmatter "$DRIFT_HOME/skill/drift-audit-ux/SKILL.md" > "$ux_skill"

    local -a domains=(
        "modals|Modal/Dialog Interaction Consistency|modal,dialog,overlay,ModalShell,onClose,Escape"
        "shared-components|Shared Component Adoption|shared-components,shared component library,ad-hoc alternative"
        "workflows|Multi-Step Workflow Consistency|workflow,multi-step,wizard,queue,review step,confirmation"
        "loading-errors|Loading & Error State Patterns|loading,isLoading,error,isEmpty,skeleton,spinner,error boundary"
        "forms|Form Validation & Input Behavior|form,validation,onBlur,onSubmit,dirty,unsaved changes"
        "keyboard-a11y|Keyboard & Accessibility Patterns|keydown,focus,aria-,tabIndex,autoFocus,screen reader"
        "notifications|Notification & Feedback Patterns|toast,notification,snackbar,feedback,success message,error message"
    )

    local domain_spec domain_id domain_name domain_hints
    for domain_spec in "${domains[@]}"; do
        IFS='|' read -r domain_id domain_name domain_hints <<< "$domain_spec"

        info "Step 3b: $domain_name..."

        local domain_prompt="You are auditing a SINGLE behavioral domain on: $PROJECT_ROOT

DOMAIN: $domain_name
Search hints: $domain_hints

Available artifacts:
- Code units ($unit_count units): $CODE_UNITS

YOUR TASK:
1. Search the codebase for patterns related to this domain (use the search hints above)
2. Read representative files to understand how this domain is implemented across apps
3. Build a comparison matrix showing variant implementations
4. For EVERY finding: include code excerpts (5-15 lines) and 3+ sentence analysis
5. Write findings to $partials_dir/$domain_id.json as a JSON array of manifest area objects
   (each with \"type\": \"behavioral\", \"domain\": \"$domain_name\")

If this domain does not apply to the project (no relevant patterns found), write an empty
array [] to the output file and move on.

IMPORTANT:
- ONLY audit this ONE domain — do not explore other domains
- Do NOT write to $MANIFEST directly — write to $partials_dir/$domain_id.json
- Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLE:
- $partials_dir/$domain_id.json (JSON array of manifest area entries, or [] if not applicable)"

        _claude_call "$domain_name" "$ux_skill" "$domain_prompt" "--session-id $(_gen_uuid)"

        gate_file_exists "$partials_dir/$domain_id.json" "$domain_id.json" || {
            warn "$domain_name produced no output — writing empty array"
            echo '[]' > "$partials_dir/$domain_id.json"
        }
    done

    rm -f "$ux_skill"

    # ---- Step 3c: Deterministic merge ----
    info "Step 3c: Merging partial results..."

    python3 -u "$DRIFT_HOME/scripts/merge-audit-partials.py" \
        "$partials_dir" "$MANIFEST" "$AUDIT_DIR/drift-report.md" 2>&1 | _log

    gate_file_exists "$MANIFEST" "drift-manifest.json" || {
        error "Step 3 failed: merge produced no drift-manifest.json"
        error "Re-run: drift audit $PROJECT_ROOT --skip-to 3"
        exit 1
    }
    gate_json_nonempty_array "$MANIFEST" "areas" "manifest areas" || {
        error "Step 3 failed: manifest has no areas"
        exit 1
    }

    local area_count
    area_count="$(python3 -c "import json; print(len(json.load(open('$MANIFEST')).get('areas',[])))" 2>/dev/null || echo "?")"
    success "Merged $area_count areas from $(ls "$partials_dir"/*.json 2>/dev/null | wc -l) partial files."
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

    # Resume the semantic session if step 2 ran in this invocation;
    # otherwise start a fresh session (step 2 was skipped due to reuse).
    local session_flag
    if [[ -n "$SESSION_SEMANTIC" ]]; then
        session_flag="--resume $SESSION_SEMANTIC"
    else
        session_flag="--session-id $(_gen_uuid)"
    fi

    _claude_call "cluster verification" \
        "$DRIFT_HOME/skill/drift-audit-semantic/SKILL.md" \
        "$prompt" \
        "$session_flag"

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
