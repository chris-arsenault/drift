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
| `/drift` or "run the drift pipeline" | `full` | audit → plan → unify → guard |
| `/drift audit` or "audit for drift" | `audit` | All three audits, then stop |
| `/drift plan` or "show drift plan" / "what should I unify next" | `plan` | Prioritize and present, then stop |
| `/drift unify` or "unify drift" / "fix drift" | `unify` | Unify planned areas, then stop |
| `/drift guard` or "guard against drift" / "lock patterns" | `guard` | Guard completed areas, then stop |

Each phase runs ONLY that phase and stops. `/drift` (no args) runs all phases sequentially.

---

## Phase: Audit

Run the semantic pipeline first, then all three audit methodologies, compiling a unified manifest.

### Step 0: Library Pull

If `.drift-audit/config.json` exists and `mode` is `"online"`, pull from the library:

```bash
drift library pull
```

Skip if the config file does not exist or mode is `"offline"`.

### Step 1: Run Semantic Pipeline

Run the full pipeline before any manual analysis. This is mandatory — it produces the
structural artifacts (fingerprints, similarity scores, clusters) that inform all three
audit phases.

```bash
PROJECT_ROOT="<path>"
bash "$DRIFT_SEMANTIC/cli.sh" run --project "$PROJECT_ROOT"
```

**Verification:** After the pipeline completes, confirm the artifacts exist:

```bash
ls .drift-audit/semantic/code-units.json .drift-audit/semantic/clusters.json
```

- Both exist → pipeline succeeded, proceed to Step 2.
- Only `code-units.json` exists → downstream stages failed. Run individual stages to
  isolate the failure:

```bash
bash "$DRIFT_SEMANTIC/cli.sh" fingerprint
bash "$DRIFT_SEMANTIC/cli.sh" typesig
bash "$DRIFT_SEMANTIC/cli.sh" callgraph
bash "$DRIFT_SEMANTIC/cli.sh" depcontext
bash "$DRIFT_SEMANTIC/cli.sh" score
bash "$DRIFT_SEMANTIC/cli.sh" cluster
bash "$DRIFT_SEMANTIC/cli.sh" css-extract --project "$PROJECT_ROOT"
bash "$DRIFT_SEMANTIC/cli.sh" css-score
bash "$DRIFT_SEMANTIC/cli.sh" report
```

- Neither file exists → extraction failed. Check `drift version` and diagnose before
  proceeding. Do not skip the pipeline and fall back to manual-only analysis.

### Step 2: Structural Audit

Read `$DRIFT_SEMANTIC/skill/drift-audit/SKILL.md` for the analysis methodology, then:
- Run `bash "$DRIFT_SEMANTIC/scripts/discover.sh" "$PROJECT_ROOT"` for raw inventory
- Perform intelligent analysis (read source files, identify drift areas)
- Use the pipeline's `code-units.json` to cross-reference extracted units
- Write findings to `.drift-audit/drift-manifest.json` and `.drift-audit/drift-report.md`

All structural entries should have `"type": "structural"` (or no type field — structural
is the default since drift-audit predates the type system).

### Step 3: Behavioral Audit

Read `$DRIFT_SEMANTIC/skill/drift-audit-ux/SKILL.md` for the analysis methodology, then:
- Work through the 7 behavioral domain checklist
- Read implementation code to understand actual behavior
- Build behavior matrices per domain
- Append findings to the existing manifest with `"type": "behavioral"`
- Append `## Behavioral Findings` section to drift-report.md

### Step 4: Semantic Audit

The pipeline already ran in Step 1. Read `$DRIFT_SEMANTIC/skill/drift-audit-semantic/SKILL.md`
for the cluster verification and purpose statement methodology (start from Phase 1).

- Verify pipeline clusters by reading source code — include code excerpts in every finding
- **Generate purpose statements** — this is mandatory, not optional. Purpose statements
  are your primary semantic contribution and the pipeline's highest-value input.
- Append findings to manifest with `"type": "semantic"`
- Append `## Semantic Findings` section to drift-report.md
- **Zero semantic findings is a failure state**, not a valid result for any non-trivial
  codebase. If the pipeline produced no clusters, diagnose why and produce manual findings.

