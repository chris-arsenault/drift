---
name: drift-audit-ux
description: >
  Audit a codebase for behavioral and UX-level drift — places where similar user interactions,
  workflows, or UI patterns work inconsistently across the codebase. Complements drift-audit
  (which finds structural drift like dependency versions and file conventions) by reading
  implementation logic to discover how things actually behave.

  Use this skill whenever the user mentions "behavioral drift", "UX consistency", "interaction
  audit", "workflow drift", "pattern consistency", or describes inconsistencies like "some modals
  close on Escape and some don't", "not all workflows have a review step", "some forms validate
  on blur and others on submit". Also trigger when someone says "the UX is inconsistent",
  "interactions don't work the same way everywhere", or "audit the user experience patterns".
---

# Behavioral Drift Audit Skill

You are performing a **behavioral drift audit** — discovering places where similar user-facing
interactions, workflows, or UI patterns are implemented inconsistently across the codebase.

This is fundamentally different from structural drift (dependency versions, file naming, import
patterns). Behavioral drift requires **reading implementation code** to understand what actually
happens when a user interacts with a component. Two modals may both import ModalShell but handle
Escape key differently. Two workflows may both use a queue store but one has a review phase and
the other doesn't.

Your job is discovery and analysis — NOT making architecture decisions. Present findings
and recommendations; the user decides what becomes canonical.

## Prerequisites

The drift tool must be installed (`$DRIFT_SEMANTIC` set). If not, see the drift installation
instructions.

Ask the user for the **project root path** if you're not already in it.

Before scanning, do a quick orientation:

1. Read the project's package.json and directory structure to understand app boundaries
2. Check if `.drift-audit/drift-manifest.json` exists — if so, load it. You'll append
   behavioral findings to it rather than creating a fresh file.
3. Identify the shared component library (if any) — this tells you what "canonical" shared
   patterns already exist. Understanding the shared library is critical because behavioral
   drift often manifests as "shared component exists but some apps use ad-hoc alternatives."
4. Get a count of source files per app to calibrate investigation depth.

## Behavioral Domain Checklist

Work through these domains sequentially. For each domain:

1. **Find candidates** — use glob/grep with the heuristic patterns listed below
2. **Read representative files** — read 2-5 files per app that handle the concern.
   You MUST read actual implementation code, not just imports or exports.
3. **Fill a behavior matrix** — for each file, catalog which behaviors are present/absent
4. **Identify drift** — where do similar components handle the same concern differently?
5. **Rate impact** — how many files affected, how user-visible is the inconsistency?

Skip domains that don't apply to the project (e.g., skip "notification patterns" if the
project has no toast system).

### Domain 1: Modal/Dialog Interaction Consistency

**What to check per modal component:**

| Behavior | How to detect |
|----------|---------------|
| Overlay click closes | Look for onClick/onMouseDown on the overlay div (e.g., `e.target === e.currentTarget`) |
| Escape key closes | Look for `keydown` event listeners checking for `Escape` or `key === 'Escape'` |
| Focus trapping | Look for focus management (tabIndex manipulation, focus-trap libraries, keydown Tab handling) |
| Body scroll lock | Look for `overflow: hidden` on body, or scroll-lock utilities |
| Close button present | Look for explicit close/X button in the modal header or corner |
| Animation on open/close | Look for CSS transitions/animations on the modal or overlay |

**Where to look:**
- Files matching `*Modal*`, `*Dialog*` in name
- Components importing from a shared modal component (e.g., ModalShell)
- Files with `modal-overlay` or `dialog-overlay` in CSS classes
- Files with `position: fixed` overlay patterns

**Output:** A matrix like:

| Modal | Overlay Close | Escape | Focus Trap | Scroll Lock | Close Btn |
|-------|:---:|:---:|:---:|:---:|:---:|
| ImageModal | yes | yes | no | no | yes |
| QuickCheckModal | yes | no | no | no | yes |
| BulkHistorianModal | no | no | no | no | no (footer only) |

### Domain 2: Shared Component Adoption

