---
name: drift-audit
description: >
  Scan a codebase to discover and categorize technical drift — places where the same concept is
  implemented in multiple inconsistent ways. Use this skill whenever the user mentions "drift",
  "inconsistency", "unification", "standardization", "cleanup", "audit", "tech debt inventory",
  or wants to understand how many different ways something is done across their codebase. Also
  trigger when someone says things like "my codebase is a mess", "everything is implemented
  differently", "vibe coded project needs cleanup", or "I want to make my code more consistent".
  This is the FIRST skill to run in the drift pipeline — it produces a report and manifest
  consumed by drift-unify and drift-guard.
---

# Drift Audit Skill

You are performing a technical drift audit on a codebase. Your goal is to discover every place
where the same concept is implemented in different ways, categorize the variants, and produce
actionable output.

Your job is discovery and analysis — NOT making architecture decisions. You present findings
and recommendations; the user decides what becomes canonical.

## Prerequisites

The drift tool must be installed (`$DRIFT_SEMANTIC` set). If not, see the drift installation
instructions.

Ask the user for the **project root path** if you're not already in it.

Before scanning, do a quick orientation:

```bash
PROJECT_ROOT="<path>"

# What kind of project is this?
cat "$PROJECT_ROOT/package.json" 2>/dev/null | head -50
ls "$PROJECT_ROOT/tsconfig.json" "$PROJECT_ROOT/.eslintrc*" "$PROJECT_ROOT/eslint.config.*" 2>/dev/null

# What are the major dependencies? This tells you what patterns to look for.
cat "$PROJECT_ROOT/package.json" | python3 -c "
import json, sys
pkg = json.load(sys.stdin)
deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
for name in sorted(deps):
    print(f'  {name}: {deps[name]}')
" 2>/dev/null

# What does the source tree look like?
find "$PROJECT_ROOT/src" -type d -maxdepth 3 2>/dev/null | head -60

# How big is the project?
find "$PROJECT_ROOT/src" -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' \) \
  ! -path '*/node_modules/*' ! -path '*/dist/*' 2>/dev/null | wc -l
```

This orientation step is important. The dependencies, directory structure, and project shape
tell you what drift domains are relevant. A project using Dexie has different drift risks
than one using Prisma. A project with zustand has different state patterns than one using Redux.
Tailor your entire audit to what's actually in the project.

## Audit Workflow

### Phase 1: Automated Discovery

Run the bundled discovery script to get a raw inventory of the codebase:

```bash
AUDIT_DIR="$PROJECT_ROOT/.drift-audit"
mkdir -p "$AUDIT_DIR"

bash "$DRIFT_SEMANTIC/scripts/discover.sh" "$PROJECT_ROOT" > "$AUDIT_DIR/raw-discovery.txt"
```

This script produces a raw inventory — it finds exports, component definitions, hook definitions,
class definitions, common import sources, and structural patterns. It does NOT interpret them.
That's your job in Phase 2.

If the project is large (1000+ files), you may also want targeted scans. Use ripgrep directly
to investigate specific areas the discovery output highlights. For example, if discovery shows
5 different files exporting things with "modal" or "dialog" in the name, dig deeper:

```bash
# Example: the agent decides what to search for based on discovery output
rg --glob='!node_modules' --glob='!dist' -l 'SomePatternYouNoticed' "$PROJECT_ROOT/src"
```

### Phase 2: Intelligent Analysis

This is the most important phase and it relies entirely on YOUR judgment with the codebase
context. Read the discovery output and the project's actual source files to identify drift.

**What is drift?** Two or more files solving the same problem in structurally different ways.
Not every difference is drift — sometimes different approaches serve different needs. Drift is
when the differences are accidental rather than intentional.

For each potential drift area you identify:

1. **Name it descriptively.** Not "modal drift" if the project doesn't use that term —
   use whatever vocabulary the codebase uses.

2. **Read representative files.** Don't just rely on grep matches. Read 2-3 files per
   variant to understand the full pattern — the state management, error handling, types,
   composition approach, and edge case handling.

3. **Count variants and adoption.** How many distinct approaches exist? How many files
   use each? Which is most common?

4. **Assess whether it's actually drift.** Some differences are intentional or contextual.
   A simple confirmation dialog and a complex multi-step wizard may look like "drift" but
   are actually different tools for different jobs. Flag cases where you're unsure and ask
   the user.

5. **Rate impact.** Consider:
   - HIGH: Affects shared infrastructure, data layer, or patterns used in 20+ files.
     Inconsistency here causes bugs, makes onboarding hard, or blocks refactoring.
   - MEDIUM: Affects 5-20 files or touches important workflows. Worth unifying but
     not urgent.
   - LOW: Affects <5 files or is cosmetic. Fix opportunistically.

6. **Note the tradeoffs of each variant.** Don't just say "Variant A is better."
   Explain what each variant does well and poorly. The user has context you don't —
   maybe the "worse" pattern exists because of a constraint you can't see.