### Step 5: Re-run Pipeline with Purpose Statements

After writing purpose statements, re-run the downstream stages to incorporate semantic
embeddings into the similarity scoring:

```bash
bash "$DRIFT_SEMANTIC/cli.sh" ingest-purposes --file .drift-audit/semantic/purpose-statements.json
bash "$DRIFT_SEMANTIC/cli.sh" embed
bash "$DRIFT_SEMANTIC/cli.sh" score
bash "$DRIFT_SEMANTIC/cli.sh" cluster
bash "$DRIFT_SEMANTIC/cli.sh" report
```

Review the updated clusters — purpose-enhanced scoring may surface new semantic findings
that structural signals alone missed.

### Step 6: Update Summary

After all three audits, recompute the manifest's `summary` field:

```json
{
  "total_drift_areas": "<count all areas>",
  "total_files_affected": "<sum unique files across all areas>",
  "high_impact": "<count HIGH areas>",
  "medium_impact": "<count MEDIUM areas>",
  "low_impact": "<count LOW areas>",
  "by_type": {
    "structural": "<count>",
    "behavioral": "<count>",
    "semantic": "<count>"
  },
  "evidence_coverage": {
    "high": "<count areas with code_excerpts + line ranges>",
    "medium": "<count areas with file paths only>",
    "low": "<count areas with observation only>"
  }
}
```

### Step 7: Quality Gate

Before presenting findings to the user, validate that every finding has sufficient evidence.
This prevents shallow, generic output that could apply to any codebase.

**For each area in the manifest, verify:**

1. **Code excerpts exist** — every variant must have at least one `code_excerpts` entry with
   actual source code (not a description of code). If missing, go back and read the files.

2. **File paths include line ranges** — `files` entries should be `path:startLine-endLine`,
   not bare file paths. If missing, re-read the files and add line ranges.

3. **Analysis has substance** — the `analysis` field must be 3+ sentences covering: why the
   drift exists, concrete tradeoffs, and what convergence looks like. If it's 1-2 generic
   sentences, rewrite it.

4. **Recommendations are actionable** — the `recommendation` field must include a concrete
   target (API sketch, component interface, migration path). "Extract a shared component"
   is not actionable. "Extract `ModalShell({ onClose, escapeClose?, scrollLock?, children })`
   into `packages/shared-components/`" is actionable.

5. **Semantic findings have purpose statements** — every semantic finding must reference
   purpose statements that demonstrate functional equivalence. If the semantic pipeline
   produced zero findings, that's a pipeline failure, not an absence of semantic drift.
   Fall back to manual analysis.

**If any finding fails the quality gate**, fix it before presenting to the user. The
quality gate is non-negotiable — it's what distinguishes a useful audit from busywork.

### Re-Audit Behavior

If the manifest already exists, each audit phase compares against existing entries:
- **New findings** are appended
- **Previously found areas** are compared — note if drift has worsened, improved, or been resolved
- **Completed areas** are checked for regression — if drift has returned, flag it prominently

#### ADR Violation Detection

When re-auditing finds drift in an area that was previously `completed`:

1. **Check if the area has an associated ADR:**
   Look in the attack plan's `guard_artifacts` for ADR paths, or search `docs/adr/`
   for ADRs whose Context section references the area's ID or name.