**What to check:**
- For each component exported by the shared component library: is it used in every app
  where equivalent functionality exists?
- Are there ad-hoc reimplementations? (e.g., a custom dropdown instead of SearchableDropdown,
  a hand-rolled toggle instead of EnableToggle)

**How to investigate:**
1. List all exports from the shared component library
2. For each export, grep across apps for:
   - Direct imports of the shared component (adoption)
   - Ad-hoc implementations of the same pattern (drift)
3. To find ad-hoc implementations, search for structural markers:
   - Custom `<select>` or `<option>` patterns where SearchableDropdown exists
   - Custom checkbox/toggle where EnableToggle exists
   - Custom chip/tag rendering where ChipSelect exists
   - Custom overlay + positioned div where ModalShell exists

**Output:** A matrix like:

| Shared Component | App A | App B | App C |
|-----------------|:-----:|:-----:|:-----:|
| ModalShell | uses shared | ad-hoc | uses shared |
| ChipSelect | uses shared | not needed | ad-hoc |
| SearchableDropdown | uses shared | ad-hoc | not needed |

### Domain 3: Multi-Step Workflow Consistency

**What to check per workflow:**

| Characteristic | How to detect |
|---------------|---------------|
| Pre-work configuration | Modal/panel shown before execution begins (settings, entity selection, tone choice) |
| Progress display | Progress bar, step counter, streaming text, or percentage during execution |
| Post-work review | Modal/panel shown after execution with accept/reject/edit capabilities |
| Parallelizable | Queue-based processing allowing multiple items concurrently vs sequential |
| Minimizable | Can be collapsed to a floating pill/indicator while running |
| Error recovery | Retry per-item, resume from failure point, or abort-only |
| Central configuration | Settings come from a configure menu/panel vs hardcoded/per-invocation |
| Streaming display | Live text/progress streaming during execution |

**Where to look:**
- Files with `Bulk*`, `Batch*`, `Queue*` in name
- Worker communication patterns (postMessage, onmessage)
- Queue/job stores (Zustand stores tracking processing state)
- Modal sequences (confirmation → processing → terminal patterns)
- Any component that manages a multi-step asynchronous operation

### Domain 4: Loading & Error State Patterns

**What to check per view/component:**

| Pattern | How to detect |
|---------|---------------|
| Loading indicator | Spinner, skeleton, "Loading..." text, progress bar |
| Error display | Inline error message, error modal, toast, console.error only |
| Empty state | "No items" message, illustration, call-to-action button |
| Retry mechanism | Retry button, auto-retry, reload suggestion |
| Partial failure | Shows successful items + error for failed ones vs all-or-nothing |

**Where to look:**
- Components with `loading`, `isLoading`, `error`, `isEmpty` in state/props
- Conditional rendering based on data presence
- Error boundary components
- Hooks returning `{ data, loading, error }` patterns

### Domain 5: Form Validation & Input Behavior

**What to check:**

| Pattern | How to detect |
|---------|---------------|
| Validation timing | onChange handler validates, onBlur validates, onSubmit-only validates |
| Error display | Red border, inline message below field, top-of-form summary, none |
| Required indicators | Asterisk (*), "(required)" text, red label, border change, none |
| Debouncing | setTimeout in handlers, useDeferredValue, debounce utility |
| Dirty tracking | Tracks whether form has unsaved changes |

**Where to look:**
- Form components and form containers
- Input event handlers (onChange, onBlur)
- Validation functions and schemas (if any)
- Submit handlers

### Domain 6: Keyboard & Accessibility Patterns

**What to check:**

| Pattern | How to detect |
|---------|---------------|
| Keyboard navigation | keydown handlers on interactive elements (not just global) |
| Focus management | ref.focus() calls, autoFocus props, focus on modal open |
| ARIA attributes | role, aria-label, aria-describedby, aria-expanded on custom controls |
| Screen reader text | sr-only CSS class, aria-label on icon-only buttons |
| Skip navigation | Skip-to-content links |

