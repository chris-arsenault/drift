# Type Duplication & Non-Exported Unit Detection

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix two detection gaps: type units excluded from scoring, and non-exported inline hooks/components invisible to the extractor.

**Architecture:** Two layers per fix — discover.sh improvements for the Claude structural audit, and deterministic pipeline changes (extractor + scoring) for automated detection. Type scoring gets a dedicated weight matrix since types have zero behavioral signals. Non-exported extraction targets only hooks and components by naming convention.

**Tech Stack:** TypeScript/ts-morph (extractor), Python (pipeline scoring), Bash (discover.sh)

---

### Task 1: discover.sh — Duplicated Type Names Section

**Files:**
- Modify: `scripts/discover.sh`

**Step 1: Add duplicated types section after the existing "Exported interfaces and types" block**

Find the line `echo "### Default exports"` (line 88). Insert a new section before it, after the exported interfaces/types block:

```bash
echo ""
echo "### Types/interfaces defined in multiple files"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' \
  -n -e '^\s*(export )?(interface|type) [A-Z]\w+' \
  "$SRC_DIR" 2>/dev/null | \
  python3 -c "
import sys, re
from collections import defaultdict
by_name = defaultdict(list)
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    m = re.match(r'(.+?):(\d+):\s*(export\s+)?(interface|type)\s+([A-Z]\w+)', line)
    if m:
        by_name[m.group(5)].append(f'{m.group(1)}:{m.group(2)}')
for name in sorted(by_name, key=lambda n: -len(by_name[n])):
    files = by_name[name]
    unique_files = set(f.rsplit(':',1)[0] for f in files)
    if len(unique_files) > 1:
        print(f'{len(unique_files)} files  {name}')
        for f in files[:5]:
            print(f'    {f}')
        if len(files) > 5:
            print(f'    ... and {len(files)-5} more')
" || true
```

**Step 2: Verify manually**

Run: `bash scripts/discover.sh /home/tsonu/src/drift 2>/dev/null | grep -A 20 "multiple files"`

Expected: section header appears, possibly with 0 matches on drift's own codebase (few duplicate types here).

**Step 3: Commit**

```
feat(discover): surface type names defined in multiple files
```

---

### Task 2: discover.sh — Non-Exported Hooks and Components

**Files:**
- Modify: `scripts/discover.sh`

**Step 1: Add non-exported hooks section after the existing CUSTOM_HOOKS section**

Find `echo ""` after the custom hooks section (after line 117). Insert:

```bash
echo "## Non-exported hook definitions (inline/local)"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' \
  -n -e '^\s+(const|function|let) use[A-Z]\w+' \
  "$SRC_DIR" 2>/dev/null | head -80 || true

echo ""
```

**Step 2: Add non-exported components section after COMPONENT_DEFINITIONS**

Find the end of the component definitions section (after line 108). Insert:

```bash
echo "### Non-exported component definitions (inline/local)"
$RG $EXCLUDES --glob='*.tsx' --glob='*.jsx' \
  -n -e '^\s+(const|function) [A-Z][a-zA-Z0-9]+\s*(:\s*\w+(<[^>]*>)?)?\s*=' \
  "$SRC_DIR" 2>/dev/null | head -80 || true

echo ""
```

**Step 3: Verify manually**

Run: `bash scripts/discover.sh /home/tsonu/src/drift 2>/dev/null | grep -A 5 "Non-exported"`

Expected: both section headers appear.

**Step 4: Commit**

```
feat(discover): surface non-exported hooks and components
```

---

### Task 3: Extractor — Add typeMembers to CodeUnit

**Files:**
- Modify: `extractor/src/types.ts`

**Step 1: Add TypeMemberInfo interface**

After the `ParameterInfo` interface (after line 16), add:

```typescript
/** A member (property) of an interface or type literal */
export interface TypeMemberInfo {
  name: string;
  type: string;
  optional: boolean;
}
```

**Step 2: Add typeMembers field to CodeUnit**

After the `generics` field (line 103), add:

```typescript
  typeMembers: TypeMemberInfo[];
```

**Step 3: Commit**

```
feat(extractor): add typeMembers field to CodeUnit
```

---

### Task 4: Extractor — Extract Type Members

**Files:**
- Modify: `extractor/src/unitExtractor.ts`

**Step 1: Add TypeMemberInfo to imports**

Update the import on line 3:

```typescript
import type { CodeUnit, ParameterInfo, TypeMemberInfo } from "./types.js";
```

