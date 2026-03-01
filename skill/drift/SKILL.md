---
name: drift
description: >
  Orchestrate the full drift pipeline: audit, prioritize, unify, and guard. Wraps all 5 drift
  skills into a coordinated workflow with dependency-aware prioritization and progress tracking.

  Use this skill whenever the user wants to "run the drift pipeline", "audit and fix drift",
  "what should I unify next", "show drift progress", or any full-pipeline drift work. Also
  trigger for "drift plan", "drift unify", "drift guard", or just "drift".

  Phase commands: `/drift` (full pipeline), `/drift audit` (audits only), `/drift plan`
  (prioritize only), `/drift unify` (unify only), `/drift guard` (guard only).
---

# Drift Orchestrator

You are coordinating the full drift pipeline — from discovery through unification to
prevention. You wrap 5 sub-skills into a single coordinated workflow.

## Phase Routing

Parse the user's invocation to determine which phase to run:

| Invocation | Phase | What runs |
|-----------|-------|-----------|
| `/drift` or "run the drift pipeline" | `full` | audit → plan → unify+guard |
| `/drift audit` or "audit for drift" | `audit` | All three audits, then stop |
| `/drift plan` or "show drift plan" / "what should I unify next" | `plan` | Prioritize and present, then stop |
| `/drift unify` or "unify drift" / "fix drift" | `unify` | Unify + guard per area (atomic), then stop |

Each phase runs ONLY that phase and stops. `/drift` (no args) runs all phases sequentially.

---

## Phase: Audit

Run the deterministic audit orchestrator. This script handles all six audit steps
with artifact gates between them — the LLM cannot skip steps or collapse phases.

### Run the Audit

```bash
drift audit "$PROJECT_ROOT"
```

This runs 7 steps automatically:

| Step | What | Type |
|------|------|------|
| 0 | Library pull (if online) | deterministic |
| 1 | Extract + feature extraction (no scoring) | deterministic |
| 2 | Purpose statements | `claude -p` |
| 3 | Structural + behavioral audit | `claude -p` × 8 + merge |
| 4 | Score + cluster (with purpose embeddings) | deterministic |
| 5 | Cluster verification + semantic manifest entries | `claude -p` |
| 6 | Validate manifest | deterministic |

Step 3 splits the audit into 8 focused `claude -p` calls (1 structural + 7 behavioral
domains), each writing to a partial file. A deterministic merge combines them into the
manifest. This prevents context overflow on large codebases — each call only explores
one domain.

Purpose statements are written BEFORE scoring so clusters are semantically informed.
The structural audit runs before scoring since it only needs code units, not clusters.
Scoring and clustering happen once with all signals available.

Each step has artifact gates that prevent the next step from starting until required
files exist. If a step fails, re-run from that step:

```bash
drift audit "$PROJECT_ROOT" --skip-to <step-number>
```

Options:
- `--model <model>` — override the Claude model for analytical steps
- `--skip-to <N>` — resume from step N (verifies prior gates)
- `--max-turns <N>` — max agentic turns per Claude call (default: 200)
- `--verbose` — stream all output to terminal (always logged to `.drift-audit/audit.log`)
- `--dry-run` — print what would run without executing

Wait for the audit to complete before proceeding to the Plan phase.

### Re-Audit Behavior

The orchestrator handles re-audits automatically. If the manifest already exists,
Step 3 runs regression checking before the structural audit begins.

#### ADR Violation Detection

When re-auditing finds drift in an area that was previously `completed`:

1. **Check if the area has an associated ADR:**
   Look in the attack plan's `guard_artifacts` for ADR paths, or search `docs/adr/`
   for ADRs whose Context section references the area's ID or name.

2. **If an ADR exists for a regressed area, this is an ADR violation:**
   - Flag it with `"severity": "violation"` in the finding — this is higher than HIGH
   - Include the ADR reference: "This area was resolved by ADR-NNNN but drift has
     returned, suggesting enforcement mechanisms have failed."
   - ADR violations must appear at the **TOP** of re-audit findings, before any
     normal priority sorting

3. **If no ADR exists for a regressed area:**
   - This is a normal regression, not a violation
   - Recommend adding guard artifacts to prevent future regression

---

## Phase: Plan

Build a prioritized attack plan from the manifest. The plan script handles all mechanical
work: cross-type deduplication (Jaccard on file sets), dependency graph construction,
topological sorting with impact weighting, and merging with any existing plan.

### Step 1: Build Plan

```bash
drift plan "$PROJECT_ROOT"
```

This script:
- Deduplicates cross-type overlap (Jaccard > 0.5 on file sets → merge)
- Builds dependency DAG from file overlap (higher-impact blocks lower)
- Topologically sorts: impact desc → file count desc → variant count asc
- Merges with existing plan (preserves phase progress, flags regressions)
- Writes `.drift-audit/attack-plan.json`
- Outputs the ranked attack order

Use `--merge-threshold 0.6` to adjust dedup sensitivity, `--json` for machine output.

### Step 2: Present to User

Present the script's output to the user. The plan shows:
- **Ready to unify:** areas with all dependencies resolved
- **In progress:** areas mid-unification
- **Completed:** areas already unified + guarded
- **Blocked:** areas waiting on dependencies
- **Regressions:** previously completed areas where drift returned