**Where to look:**
- Custom interactive components (not native `<button>`, `<input>`)
- Modal open/close handlers (should manage focus)
- Tab/panel switching components
- Drag-and-drop implementations

### Domain 7: Notification & Feedback Patterns

**What to check:**

| Pattern | How to detect |
|---------|---------------|
| Success feedback | Toast, inline message, status change, icon flash, none |
| Failure feedback | Error toast, inline error, modal, console only |
| Progress feedback | Progress bar, spinner, streaming text, step counter, none |
| Persistence | Auto-dismiss (timed), permanent, user-dismissable |
| Placement | Top-right toast, bottom bar, inline near trigger, modal |

**Where to look:**
- After async operations complete (fetch, worker messages, API calls)
- Toast/notification components and their invocation patterns
- Status text updates after user actions

## Output Format

### drift-report.md / behavioral-drift-report.md

If drift-report.md exists from a prior structural audit, append a `## Behavioral Findings`
section. If running standalone, create `behavioral-drift-report.md`.

```markdown
## Behavioral Findings

### B1. [Descriptive Area Name]
**Domain:** [which domain from the checklist]
**Variants found:** N | **Impact:** HIGH/MED/LOW | **Files affected:** N

**Behavior Matrix:**

| Component | Behavior A | Behavior B | Behavior C |
|-----------|:---:|:---:|:---:|
| Component1 | yes | no | partial |
| Component2 | no | yes | no |

**Most common pattern:** [which variant most files follow]

**Outliers:** [which files deviate and how]

**Analysis:** [your assessment — is this drift or intentional variation?]
```

### drift-manifest.json

Append entries to the existing `areas` array. Each behavioral entry uses the standard
manifest schema with an additional `"type": "behavioral"` field:

```json
{
  "id": "modal-close-behavior",
  "name": "Modal Close Behavior Consistency",
  "type": "behavioral",
  "description": "...",
  "impact": "MEDIUM",
  "total_files": 8,
  "variants": [
    {
      "name": "overlay-click-plus-escape",
      "description": "Closes on overlay click AND Escape key",
      "file_count": 1,
      "files": ["src/components/ImageModal.jsx"],
      "sample_file": "src/components/ImageModal.jsx"
    }
  ],
  "behavior_matrix": {
    "ImageModal": { "overlay_close": true, "escape_close": true, "focus_trap": false },
    "QuickCheckModal": { "overlay_close": true, "escape_close": false, "focus_trap": false }
  },
  "analysis": "...",
  "recommendation": "...",
  "status": "pending"
}
```

The `behavior_matrix` field is specific to behavioral findings. drift-unify and drift-guard
can ignore it — the standard `variants` and `files` fields are sufficient for those skills.

## Investigation Guidance

### What IS behavioral drift
- Two modals that both show an overlay, but one closes on Escape and the other doesn't
- A shared SearchableDropdown component exists, but some forms use a custom `<select>` instead
- One bulk workflow has a review step after completion, another just auto-closes
- Some forms validate on blur, others only on submit, with no apparent reason for the difference

### What is NOT behavioral drift
- A simple confirmation dialog vs a complex multi-step wizard — these serve different purposes
- An image viewer modal that doesn't close on overlay click because clicking the overlay
  might be part of the interaction — this is intentional, not drift
- A form that validates on change because it's a real-time search filter — the validation
  timing serves a different purpose than a settings form

When in doubt, flag it as "possibly intentional" and ask the user.

### Prioritization
If the project is large, prioritize domains by:
1. **Domains the user specifically mentioned** (they know where the pain is)
2. **Domain 1 (Modals)** and **Domain 3 (Workflows)** — highest user impact
3. **Domain 2 (Shared component adoption)** — easiest to fix
4. Remaining domains based on project relevance

## Re-Audits

If behavioral entries already exist in drift-manifest.json, compare findings to previous
entries and note changes. Update `status` fields for areas that have been addressed.

## Scope Control

If the user wants to focus on specific domains, respect that. A targeted audit of just
modal behavior or just workflow consistency is perfectly valid.
