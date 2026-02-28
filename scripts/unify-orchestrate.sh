#!/usr/bin/env bash
# unify-orchestrate.sh — Deterministic orchestrator for the drift unify phase.
#
# Loops through eligible planned areas, builds a per-area work file, calls
# claude -p once per area with an execution-framed prompt, then updates the
# plan and manifest deterministically.
#
# Usage:
#   drift unify <project-root> [options]
#
# Options:
#   --area <id>            Only unify this specific area
#   --model <model>        Override Claude model
#   --max-turns <N>        Max agentic turns per Claude call (default: 200)
#   --verbose              Pass --verbose to claude
#   --dry-run              Print what would run without executing

set -euo pipefail

DRIFT_HOME="${DRIFT_SEMANTIC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# ---------------------------------------------------------------------------
# Output helpers (same as audit-orchestrate.sh)
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

Execute unification for eligible planned areas.

Options:
  --area <id>            Only unify this specific area
  --model <model>        Override Claude model for unify calls
  --max-turns <N>        Max agentic turns per Claude call (default: 200)
  --verbose              Stream verbose output
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
    if [[ "${VERBOSE:-0}" -eq 1 ]]; then
        tee -a "$LOG_FILE"
    else
        cat >> "$LOG_FILE"
    fi
}

# ---------------------------------------------------------------------------
# Claude call wrapper (same pattern as audit-orchestrate.sh)
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
# Update plan + manifest after unification
# ---------------------------------------------------------------------------

_update_after_unify() {
    local area_id="$1"

    python3 -c "
import json, sys
from datetime import datetime

area_id = sys.argv[1]
manifest_path = sys.argv[2]
plan_path = sys.argv[3]

plan = json.load(open(plan_path))
manifest = json.load(open(manifest_path))

for entry in plan.get('plan', []):
    if entry['area_id'] == area_id:
        entry['phase'] = 'guard'
        entry['unify_summary'] = f'Unified by orchestrator on {datetime.now().strftime(\"%Y-%m-%d\")}'
        break

plan['updated'] = datetime.now().isoformat()
json.dump(plan, open(plan_path, 'w'), indent=2)

for area in manifest.get('areas', []):
    if area.get('id') == area_id:
        area['status'] = 'in_progress'
        break

json.dump(manifest, open(manifest_path, 'w'), indent=2)
print(f'Updated {area_id}: phase=guard, status=in_progress')
" "$area_id" "$MANIFEST" "$PLAN" 2>&1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

PROJECT_ROOT=""
MODEL=""
AREA_FILTER=""
MAX_TURNS="200"
VERBOSE=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --area)       AREA_FILTER="$2"; shift 2 ;;
        --model)      MODEL="$2"; shift 2 ;;
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
# Find eligible areas
# ---------------------------------------------------------------------------

info "Drift unify orchestrator"
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
    if e.get('phase') != 'planned':
        continue
    if area_filter and e['area_id'] != area_filter:
        continue
    # Check all dependencies are completed
    deps = e.get('depends_on', [])
    if all(d in completed_ids for d in deps):
        eligible.append(e['area_id'])

# Output one per line, in rank order (already sorted by plan-build)
for aid in eligible:
    print(aid)
" "$PLAN" "${AREA_FILTER:-}" 2>/dev/null)"

if [[ -z "$ELIGIBLE" ]]; then
    if [[ -n "$AREA_FILTER" ]]; then
        error "Area '$AREA_FILTER' is not eligible (not planned, or has unmet dependencies)."
    else
        warn "No eligible areas found. All planned areas may have unmet dependencies."
    fi
    # Show what's blocked
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
info "$ELIGIBLE_COUNT eligible area(s) to unify."
echo "" >&2

# ---------------------------------------------------------------------------
# Main loop: one claude -p call per area
# ---------------------------------------------------------------------------

UNIFIED=0
FAILED=0

while IFS= read -r area_id; do
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

    # Build prompt
    prompt="You are executing a drift unification for: $PROJECT_ROOT

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

    # Call Claude (dry-run is handled inside _claude_call)
    _claude_call "unify: $area_id" \
        "$DRIFT_HOME/skill/drift-unify/SKILL.md" \
        "$prompt" \
        "--session-id $(_gen_uuid)" || {
        error "Unification failed for $area_id"
        FAILED=$((FAILED + 1))
        continue
    }

    # Dry-run: skip gate and plan update
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        UNIFIED=$((UNIFIED + 1))
        continue
    fi

    # Gate: check if any files were actually modified
    changed_count="$(cd "$PROJECT_ROOT" && git diff --name-only 2>/dev/null | wc -l || echo "0")"

    if [[ "$changed_count" -eq 0 ]]; then
        warn "$area_id: Claude completed but changed zero files. Keeping as planned."
        FAILED=$((FAILED + 1))
        continue
    fi

    info "$area_id: $changed_count file(s) modified."

    # Update plan and manifest
    _update_after_unify "$area_id" 2>&1 | _log

    UNIFIED=$((UNIFIED + 1))
    success "$area_id unified. Phase set to guard."

    # Clean up work file
    rm -f "$local_work_file"

done <<< "$ELIGIBLE"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo "" >&2
step_header "UNIFY COMPLETE"
info "Unified:  $UNIFIED area(s)"
[[ "$FAILED" -gt 0 ]] && warn "Failed:   $FAILED area(s)"
info "Log:      $LOG_FILE"
echo "" >&2

# Show what's next
python3 -c "
import json
plan = json.load(open('$PLAN'))
entries = plan.get('plan', [])
guard = [e for e in entries if e.get('phase') == 'guard']
planned = [e for e in entries if e.get('phase') == 'planned']
completed = [e for e in entries if e.get('phase') == 'completed']
print(f'Plan status: {len(completed)} completed, {len(guard)} ready for guard, {len(planned)} still planned')
if guard:
    print('Areas ready for guard:')
    for e in guard:
        print(f'  - {e[\"area_id\"]}')
" 2>/dev/null >&2

info "Next: drift guard $PROJECT_ROOT"