Ask the user if they want to reorder or skip any areas. If changes are needed, edit
`.drift-audit/attack-plan.json` directly and re-run `drift plan "$PROJECT_ROOT"`.

Phase values: `pending` (in manifest but not yet planned), `planned` (approved for unification),
`unify` (unification in progress), `guard` (unified, guard pending), `completed` (fully done).

---

## Phase: Unify + Guard (atomic)

Run the deterministic orchestrator. For each eligible area, the script runs
unify (refactor to canonical) then immediately guard (generate lint rules + ADRs)
in the same cycle. This is atomic per area — the guard agent has full context of
what was just refactored.

### Run It

```bash
drift unify "$PROJECT_ROOT"
```

This processes all eligible areas (phase=`planned`, dependencies met) in rank order:

| Step | What | Type |
|------|------|------|
| 1 | Read attack plan, filter eligible areas | deterministic |
| 2 | For each area: build work file from manifest | deterministic |
| 3 | For each area: `claude -p` unify+guard (single call) | `claude -p` × N |
| 4 | Gate: verify files modified + guard artifacts created | deterministic |
| 5 | Finalize: plan-update --finalize (→completed) | deterministic |
| 6 | After all areas: `drift verify` | deterministic |

Each `claude -p` call gets a pre-built work file and a combined prompt that
covers both unification and guard artifact generation. The agent refactors first,
then generates lint rules and ADRs in the same session — retaining full context
of what it just changed. The prompt frames the task as execution, not evaluation.

Phase transitions:
- `planned` → `completed` (happy path, unify+guard both succeed)
- `planned` → `guard` (unify succeeded, guard failed — retry with `--area`)

Options:
- `--area <id>` — only process this specific area
- `--model <model>` — override the Claude model
- `--max-turns <N>` — max agentic turns per Claude call (default: 200)
- `--dry-run` — print what would run without executing

Process a single area: `drift unify "$PROJECT_ROOT" --area <area-id>`

Areas in `guard` phase (from a previous failed guard) are automatically retried —
the orchestrator skips the unify step and goes straight to guard.

---

## Phase: Verify

After all areas are processed, the orchestrator runs `drift verify` automatically.
You can also run it standalone:

```bash
drift verify "$PROJECT_ROOT"
```

This runs three checks:

1. **Markers** — every file in sync directories has its drift marker on line 1.
   Files without markers won't sync to the library.
2. **ESLint** — every rule file in `eslint-rules/` is imported AND enabled in the
   ESLint config. Reports INTEGRATED / NOT INTEGRATED per rule.
3. **ADR** — every ADR's `## Enforcement` section references rules and docs that
   actually exist. Reports OK / DEGRADED / BROKEN per ADR.

Use `--check markers`, `--check eslint`, or `--check adr` to run individual checks.
Use `--json` for machine-readable output.

**If any check fails:**
- Missing markers → add the appropriate marker as line 1 (the report tells you which)
- Unintegrated rules → wire them into the ESLint config (see
  `$DRIFT_SEMANTIC/skill/drift-guard/references/eslint-rule-patterns.md`)
- Broken ADR enforcement → fix the missing referenced files

Re-run `drift verify "$PROJECT_ROOT"` after fixes until all checks pass.
Do not proceed to library push with failing checks.

---

## Full Pipeline (`/drift`)

When invoked with no phase argument, run all phases in sequence:

1. **Audit** — `drift audit "$PROJECT_ROOT"` (deterministic orchestrator with gates)
2. **Plan** — `drift plan "$PROJECT_ROOT"` then present to user for approval/reordering
3. **Unify + Guard** — `drift unify "$PROJECT_ROOT"` (atomic per area)
4. **Verify** — runs automatically at end of step 3; fix any failures
5. **Library Push** — if `.drift-audit/config.json` has `"mode": "online"`, run
   `drift library push` to share guard artifacts to the centralized library.
   Check the push output for skipped files — any skipped file is a bug to fix.
6. **Summary** — present full pipeline results

The plan phase is the one human checkpoint in the full pipeline. After the user
approves the plan, unify+guard runs autonomously with a summary at the end.

---

## Progress Tracking

The orchestrator maintains two sources of truth:

1. **`.drift-audit/drift-manifest.json`** — the findings (what drift exists).
   Updated by audit phases. Status field updated by unify/guard phases.

2. **`.drift-audit/attack-plan.json`** — the execution plan (what to do about it).
   Created by plan phase. Updated by unify/guard phases.

When starting any phase, always read both files to understand current state.
When completing any phase, update both files to reflect progress.

---

## Error Handling

- **Audit finds no drift:** Congratulate the user. Skip remaining phases.
- **Plan has no eligible areas:** All remaining areas are blocked by incomplete
  dependencies. Show what's blocking what and ask the user how to proceed.
- **Unify encounters an area too large for one session:** Document progress in
  the plan (keep phase as `unify`), note remaining files in DRIFT_BACKLOG.md,
  continue to next area.
- **Guard can't express a constraint in ESLint:** Document it as a review
  guideline in the checklist instead. Don't force imprecise rules.
- **Re-audit finds regression:** Flag it prominently. Ask user whether to
  re-plan the regressed area or investigate why the guard failed.