**Step 2: Add extractTypeMembers function**

After the `extractGenerics` function (after line 421), add:

```typescript
/**
 * Extract member properties from interface or type alias declarations.
 * Only extracts top-level property signatures (not methods, index signatures, etc.).
 */
function extractTypeMembers(decl: Node): TypeMemberInfo[] {
  const members: TypeMemberInfo[] = [];

  let memberNodes: Node[] = [];

  if (Node.isInterfaceDeclaration(decl)) {
    memberNodes = decl.getMembers();
  } else if (Node.isTypeAliasDeclaration(decl)) {
    const typeNode = decl.getTypeNode();
    if (typeNode && Node.isTypeLiteral(typeNode)) {
      memberNodes = typeNode.getMembers();
    }
  }

  for (const m of memberNodes) {
    if (!Node.isPropertySignature(m)) continue;
    const name = m.getName();
    let type = "unknown";
    try {
      const typeNode = m.getTypeNode();
      if (typeNode) {
        type = typeNode.getText();
      } else {
        type = m.getType().getText(m);
      }
    } catch {
      type = "unknown";
    }
    if (type.length > 500) {
      type = type.slice(0, 497) + "...";
    }
    const optional = m.hasQuestionToken();
    members.push({ name, type, optional });
  }

  return members;
}
```

**Step 3: Call extractTypeMembers in extractSingleUnit**

In `extractSingleUnit`, after the `generics` assignment (line 83), add:

```typescript
  const typeMembers = extractTypeMembers(decl);
```

And in the return object (after `generics,` around line 158), add:

```typescript
    typeMembers,
```

**Step 4: Build and verify**

Run: `cd /home/tsonu/src/drift/extractor && npx tsc --noEmit`

Expected: no type errors.

**Step 5: Commit**

```
feat(extractor): extract interface/type alias members
```

---

### Task 5: Extractor — Non-Exported Hook and Component Extraction

**Files:**
- Modify: `extractor/src/unitExtractor.ts`

**Step 1: Add extractNonExportedUnits function**

After the `extractUnits` function (after line 56), add:

```typescript
const MIN_NON_EXPORTED_LINES = 5;

/**
 * Extract non-exported hooks and components from a source file.
 *
 * Walks all descendants looking for function/variable declarations that
 * match hook (use[A-Z]) or component (PascalCase + JSX) naming patterns.
 * Skips names that already appear in the exported set.
 */
function extractNonExportedUnits(
  sourceFile: SourceFile,
  projectRoot: string,
  exportedNames: Set<string>,
  importInfo: ReturnType<typeof analyzeImports>
): CodeUnit[] {
  const units: CodeUnit[] = [];
  const relativePath = path.relative(projectRoot, sourceFile.getFilePath());
  const seenNames = new Set<string>();

  // Collect candidate declarations: functions and variable declarations with function initializers
  const candidates: { name: string; decl: Node }[] = [];

  for (const fn of sourceFile.getDescendantsOfKind(SyntaxKind.FunctionDeclaration)) {
    const name = fn.getName();
    if (name && !fn.isExported()) {
      candidates.push({ name, decl: fn });
    }
  }

  for (const vd of sourceFile.getDescendantsOfKind(SyntaxKind.VariableDeclaration)) {
    const name = vd.getName();
    const init = vd.getInitializer();
    if (
      name &&
      init &&
      (Node.isArrowFunction(init) || Node.isFunctionExpression(init))
    ) {
      // Check the variable statement is not exported
      const varStmt = vd.getFirstAncestorByKind(SyntaxKind.VariableStatement);
      if (varStmt && varStmt.isExported()) continue;
      candidates.push({ name, decl: vd });
    }
  }

  for (const { name, decl } of candidates) {
    if (exportedNames.has(name)) continue;
    if (seenNames.has(name)) continue;

    // Size filter
    const startLine = decl.getStartLineNumber();
    const endLine = decl.getEndLineNumber();
    if (endLine - startLine + 1 < MIN_NON_EXPORTED_LINES) continue;

    // Must match hook or component naming
    const kind = determineKind(decl, name);
    if (kind !== "hook" && kind !== "component") continue;

    seenNames.add(name);

    try {
      const unit = extractSingleUnit(decl, name, relativePath, sourceFile, projectRoot, importInfo);
      if (unit) units.push(unit);
    } catch (err) {
      process.stderr.write(
        `  WARN: failed to extract non-exported ${name} from ${relativePath}: ${err}\n`
      );
    }
  }

  return units;
}
```