2. **If an ADR exists for a regressed area, this is an ADR violation:**
   - Flag it with `"severity": "violation"` in the finding — this is higher than HIGH
   - Include the ADR reference: "This area was resolved by ADR-NNNN but drift has
     returned, suggesting enforcement mechanisms have failed."
   - Check which enforcement mechanism failed (run the ADR enforcement check from
     the guard phase's Step 6 for this specific ADR)
   - ADR violations must appear at the **TOP** of re-audit findings, before any
     normal priority sorting

3. **If no ADR exists for a regressed area:**
   - This is a normal regression, not a violation
   - Recommend adding guard artifacts to prevent future regression

Present the combined findings when the audit phase is complete.

---

## Phase: Plan

Read `.drift-audit/drift-manifest.json` and produce a prioritized attack order.

### Step 1: Build Dependency Graph

For each area in the manifest:

1. **Explicit dependencies:** Scan the `analysis` and `recommendation` fields for references
   to other areas (by ID or by name). Example: "resolving area #1 would largely resolve this"
   means this area depends on area #1.

2. **File overlap dependencies:** If two areas share files, the higher-impact area should be
   resolved first (changing shared files twice creates churn).

3. **Logical dependencies:** Some dependencies are domain-logical even without textual
   references. Build config depends on dependency versions. TypeScript config depends on
   TypeScript version. Use judgment.

Produce a DAG of area IDs.

### Step 1b: Deduplicate Cross-Type Overlap

The three audit types have genuine overlap. The semantic tool's structural fingerprinting
can surface findings that also appear in structural or behavioral audits (e.g., "these
components all handle loading states differently" may appear as both a behavioral Domain 4
finding and a semantic cluster). Before prioritizing, merge overlapping entries:

1. **Detect overlap by file sets.** For every pair of areas, compute the Jaccard similarity
   of their file sets (union of all variant files). If overlap > 0.5, they likely describe
   the same drift from different angles.

2. **Merge strategy.** When two areas overlap:
   - Keep the **higher-impact** entry as the primary. If equal impact, prefer semantic
     (it has richer metadata: cluster scores, signal breakdowns, consolidation reasoning).
   - Merge the other entry's unique files and variants into the primary.
   - Append the other entry's `analysis` text to the primary's analysis as an
     "Also noted by [type] audit:" addendum.
   - Record the merged area's ID in a `merged_from` array on the primary entry.
   - Delete the secondary entry from the manifest.

3. **Log merges.** When presenting the plan, note which areas were merged so the user
   understands why a behavioral finding disappeared (it was absorbed into a semantic one).

Common overlaps to watch for:
- Behavioral Domain 4 (loading/error states) ↔ semantic clusters with `hasLoadingState`/`hasErrorHandling` behavior signals
- Behavioral Domain 2 (shared component adoption) ↔ semantic clusters where one member is in the shared library
- Structural "naming cluster" findings ↔ semantic clusters of the same units

### Step 2: Topological Sort with Impact Weighting

Within each dependency tier (areas whose dependencies are all resolved or have none):

1. **Impact:** HIGH (3) > MEDIUM (2) > LOW (1)
2. **File count:** More files = higher priority (larger blast radius, more value from early resolution)
3. **Variant count:** Fewer variants = simpler unification = quicker win (tiebreaker)

Sort by impact descending, then file count descending, then variant count ascending.

### Step 3: Merge with Existing Plan

If `.drift-audit/attack-plan.json` exists:
- Preserve phase progress for areas already in the plan
- Add newly discovered areas at appropriate rank positions
- Remove areas that no longer appear in the manifest (resolved naturally)
- Flag areas that regressed from `completed` back to having drift

If no plan exists, create it fresh.

### Step 4: Present to User

Display the ranked attack order:

```
Drift Attack Plan (N areas, M completed, K remaining)

Ready to unify:
  1. [HIGH] Area Name (X files, Y variants)
  2. [HIGH] Another Area (X files, Y variants) — depends on #1

In progress:
  3. [MEDIUM] Area Name — unify phase, 8/15 files done

Completed:
  ✓ Area Name — unified + guarded
  ✓ Another Area — unified + guarded

Blocked:
  5. [MEDIUM] Area Name — blocked by #1 (not yet completed)
```

Ask the user if they want to reorder or skip any areas. Apply their changes.

### Step 5: Save Plan

Write the plan to `.drift-audit/attack-plan.json`:

```json
{
  "created": "ISO-8601",
  "updated": "ISO-8601",
  "plan": [
    {
      "area_id": "kebab-case-id",
      "rank": 1,
      "depends_on": [],
      "phase": "planned",
      "canonical_variant": null,
      "unify_summary": null,
      "guard_artifacts": []
    }
  ]
}
```

Phase values: `pending` (in manifest but not yet planned), `planned` (approved for unification),
`unify` (unification in progress), `guard` (unified, guard pending), `completed` (fully done).

---

## Phase: Unify

Execute unification for all eligible areas in the attack plan.

### Execution Loop

1. Read `.drift-audit/attack-plan.json`
2. Find all areas where `phase` is `planned` AND all `depends_on` areas are `completed`
3. For each eligible area, in rank order:

#### Per-Area Workflow

Read `$DRIFT_SEMANTIC/skill/drift-unify/SKILL.md` and follow its complete methodology for this area:

**a. Determine canonical pattern.**
If `canonical_variant` is set in the plan, use it. Otherwise, read the manifest's
`recommendation` field and present the variant options to the user. The user picks the
canonical. Update the plan entry.

**b. Understand the canonical.**
Read the canonical implementation files thoroughly. Read 1-2 variant files to understand
what you're migrating from.

**c. Prepare shared infrastructure.**
If consolidation requires new shared components/hooks/utilities, create them first.

**d. Refactor files.**
For each non-canonical file in the area's manifest entry:
- Read the full file
- Plan the changes to align with the canonical pattern
- Apply changes, preserving all business logic and behavior
- Verify imports and types

**e. Document.**
- Append to `UNIFICATION_LOG.md` (what changed, what was created, exceptions, breaking changes)
- Update `DRIFT_BACKLOG.md` (what's left if the area isn't fully done)

**f. Update plan.**
Set the area's `phase` to `guard`. Record `unify_summary`. Update `drift-manifest.json`
status to `in_progress` or `completed`.

4. After all eligible areas are processed, present a consolidated summary:
   - Areas unified in this session
   - Files changed per area
   - Shared utilities created
   - Areas now eligible for guard
   - Areas still blocked

---

## Phase: Guard

Generate enforcement artifacts for all unified areas. **Hard enforcement (lint rules) comes
first and is mandatory. Documentation (ADRs, guides) comes second.**

Read `$DRIFT_SEMANTIC/skill/drift-guard/SKILL.md` and follow its two-phase methodology.

### Step 1: Generate Hard Enforcement for ALL Areas

1. Read `.drift-audit/attack-plan.json`
2. Find all areas where `phase` is `guard`
3. For EVERY area, generate lint rules BEFORE writing any documentation:

**Per-area rule generation:**

**a. Read the canonical pattern** (now the only pattern, post-unification).

**b. Read 1-2 old variant files** (from git history or unification log) to understand
what to ban.

**c. Generate ESLint rules** — at minimum one of:
   - `no-restricted-imports` banning non-canonical module paths
   - `no-restricted-syntax` banning old code patterns via AST selectors
   - Custom rule module for complex detection logic
   Use `warn` severity initially.

**d. Generate ast-grep rules** if the project uses ast-grep — for structural patterns
that ESLint selectors can't express.

**e. Apply TypeScript config changes** if tighter types prevent the drift
(e.g., `paths` aliases to enforce canonical import paths).

### Step 2: Wire All Rules and Verify

After generating rules for ALL areas (not one at a time):

1. Update the ESLint config to import and enable every new rule.
2. Run ESLint and report violation counts per rule.
3. If zero violations for a rule, verify it's actually matching (could indicate
   the rule isn't loaded or the selector is wrong).

Present the enforcement scoreboard:
```
Guard Enforcement:
  Areas guarded:        N/N
  ESLint rules:         N (M violations found)
  ast-grep rules:       N
  Config changes:       N
```

If any area has NO enforceable rule, explain specifically why to the user.

### Step 3: Generate Documentation for ALL Areas

Only after all rules are wired and verified:

**a. Write an ADR** for each area — the ADR's Enforcement section MUST reference
the specific rule names created in Step 1.

**b. Write/update pattern guide** — practical usage guide in `docs/patterns/`.

**c. Update review checklist** — drift-specific items covering what lint rules
cannot catch (semantic correctness, architectural intent, edge cases).

### Step 4: Update Plan and Summarize

For each area:
- Set `phase` to `completed`
- Record `guard_artifacts` (list of files created — rules, ADRs, docs)
- Update `drift-manifest.json` status to `completed`

Present consolidated summary:
- ESLint rules created per area with violation counts
- ast-grep rules created
- Config changes made
- ADRs written (with enforcement section referencing rules)
- Pattern docs written
- Recommended rollout (warn → fix → error → CI)

### Step 5: Verify ESLint Integration

After generating all guard artifacts, verify that ESLint rules are actually wired into the
project's config. Rules that aren't referenced have zero effect.

1. **List generated rule files:**
   ```bash
   ls "$PROJECT_ROOT"/eslint-rules/*.{js,cjs,mjs,ts} 2>/dev/null
   ```

2. **Detect and read the ESLint config:**
   ```bash
   ls "$PROJECT_ROOT"/eslint.config.* 2>/dev/null && echo "Flat config"
   ls "$PROJECT_ROOT"/.eslintrc* 2>/dev/null && echo "Legacy config"
   ```
   Read whichever config file exists.

3. **For each generated rule file, check if it's referenced in the config:**
   - **Custom rule modules:** Check that the file is imported AND the rule name appears
     in a `rules: { 'drift-guard/rule-name': '...' }` entry (or equivalent).
   - **`no-restricted-imports` additions:** Check the config contains the expected
     restricted paths/patterns from the generated rules.
   - **`no-restricted-syntax` additions:** Check the config contains the expected
     AST selectors.

4. **Report results:**
   ```
   ESLint Integration Status:
     eslint-rules/no-direct-fetch.js .... INTEGRATED (warn)
     eslint-rules/use-modal-shell.js .... NOT INTEGRATED
     no-restricted-imports additions .... INTEGRATED (2 paths configured)
   ```
   For unintegrated rules, provide the exact code to add to the ESLint config
   (following the patterns in `$DRIFT_SEMANTIC/skill/drift-guard/references/eslint-rule-patterns.md`).

5. **Offer to integrate:**
   If any rules are not wired, ask the user if they want you to update the ESLint config.
   If yes, make the changes and verify:
   ```bash
   npx eslint src/ --format compact 2>/dev/null | grep -c "Warning\|Error" || echo "0 violations"
   ```

### Step 6: Verify ADR Enforcement

Cross-reference ADRs with their declared enforcement mechanisms to detect enforcement decay.

1. **Enumerate ADRs:**
   ```bash
   find "$PROJECT_ROOT/docs/adr" -name "*.md" 2>/dev/null | sort
   ```

2. **For each ADR with status "Accepted":**
   Read the file and parse the `## Enforcement` section. Extract references to:
   - **ESLint rules:** lines containing rule names (e.g., `drift-guard/rule-name`,
     `no-restricted-imports`)
   - **Review checklists:** lines referencing checklist files or PR templates
   - **Pattern documentation:** lines with file paths like `docs/patterns/...`

3. **Verify each referenced mechanism exists and is active:**
   - For ESLint rules: check the rule file exists AND is enabled in the ESLint config.
     If the rule was supposed to be `error` but is `warn` or `off`, flag as degraded.
   - For review checklists: check the referenced file exists and still contains
     the drift-related items mentioned in the ADR.
   - For pattern documentation: check the referenced file exists. Flag if modified
     more recently than the ADR (pattern may have evolved without ADR update).

4. **Report enforcement status per ADR:**
   ```
   ADR Enforcement Status:
     ADR-0001: Modal Pattern ............. OK (3/3 mechanisms active)
     ADR-0002: API Client Layer .......... DEGRADED (eslint rule is warn, should be error)
     ADR-0003: Error Boundary ............ BROKEN (pattern doc missing)
   ```

5. **For broken or degraded enforcement:**
   Provide specific remediation steps for each issue and ask the user if they
   want you to fix them.

---

## Full Pipeline (`/drift`)

When invoked with no phase argument, run all phases in sequence:

1. **Audit** — library pull (if online), run semantic pipeline, discover all drift
2. **Plan** — prioritize and present to user for approval/reordering
3. **Unify** — resolve all planned areas autonomously
4. **Guard** — generate enforcement for all unified areas
5. **Library Push** — if `.drift-audit/config.json` has `"mode": "online"`, run
   `drift library push` to share guard artifacts to the centralized library
6. **Summary** — present full pipeline results

The plan phase is the one human checkpoint in the full pipeline. After the user
approves the plan, unify and guard run autonomously with a summary at the end.

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