### Drift Domain Discovery

Rather than scanning for predetermined categories, discover what domains are relevant
to THIS project by looking at:

- **Repeated exports with similar names** — 3 files exporting `*Button*` components
  suggests button drift; 4 different `*Service` classes suggest service pattern drift.

- **Multiple libraries solving the same problem** — two state management libraries,
  two form libraries, two animation approaches.

- **Parallel directory structures** — `features/auth/` uses one pattern while
  `features/billing/` uses a completely different structure for the same concerns.

- **Inconsistent abstractions** — some features access the data layer directly,
  others go through hooks, others through service classes.

- **Naming inconsistency** — some files use `useSomething` hooks, others use
  `SomethingService` classes, others use bare functions for equivalent operations.

- **Mixed async patterns** — callbacks in some places, promises in others,
  async/await in others, for the same kinds of operations.

Common domains you might find (but discover them, don't assume them):
- UI component variants (dialogs, notifications, form inputs, layout primitives)
- Data access patterns (how the app reads/writes persistent data)
- State management approaches (where state lives and how it flows)
- Async/background processing (retries, queues, polling, workers)
- Error handling strategies
- Type patterns (interfaces vs types, enums vs unions, `any` usage)
- File/module organization conventions

### Phase 3: Generate Output

Produce two files in `$PROJECT_ROOT/.drift-audit/`:

#### 1. `drift-report.md` — Human-readable findings

```markdown
# Drift Audit Report
Generated: [date]
Project: [name from package.json]
Source files scanned: [count]
Drift areas found: [count]

## Executive Summary
[2-3 sentences: overall state of drift, biggest opportunities, quick wins]

## Priority Matrix
| # | Area | Impact | Variants | Files Affected | Notes |
|---|------|--------|----------|----------------|-------|
| 1 | [descriptive name] | HIGH | 4 | 32 | [one-line summary] |
| 2 | ...  | ... | ... | ... | ... |

## Detailed Findings

### 1. [Descriptive Area Name]
**Variants found:** N | **Impact:** HIGH/MED/LOW | **Files affected:** N

**Variant A: "[descriptive name]" (N files)**
- How it works: [brief description of the approach]
- Representative files: [2-3 file paths]
- Strengths: [what this variant does well]
- Weaknesses: [where it falls short]

**Variant B: "[descriptive name]" (N files)**
[...]

**Analysis:** [Your assessment of the tradeoffs. Do NOT dictate a canonical choice —
present the tradeoffs clearly so the user can decide. You can express a recommendation
with reasoning, but frame it as a suggestion.]

[...repeat for each drift area...]

## Quick Wins
[Drift areas where unification is low-effort and high-value]

## Questions for the Team
[Ambiguous cases where you need the user's input to determine if something is
intentional variation or accidental drift]
```

#### 2. `drift-manifest.json` — Machine-readable manifest

This file is consumed by drift-unify and drift-guard. Keep the structure flat and
let the consuming skills interpret it:

```json
{
  "generated": "ISO-8601 timestamp",
  "project_root": "/absolute/path",
  "project_name": "from package.json",
  "summary": {
    "total_drift_areas": 0,
    "total_files_affected": 0,
    "high_impact": 0,
    "medium_impact": 0,
    "low_impact": 0
  },
  "areas": [
    {
      "id": "kebab-case-identifier",
      "name": "Human Readable Name",
      "description": "What this drift area is about",
      "impact": "HIGH|MEDIUM|LOW",
      "total_files": 0,
      "variants": [
        {
          "name": "descriptive-variant-name",
          "description": "How this variant works",
          "file_count": 0,
          "files": ["src/path/to/file.ts"],
          "sample_file": "src/path/to/best-example.ts"
        }
      ],
      "analysis": "Your tradeoff assessment",
      "recommendation": "Your suggested canonical (if you have one) and why",
      "status": "pending"
    }
  ]
}
```

### Phase 4: Present and Discuss

Walk the user through findings conversationally. Focus on:
- The 3-5 highest-impact areas
- Quick wins
- Cases where you're unsure if variation is intentional
- Suggested order of attack (if they want to start unifying)

**Critical: Do not prescribe canonical patterns.** Present the variants and tradeoffs.
The user decides. If they ask for your recommendation, give one with clear reasoning,
but acknowledge you may be missing context about why a particular approach was chosen.

## Re-Audits

If `.drift-audit/drift-manifest.json` already exists, compare findings to the previous
manifest and add a `## Changes Since Last Audit` section showing progress, regressions,
and newly discovered drift areas. Update the manifest's `status` fields for areas that
have been addressed.

## Scope Control

If the user wants to focus on specific areas or directories, respect that. A targeted
audit of just the data layer or just UI components is perfectly valid — don't force a
full audit if they know where the pain is.