**Step 2: Call extractNonExportedUnits from extractUnits**

In `extractUnits`, after the `for (const [exportName, declarations] ...)` loop ends (line 53), before `return units;`, add:

```typescript
  const exportedNames = new Set(exportedDeclarations.keys());
  const nonExported = extractNonExportedUnits(
    sourceFile,
    projectRoot,
    exportedNames,
    importInfo
  );
  units.push(...nonExported);
```

**Step 3: Build and verify**

Run: `cd /home/tsonu/src/drift/extractor && npx tsc --noEmit`

Expected: no type errors.

**Step 4: Commit**

```
feat(extractor): extract non-exported hooks and components
```

---

### Task 6: Scoring — Write Failing Tests for Type Member Signal

**Files:**
- Modify: `pipeline/tests/test_score.py`

**Step 1: Add test class for sig_type_members**

At the bottom of `test_score.py`, add:

```python
class TestSigTypeMembers:
    def test_identical_fields(self):
        units = {
            "a": {"typeMembers": [
                {"name": "id", "type": "string", "optional": False},
                {"name": "name", "type": "string", "optional": False},
            ]},
            "b": {"typeMembers": [
                {"name": "id", "type": "string", "optional": False},
                {"name": "name", "type": "string", "optional": False},
            ]},
        }
        assert sig_type_members("a", "b", units) == 1.0

    def test_partial_overlap(self):
        units = {
            "a": {"typeMembers": [
                {"name": "id", "type": "string", "optional": False},
                {"name": "name", "type": "string", "optional": False},
                {"name": "email", "type": "string", "optional": True},
            ]},
            "b": {"typeMembers": [
                {"name": "id", "type": "string", "optional": False},
                {"name": "name", "type": "string", "optional": False},
                {"name": "avatar", "type": "string", "optional": True},
            ]},
        }
        # Jaccard: {id, name} intersection = 2, union = {id, name, email, avatar} = 4 → 0.5
        result = sig_type_members("a", "b", units)
        assert abs(result - 0.5) < 1e-6

    def test_disjoint_fields(self):
        units = {
            "a": {"typeMembers": [{"name": "foo", "type": "string", "optional": False}]},
            "b": {"typeMembers": [{"name": "bar", "type": "number", "optional": False}]},
        }
        assert sig_type_members("a", "b", units) == 0.0

    def test_both_empty(self):
        units = {"a": {"typeMembers": []}, "b": {"typeMembers": []}}
        assert sig_type_members("a", "b", units) == 0.0

    def test_missing_unit(self):
        assert sig_type_members("a", "b", {}) == 0.0
```

**Step 2: Add test class for type weight matrix**

```python
class TestTypeWeights:
    def test_type_pair_sums_to_1(self):
        w = _get_weights(False, False, "type", "type")
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_type_pair_has_member_signal(self):
        w = _get_weights(False, False, "type", "type")
        assert "typeMemberOverlap" in w

    def test_type_pair_no_behavioral_signals(self):
        w = _get_weights(False, False, "type", "type")
        for sig in ("jsxStructure", "hookProfile", "calleeSet", "callSequence", "dataAccess", "behavior"):
            assert sig not in w

    def test_type_pair_with_embeddings(self):
        w = _get_weights(True, False, "type", "type")
        assert abs(sum(w.values()) - 1.0) < 1e-6
        assert "semantic" in w
        assert "typeMemberOverlap" in w

    def test_type_not_skipped(self):
        """Type units should be included in candidate list (not in _SKIP_KINDS)."""
        from drift_semantic.score import _SKIP_KINDS
        assert "type" not in _SKIP_KINDS
```

**Step 3: Update imports at top of test_score.py**

Add `sig_type_members` to the import list from `drift_semantic.score`.

**Step 4: Run tests to verify they fail**

Run: `cd /home/tsonu/src/drift && make test 2>&1 | tail -20`

Expected: FAIL — `sig_type_members` does not exist yet, `_get_weights` doesn't handle type pairs yet.

**Step 5: Commit**

```
test: add failing tests for type member scoring
```

---

### Task 7: Scoring — Implement Type Member Signal and Weight Matrix

**Files:**
- Modify: `pipeline/src/drift_semantic/score.py`

**Step 1: Add type weight matrices**

