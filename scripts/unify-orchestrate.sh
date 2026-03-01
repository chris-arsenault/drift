#!/usr/bin/env bash
# unify-orchestrate.sh — Deterministic orchestrator for drift unify+guard.
#
# For each eligible area: unify (claude -p) → gate → guard (claude -p) → gate → finalize.
# Unify and guard are atomic per area so the guard agent has full context of
# what was just refactored.
#
# Usage:
#   drift unify <project-root> [options]
#
# Options:
#   --area <id>            Only process this specific area
#   --model <model>        Override Claude model
#   --max-turns <N>        Max agentic turns per Claude call (default: 200)
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

_to_log() { [[ -n "${LOG_FILE:-}" ]] && printf "%s\n" "$*" >> "$LOG_FILE"; }

step_header() {
    local msg="=== $1 ==="
    printf "\n${_BOLD}${_B}%s${_R}\n" "$msg" >&2
    _to_log ""; _to_log "$msg"
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
Usage: drift unify <project-root> [options]

Unify + guard eligible planned areas (atomic per area).

Options:
  --area <id>            Only process this specific area
  --model <model>        Override Claude model
  --max-turns <N>        Max agentic turns per Claude call (default: 200)
  --dry-run              Print what would run without executing
  -h, --help             Show this help
USAGE
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_strip_frontmatter() {
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

_log() {
    tee -a "$LOG_FILE" >&2
}

# ---------------------------------------------------------------------------
# Claude call wrapper
# ---------------------------------------------------------------------------

_claude_call() {
    local step_name="$1"
    local system_prompt_file="$2"
    local user_prompt="$3"
    local session_flag="$4"

    local -a cmd=(claude -p)

    if [[ -n "$session_flag" ]]; then
        local flag value
        read -r flag value <<< "$session_flag"
        cmd+=("$flag" "$value")
    fi

    local sys_prompt_tmpfile=""
    if [[ -n "$system_prompt_file" ]]; then
        sys_prompt_tmpfile="$(mktemp)"
        _strip_frontmatter "$system_prompt_file" > "$sys_prompt_tmpfile"
        cmd+=(--append-system-prompt-file "$sys_prompt_tmpfile")
    fi

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
        info "[DRY RUN]   prompt: $(echo "$user_prompt" | head -3)..."
        return 0
    fi

    local exit_code=0

    # stream-json requires --verbose with claude -p
    cmd+=(--verbose)

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
# Build work file for a single area
# ---------------------------------------------------------------------------

_build_work_file() {
    local area_id="$1"
    local work_file="$2"

    python3 -c "
import json, sys

area_id = sys.argv[1]
work_path = sys.argv[2]
manifest_path = sys.argv[3]
plan_path = sys.argv[4]

manifest = json.load(open(manifest_path))
plan = json.load(open(plan_path))

# Find manifest area
area = None
for a in manifest.get('areas', []):
    if a.get('id') == area_id:
        area = a
        break

if not area:
    print(f'ERROR: area {area_id} not found in manifest', file=sys.stderr)
    sys.exit(1)

# Find plan entry
plan_entry = None
for e in plan.get('plan', []):
    if e['area_id'] == area_id:
        plan_entry = e
        break

# Build work file
variants = area.get('variants', [])
canonical_name = plan_entry.get('canonical_variant') if plan_entry else None

# Determine canonical variant
canonical = None
to_migrate = []
if canonical_name:
    for v in variants:
        if v.get('name') == canonical_name:
            canonical = v
        else:
            to_migrate.append(v)
    if not canonical:
        # canonical_variant didn't match any variant name — use first
        canonical = variants[0] if variants else None
        to_migrate = variants[1:] if len(variants) > 1 else []
else:
    # No canonical set — use first variant as canonical, rest migrate
    canonical = variants[0] if variants else None
    to_migrate = variants[1:] if len(variants) > 1 else []

work = {
    'area_id': area_id,
    'area_name': area.get('name', area_id),
    'type': area.get('type', 'structural'),
    'impact': area.get('impact', 'LOW'),
    'description': area.get('description', ''),
    'recommendation': area.get('recommendation', ''),
    'analysis': area.get('analysis', ''),
    'canonical_variant': canonical,
    'variants_to_migrate': to_migrate,
    'all_files': [],
}

# Collect all files
for v in variants:
    for f in v.get('files', []):
        if f not in work['all_files']:
            work['all_files'].append(f)

# Include behavior_matrix if present
if 'behavior_matrix' in area:
    work['behavior_matrix'] = area['behavior_matrix']

json.dump(work, open(work_path, 'w'), indent=2)
print(json.dumps({
    'area_name': work['area_name'],
    'type': work['type'],
    'impact': work['impact'],
    'canonical': canonical.get('name', '?') if canonical else 'NONE',
    'canonical_files': canonical.get('files', []) if canonical else [],
    'migrate_count': len(to_migrate),
    'total_files': len(work['all_files']),
}))
" "$area_id" "$work_file" "$MANIFEST" "$PLAN" 2>&1
}

# ---------------------------------------------------------------------------
# Snapshot guard artifact directories (for detecting new files after guard)
# ---------------------------------------------------------------------------

_snapshot_guard_files() {
    find "$PROJECT_ROOT/eslint-rules" "$PROJECT_ROOT/docs/adr" \
         "$PROJECT_ROOT/docs/patterns" "$PROJECT_ROOT/docs" \
         -maxdepth 1 -type f 2>/dev/null | sort
}

_detect_new_guard_artifacts() {
    local before_file="$1"
    local after
    after="$(_snapshot_guard_files)"
    comm -13 "$before_file" <(echo "$after") | while IFS= read -r f; do
        # Make path relative to project root
        echo "${f#"$PROJECT_ROOT/"}"
    done
}

# ---------------------------------------------------------------------------
# Update plan phase to guard (unify done, guard failed — recovery state)
# ---------------------------------------------------------------------------

_set_phase_guard() {
    local area_id="$1"

    python3 -c "
import json, sys
from datetime import datetime

area_id = sys.argv[1]
plan_path = sys.argv[2]
manifest_path = sys.argv[3]

plan = json.load(open(plan_path))
for entry in plan.get('plan', []):
    if entry['area_id'] == area_id:
        entry['phase'] = 'guard'
        entry['unify_summary'] = f'Unified on {datetime.now().strftime(\"%Y-%m-%d\")}'
        break
plan['updated'] = datetime.now().isoformat()
json.dump(plan, open(plan_path, 'w'), indent=2)

manifest = json.load(open(manifest_path))
for area in manifest.get('areas', []):
    if area.get('id') == area_id:
        area['status'] = 'in_progress'
        break
json.dump(manifest, open(manifest_path, 'w'), indent=2)
print(f'Set {area_id}: phase=guard (unify done, guard pending)')
" "$area_id" "$PLAN" "$MANIFEST" 2>&1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

PROJECT_ROOT=""
MODEL=""
AREA_FILTER=""
MAX_TURNS="200"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --area)       AREA_FILTER="$2"; shift 2 ;;
        --model)      MODEL="$2"; shift 2 ;;
        --max-turns)  MAX_TURNS="$2"; shift 2 ;;
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
MANIFEST="$AUDIT_DIR/drift-manifest.json"
PLAN="$AUDIT_DIR/attack-plan.json"
LOG_FILE="$AUDIT_DIR/unify.log"
WORK_DIR="$AUDIT_DIR/unify-work"

mkdir -p "$AUDIT_DIR" "$WORK_DIR"
: > "$LOG_FILE"

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

command -v claude &>/dev/null || {
    error "claude CLI not found in PATH"
    exit 1
}

[[ -f "$PLAN" ]] || {
    error "No attack-plan.json found. Run: drift plan $PROJECT_ROOT"
    exit 1
}

[[ -f "$MANIFEST" ]] || {
    error "No drift-manifest.json found. Run: drift audit $PROJECT_ROOT"
    exit 1
}

if [[ "${CLAUDECODE:-0}" == "1" ]]; then
    warn "Running inside an existing Claude session."
    warn "Claude -p calls will spawn separate subprocess sessions."
fi

# ---------------------------------------------------------------------------
# Find eligible areas (planned + deps met, OR guard phase for guard-only retry)
# ---------------------------------------------------------------------------

info "Drift unify+guard orchestrator"
info "Project: $PROJECT_ROOT"
info "Drift:   $DRIFT_HOME"
info "Log:     $LOG_FILE"
[[ -n "$MODEL" ]] && info "Model:   $MODEL"
[[ -n "$AREA_FILTER" ]] && info "Area:    $AREA_FILTER"
echo "" >&2

ELIGIBLE="$(python3 -c "
import json, sys

plan = json.load(open(sys.argv[1]))
area_filter = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else ''

entries = plan.get('plan', [])
completed_ids = {e['area_id'] for e in entries if e.get('phase') == 'completed'}

eligible = []
for e in entries:
    phase = e.get('phase', '')
    if phase not in ('planned', 'guard'):
        continue
    if area_filter and e['area_id'] != area_filter:
        continue
    deps = e.get('depends_on', [])
    if all(d in completed_ids for d in deps):
        # Output: area_id<TAB>phase (so we know whether to skip unify)
        eligible.append(f\"{e['area_id']}\t{phase}\")

for line in eligible:
    print(line)
" "$PLAN" "${AREA_FILTER:-}" 2>/dev/null)"

if [[ -z "$ELIGIBLE" ]]; then
    if [[ -n "$AREA_FILTER" ]]; then
        error "Area '$AREA_FILTER' is not eligible (not planned/guard, or has unmet dependencies)."
    else
        warn "No eligible areas found. All planned areas may have unmet dependencies."
    fi
    python3 -c "
import json
plan = json.load(open('$PLAN'))
entries = plan.get('plan', [])
completed = {e['area_id'] for e in entries if e.get('phase') == 'completed'}
for e in entries:
    if e.get('phase') == 'planned':
        deps = e.get('depends_on', [])
        unmet = [d for d in deps if d not in completed]
        if unmet:
            print(f'  {e[\"area_id\"]} blocked by: {\", \".join(unmet)}')
" 2>/dev/null >&2
    exit 1
fi

ELIGIBLE_COUNT=$(echo "$ELIGIBLE" | wc -l)
info "$ELIGIBLE_COUNT eligible area(s)."
echo "" >&2

# ---------------------------------------------------------------------------
# Main loop: unify + guard atomic per area
# ---------------------------------------------------------------------------

COMPLETED=0
FAILED=0

while IFS=$'\t' read -r area_id area_phase; do

    # ------------------------------------------------------------------
    # Phase 1: UNIFY (skip if area is already in guard phase — retry)
    # ------------------------------------------------------------------

    if [[ "$area_phase" == "guard" ]]; then
        info "$area_id: already unified (phase=guard), skipping to guard."
    else
        step_header "UNIFY: $area_id"

        # Build work file
        local_work_file="$WORK_DIR/unify-work-${area_id}.json"
        work_meta="$(_build_work_file "$area_id" "$local_work_file")"

        if [[ $? -ne 0 ]]; then
            error "Failed to build work file for $area_id"
            FAILED=$((FAILED + 1))
            continue
        fi

        # Parse work file metadata
        area_name="$(echo "$work_meta" | python3 -c "import json,sys; print(json.load(sys.stdin).get('area_name','?'))" 2>/dev/null || echo "$area_id")"
        area_type="$(echo "$work_meta" | python3 -c "import json,sys; print(json.load(sys.stdin).get('type','?'))" 2>/dev/null || echo "?")"
        area_impact="$(echo "$work_meta" | python3 -c "import json,sys; print(json.load(sys.stdin).get('impact','?'))" 2>/dev/null || echo "?")"
        canonical_name="$(echo "$work_meta" | python3 -c "import json,sys; print(json.load(sys.stdin).get('canonical','?'))" 2>/dev/null || echo "?")"
        canonical_files="$(echo "$work_meta" | python3 -c "import json,sys; print(' '.join(json.load(sys.stdin).get('canonical_files',[])))" 2>/dev/null || echo "")"
        migrate_count="$(echo "$work_meta" | python3 -c "import json,sys; print(json.load(sys.stdin).get('migrate_count',0))" 2>/dev/null || echo "0")"
        total_files="$(echo "$work_meta" | python3 -c "import json,sys; print(json.load(sys.stdin).get('total_files',0))" 2>/dev/null || echo "0")"

        info "$area_name ($area_type, $area_impact)"
        info "Canonical: $canonical_name"
        info "Files to migrate: $migrate_count (of $total_files total)"

        if [[ "$canonical_name" == "NONE" ]]; then
            warn "No canonical variant set — Claude will pick based on recommendation."
        fi

        # Build unify prompt
        unify_prompt="You are executing a drift unification for: $PROJECT_ROOT

AREA: $area_name ($area_type, $area_impact impact)
AREA ID: $area_id
WORK FILE: $local_work_file

THE AUDIT HAS DETERMINED THIS IS A CONSOLIDATION TARGET.
Your job is to EXECUTE the refactoring, not to re-evaluate whether it's needed.
Do not skip this area. Do not batch-close it. Do not dismiss it as 'different components.'
The audit already verified these are variant implementations of the same concern.

CANONICAL PATTERN: $canonical_name
CANONICAL FILES: $canonical_files

YOUR TASK:
1. Read the work file at $local_work_file — it contains the full area context,
   all variant details, files, code excerpts, and the recommendation
2. Read the canonical implementation files to understand the target pattern
3. Read 1-2 variant files to understand what you're migrating FROM
4. For each file listed in variants_to_migrate:
   a. Read the full file
   b. Refactor it to align with the canonical pattern
   c. Preserve ALL business logic, behavior, error handling, and edge cases
   d. Update imports as needed
   e. Verify the changes compile conceptually (types, interfaces)
5. Append an entry to $PROJECT_ROOT/UNIFICATION_LOG.md:
   ## $(date +%Y-%m-%d) — $area_name
   ### Canonical Pattern
   [which pattern, where it lives]
   ### Files Changed
   - path — what changed
   ### Intentional Exceptions
   - path — why NOT converted (if any)

RULES:
- You MUST make actual file edits. Completing with zero file changes is a failure.
- DO NOT skip files because 'they serve different purposes' or 'they are different components.'
  The audit identified these as drift — variant implementations of the SAME concern.
- For CSS areas: consolidate duplicated styles into the shared-components location.
  Update @import paths in consuming components. Delete the redundant copy.
- For behavioral areas: migrate to the canonical hook/component/pattern.
  Create shared infrastructure first if needed.
- For structural areas: align configuration, naming, or organization to the canonical.
- If a file genuinely CANNOT be migrated (breaks third-party contract, etc.),
  document it as an intentional exception in UNIFICATION_LOG.md with a specific reason.

Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLES:
- Modified source files (the actual refactoring)
- Appended entry in $PROJECT_ROOT/UNIFICATION_LOG.md"

        # Call Claude for unify
        _claude_call "unify: $area_id" \
            "$DRIFT_HOME/skill/drift-unify/SKILL.md" \
            "$unify_prompt" \
            "--session-id $(_gen_uuid)" || {
            error "Unification failed for $area_id"
            FAILED=$((FAILED + 1))
            continue
        }

        # Dry-run: skip gates and updates
        if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
            COMPLETED=$((COMPLETED + 1))
            continue
        fi

        # Gate: check if any files were actually modified
        changed_files="$(cd "$PROJECT_ROOT" && git diff --name-only 2>/dev/null || true)"
        changed_count="$(echo "$changed_files" | grep -c . || echo "0")"

        if [[ "$changed_count" -eq 0 ]]; then
            warn "$area_id: Claude completed but changed zero files. Keeping as planned."
            FAILED=$((FAILED + 1))
            continue
        fi

        info "$area_id: $changed_count file(s) modified by unify."
        success "Unify complete for $area_id."
    fi

    # ------------------------------------------------------------------
    # Phase 2: GUARD (immediate, same area)
    # ------------------------------------------------------------------

    step_header "GUARD: $area_id"

    # Ensure work file exists (might not if we're retrying guard-only)
    local_work_file="$WORK_DIR/unify-work-${area_id}.json"
    if [[ ! -f "$local_work_file" ]]; then
        _build_work_file "$area_id" "$local_work_file" >/dev/null 2>&1
    fi

    # Read area metadata from work file for the guard prompt
    area_name="$(python3 -c "import json; w=json.load(open('$local_work_file')); print(w.get('area_name','?'))" 2>/dev/null || echo "$area_id")"
    area_type="$(python3 -c "import json; w=json.load(open('$local_work_file')); print(w.get('type','?'))" 2>/dev/null || echo "?")"
    canonical_name="$(python3 -c "import json; w=json.load(open('$local_work_file')); print(w.get('canonical_variant',{}).get('name','?') if w.get('canonical_variant') else '?')" 2>/dev/null || echo "?")"

    # Snapshot existing guard artifacts before the call
    guard_before_file="$(mktemp)"
    _snapshot_guard_files > "$guard_before_file"

    # Get the list of files changed by unify (for guard context)
    changed_files="$(cd "$PROJECT_ROOT" && git diff --name-only 2>/dev/null || true)"

    # Build guard prompt — guard agent gets full context of what was just unified
    guard_prompt="You are generating guard artifacts for a just-unified drift area in: $PROJECT_ROOT

AREA: $area_name ($area_type)
AREA ID: $area_id
WORK FILE: $local_work_file (contains canonical pattern, variants, all context)
UNIFICATION LOG: $PROJECT_ROOT/UNIFICATION_LOG.md (details of what was just changed)

FILES MODIFIED BY UNIFICATION:
$changed_files

THE UNIFICATION IS COMPLETE. Your job is to create enforceable guardrails
that prevent this drift from returning. Do not re-evaluate whether the
unification was correct — it's done.

YOUR TASK:

1. Read the work file at $local_work_file for the canonical pattern and variants
2. Read $PROJECT_ROOT/UNIFICATION_LOG.md for the latest entry about this area
3. Read the canonical implementation files to understand what to enforce
4. Read $DRIFT_SEMANTIC/skill/drift-guard/references/eslint-rule-patterns.md
   for ESLint rule writing guidance

GENERATE (in this order):

A. ESLint rules in $PROJECT_ROOT/eslint-rules/:
   - First line of every .js/.ts file: // drift-generated
   - At minimum one of: no-restricted-imports, no-restricted-syntax, or custom rule
   - Ban the OLD patterns/imports that the unification removed
   - Use 'warn' severity
   - Include helpful error messages that say what to use instead

B. ADR in $PROJECT_ROOT/docs/adr/:
   - First line: <!-- drift-generated -->
   - Document what was decided and why
   - Enforcement section MUST reference the specific ESLint rule names from step A

C. Pattern doc in $PROJECT_ROOT/docs/patterns/:
   - First line: <!-- drift-generated -->
   - Practical usage guide showing the canonical pattern

RULES:
- Every generated file MUST have the drift marker on its first line
- Every area MUST have at least one machine-enforceable ESLint rule
- If you cannot express a constraint as a lint rule, explain specifically why
- ADR enforcement section must reference actual rule names, not vague descriptions
- Use 'warn' severity for all new rules

Environment: DRIFT_SEMANTIC=$DRIFT_HOME

DELIVERABLES:
- ESLint rule file(s) in eslint-rules/
- ADR in docs/adr/
- Pattern doc in docs/patterns/"

    # Call Claude for guard
    _claude_call "guard: $area_id" \
        "$DRIFT_HOME/skill/drift-guard/SKILL.md" \
        "$guard_prompt" \
        "--session-id $(_gen_uuid)" || {
        error "Guard failed for $area_id"
        # Unify succeeded but guard failed — set phase to guard for retry
        _set_phase_guard "$area_id" 2>&1 | _log
        warn "$area_id: unify done, guard failed. Phase set to 'guard' for retry."
        FAILED=$((FAILED + 1))
        rm -f "$guard_before_file"
        continue
    }

    # Dry-run: skip finalize
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        rm -f "$guard_before_file"
        COMPLETED=$((COMPLETED + 1))
        continue
    fi

    # Detect new guard artifacts
    new_artifacts="$(_detect_new_guard_artifacts "$guard_before_file")"
    rm -f "$guard_before_file"
    artifact_count="$(echo "$new_artifacts" | grep -c . || echo "0")"

    if [[ "$artifact_count" -eq 0 ]]; then
        warn "$area_id: Guard completed but created zero artifact files."
        warn "Setting phase to guard for retry."
        _set_phase_guard "$area_id" 2>&1 | _log
        FAILED=$((FAILED + 1))
        continue
    fi

    info "$area_id: $artifact_count guard artifact(s) created."

    # Finalize: mark area as completed in plan + manifest
    artifact_args=()
    while IFS= read -r art; do
        [[ -n "$art" ]] && artifact_args+=("$art")
    done <<< "$new_artifacts"

    python3 "$DRIFT_HOME/scripts/plan-update.py" "$PROJECT_ROOT" \
        --finalize "$area_id" --guard-artifacts "${artifact_args[@]}" 2>&1 | _log

    COMPLETED=$((COMPLETED + 1))
    success "$area_id: unify + guard complete. Phase set to completed."

    # Clean up work file
    rm -f "$local_work_file"

done <<< "$ELIGIBLE"

# ---------------------------------------------------------------------------
# Post-loop: verify all guard artifacts
# ---------------------------------------------------------------------------

if [[ "${DRY_RUN:-0}" -eq 0 ]] && [[ "$COMPLETED" -gt 0 ]]; then
    echo "" >&2
    step_header "VERIFY"
    python3 "$DRIFT_HOME/scripts/guard-verify.py" "$PROJECT_ROOT" 2>&1 | _log || true
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo "" >&2
step_header "COMPLETE"
info "Completed: $COMPLETED area(s) (unify + guard)"
[[ "$FAILED" -gt 0 ]] && warn "Failed:    $FAILED area(s)"
info "Log:       $LOG_FILE"
echo "" >&2

python3 -c "
import json
plan = json.load(open('$PLAN'))
entries = plan.get('plan', [])
completed = [e for e in entries if e.get('phase') == 'completed']
guard = [e for e in entries if e.get('phase') == 'guard']
planned = [e for e in entries if e.get('phase') == 'planned']
print(f'Plan: {len(completed)} completed, {len(guard)} guard-pending, {len(planned)} planned')
if guard:
    print('Retry guard with: drift unify $PROJECT_ROOT --area <id>')
    for e in guard:
        print(f'  - {e[\"area_id\"]}')
" 2>/dev/null >&2