After `WEIGHTS_WITHOUT_EMBEDDINGS` (after line 49), add:

```python
WEIGHTS_TYPE_WITH_EMBEDDINGS = {
    "typeMemberOverlap": 0.40,
    "semantic": 0.10,
    "imports": 0.10,
    "consumerSet": 0.15,
    "coOccurrence": 0.15,
    "neighborhood": 0.10,
}

WEIGHTS_TYPE_WITHOUT_EMBEDDINGS = {
    "typeMemberOverlap": 0.45,
    "imports": 0.12,
    "consumerSet": 0.18,
    "coOccurrence": 0.15,
    "neighborhood": 0.10,
}
```

**Step 2: Remove "type" from _SKIP_KINDS**

Change line 55 from:

```python
_SKIP_KINDS = {"type", "enum", "constant", "interface", "typeAlias"}
```

to:

```python
_SKIP_KINDS = {"enum", "constant"}
```

**Step 3: Add type branch to _get_weights**

At the top of `_get_weights` (line 77), before the existing `base = dict(...)` line, add:

```python
    # Type pairs: dedicated weight matrix (types have no behavioral signals)
    is_type_pair = kind_a == "type" and kind_b == "type"
    if is_type_pair:
        base = dict(WEIGHTS_TYPE_WITH_EMBEDDINGS if has_embeddings else WEIGHTS_TYPE_WITHOUT_EMBEDDINGS)
        if has_structural_patterns:
            total = sum(base.values())
            reduction = 0.05
            for k in base:
                base[k] *= (total - reduction) / total
            base["structuralPattern"] = 0.05
        total = sum(base.values())
        if total > 0:
            for k in base:
                base[k] /= total
        return base
```

**Step 4: Add sig_type_members function**

After `sig_structural_pattern` (after line 301), add:

```python

def sig_type_members(uid_a: str, uid_b: str, units_by_id: dict[str, dict]) -> float:
    """Jaccard similarity on type member name sets."""
    members_a = units_by_id.get(uid_a, {}).get("typeMembers", [])
    members_b = units_by_id.get(uid_b, {}).get("typeMembers", [])
    names_a = {m["name"] for m in members_a if isinstance(m, dict) and "name" in m}
    names_b = {m["name"] for m in members_b if isinstance(m, dict) and "name" in m}
    if not names_a and not names_b:
        return 0.0
    return jaccard_sim(names_a, names_b)
```

**Step 5: Register in _SIGNAL_FUNCS**

Add to `_SIGNAL_FUNCS` dict (after the `structuralPattern` entry):

```python
    "typeMemberOverlap": lambda a, b, art: sig_type_members(a, b, art["units_by_id"]),
```

**Step 6: Run tests**

Run: `cd /home/tsonu/src/drift && make test 2>&1 | tail -20`

Expected: all tests PASS, including the new type scoring tests.

**Step 7: Commit**

```
feat(score): add type member scoring with dedicated weight matrix
```

---

### Task 8: Lint and Final Verification

**Step 1: Run full lint**

Run: `cd /home/tsonu/src/drift && make lint`

Fix any issues.

**Step 2: Run full test suite**

Run: `cd /home/tsonu/src/drift && make test`

All pass.

**Step 3: Build extractor**

Run: `cd /home/tsonu/src/drift/extractor && npx tsc --noEmit`

No errors.

**Step 4: Commit any lint fixes**

---

### Task 9: Update Architecture Docs

**Files:**
- Modify: `docs/architecture.md`

**Step 1: Update the "Similarity Signals" table**

Add a row for `typeMemberOverlap`:

```
| typeMemberOverlap | Jaccard on type member name sets | Type pairs only |
```

**Step 2: Update "Weight Adaptation" section**

Add a bullet:

```
- **Type pairs**: dedicated weight matrix — typeMemberOverlap (0.40-0.45), imports, consumer, co-occurrence, neighborhood. All behavioral signals dropped.
```

**Step 3: Update "Extract" stage description**

Add to the "Extracts per unit" list:

```
Type Members (interfaces/type aliases):
  - typeMembers: property name, resolved type, optionality
```

Add a note about non-exported extraction:

```
Non-exported hooks and components are also extracted if they match
naming conventions (use[A-Z] for hooks, PascalCase+JSX for components)
and are >= 5 lines. These participate in all downstream stages identically
to exported units.
```

**Step 4: Commit**

```
docs: update architecture for type scoring and non-exported extraction
```
