#!/usr/bin/env bash
# discover.sh — Generic codebase inventory for drift detection
#
# This script does NOT look for specific patterns (no "modal", no "BaseComponent").
# It produces a raw structural inventory that the agent interprets in context.
#
# Usage: bash discover.sh <project_root> [extra_excludes]

set -euo pipefail

PROJECT_ROOT="${1:-.}"
EXTRA_EXCLUDES="${2:-}"
SRC_DIR="$PROJECT_ROOT/src"

# Fall back if no src/ directory
[ -d "$SRC_DIR" ] || SRC_DIR="$PROJECT_ROOT"

# Build exclude args
EXCLUDES="--glob=!node_modules --glob=!dist --glob=!build --glob=!.git --glob=!coverage --glob=!__mocks__ --glob=!*.d.ts"
if [ -n "$EXTRA_EXCLUDES" ]; then
  IFS=',' read -ra PARTS <<< "$EXTRA_EXCLUDES"
  for part in "${PARTS[@]}"; do
    EXCLUDES="$EXCLUDES --glob=!$part"
  done
fi

# Prefer ripgrep, fall back to grep
RG="rg"
if ! command -v rg &>/dev/null; then
  echo "WARN: ripgrep not found, falling back to grep (slower, some sections skipped)" >&2
  RG="grep -rn"
fi

echo "=== CODEBASE DISCOVERY ==="
echo "Project root: $PROJECT_ROOT"
echo "Source root: $SRC_DIR"
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# ─── 1. FILE INVENTORY ─────────────────────────────────────────
echo "=== SECTION: FILE_INVENTORY ==="
echo "## File counts by extension"
find "$SRC_DIR" -type f \
  ! -path '*/node_modules/*' ! -path '*/dist/*' ! -path '*/build/*' ! -path '*/.git/*' \
  2>/dev/null | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -30

echo ""
echo "## Total source files (ts/tsx/js/jsx)"
find "$SRC_DIR" -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' \) \
  ! -path '*/node_modules/*' ! -path '*/dist/*' ! -name '*.d.ts' ! -name '*.test.*' ! -name '*.spec.*' \
  2>/dev/null | wc -l

echo ""
echo "## Directory structure (depth 3)"
find "$SRC_DIR" -type d -maxdepth 3 \
  ! -path '*/node_modules/*' ! -path '*/dist/*' ! -path '*/.git/*' \
  2>/dev/null | sort

echo ""
echo "## Largest files by line count (potential god files)"
find "$SRC_DIR" -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' \) \
  ! -path '*/node_modules/*' ! -path '*/dist/*' ! -name '*.d.ts' ! -name '*.test.*' ! -name '*.spec.*' \
  -exec wc -l {} + 2>/dev/null | sort -rn | head -30

echo ""

# ─── 2. EXPORT INVENTORY ───────────────────────────────────────
echo "=== SECTION: EXPORTS ==="
echo "## All named exports (grouped by what they export)"
echo "### Exported functions"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' --glob='*.js' --glob='*.jsx' \
  -e '^export (async )?(function|const) \w+' \
  --no-filename -o "$SRC_DIR" 2>/dev/null | sort | uniq -c | sort -rn | head -50 || true

echo ""
echo "### Exported classes"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' \
  -e '^export (default )?class \w+' \
  "$SRC_DIR" 2>/dev/null | head -50 || true

echo ""
echo "### Exported interfaces and types"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' \
  -e '^export (interface|type) \w+' \
  --no-filename -o "$SRC_DIR" 2>/dev/null | sort | uniq -c | sort -rn | head -80 || true

echo ""
echo "### Default exports"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' --glob='*.js' --glob='*.jsx' \
  -e '^export default' \
  "$SRC_DIR" 2>/dev/null | head -80 || true

echo ""

# ─── 3. COMPONENT DEFINITIONS ──────────────────────────────────
echo "=== SECTION: COMPONENT_DEFINITIONS ==="
echo "## React component definitions (all styles)"
echo "### Arrow function components (const X = ...)"
$RG $EXCLUDES --glob='*.tsx' --glob='*.jsx' \
  -e '^(export )?(const|let) [A-Z]\w+\s*(:\s*\w+)?\s*=' \
  --no-filename "$SRC_DIR" 2>/dev/null | head -100 || true

echo ""
echo "### Function declaration components"
$RG $EXCLUDES --glob='*.tsx' --glob='*.jsx' \
  -e '^(export )?(default )?(async )?function [A-Z]\w+' \
  --no-filename "$SRC_DIR" 2>/dev/null | head -100 || true

echo ""

# ─── 4. HOOK DEFINITIONS ───────────────────────────────────────
echo "=== SECTION: CUSTOM_HOOKS ==="
echo "## All custom hook definitions"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' \
  -e '^export (const|function|default function) use[A-Z]\w+' \
  "$SRC_DIR" 2>/dev/null | sort || true

echo ""

# ─── 5. IMPORT SOURCES ─────────────────────────────────────────
echo "=== SECTION: IMPORT_SOURCES ==="
echo "## Most common import sources (external packages)"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' --glob='*.js' --glob='*.jsx' \
  -o "from '[^'.][^']*'" "$SRC_DIR" 2>/dev/null | \
  grep -v '\./' | grep -v '\.\./' | grep -v '@/' | grep -v '~/' | \
  sort | uniq -c | sort -rn | head -40 || true

echo ""
echo "## Most common internal import paths"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' --glob='*.js' --glob='*.jsx' \
  -o "from '(\./|\.\./|@/|~/)[^']*'" "$SRC_DIR" 2>/dev/null | \
  sort | uniq -c | sort -rn | head -50 || true

echo ""

# ─── 6. NAMING CLUSTERS ────────────────────────────────────────
echo "=== SECTION: NAMING_CLUSTERS ==="
echo "## Files/exports sharing common name fragments"
echo "## (Clusters suggest related functionality that may have drift)"

# Extract all PascalCase identifiers from exports and find repeated roots
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' --glob='*.jsx' \
  -o 'export (const|function|default function|class|interface|type) [A-Z]\w+' \
  --no-filename "$SRC_DIR" 2>/dev/null | \
  sed 's/export \(const\|function\|default function\|class\|interface\|type\) //' | \
  # Split PascalCase into words and take the last meaningful word as a "concept"
  sed 's/\([a-z]\)\([A-Z]\)/\1\n\2/g' | \
  grep -E '^[A-Z]' | \
  sort | uniq -c | sort -rn | head -40 || true

echo ""
echo "## File name patterns (basename clusters)"
find "$SRC_DIR" -type f \( -name '*.ts' -o -name '*.tsx' \) \
  ! -path '*/node_modules/*' ! -path '*/dist/*' ! -name '*.d.ts' ! -name '*.test.*' ! -name '*.spec.*' \
  -exec basename {} \; 2>/dev/null | \
  sed 's/\.[^.]*$//' | \
  # Extract suffix patterns (e.g., "Service", "Hook", "Provider", "Context", "Store")
  grep -oE '[A-Z][a-z]+$' | \
  sort | uniq -c | sort -rn | head -30 || true

echo ""

# ─── 7. PATTERN FREQUENCY ──────────────────────────────────────
echo "=== SECTION: PATTERN_FREQUENCY ==="
echo "## High-frequency function/method calls (what the codebase does most)"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' \
  -o '\b[a-zA-Z]+\(' --no-filename "$SRC_DIR" 2>/dev/null | \
  sort | uniq -c | sort -rn | head -60 || true

echo ""
echo "## Third-party hook usage"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' \
  -o '\buse[A-Z]\w+\(' --no-filename "$SRC_DIR" 2>/dev/null | \
  sort | uniq -c | sort -rn | head -40 || true

echo ""

# ─── 8. STRUCTURAL PATTERNS ────────────────────────────────────
echo "=== SECTION: STRUCTURAL_PATTERNS ==="
echo "## Index/barrel files"
find "$SRC_DIR" -name "index.ts" -o -name "index.tsx" -o -name "index.js" | \
  grep -v node_modules | grep -v dist 2>/dev/null | head -40 || true

echo ""
echo "## Config/constants files"
find "$SRC_DIR" -type f \( -name '*config*' -o -name '*constant*' -o -name '*enum*' \) \
  ! -path '*/node_modules/*' ! -path '*/dist/*' 2>/dev/null | head -30 || true

echo ""
echo "## Test file patterns"
find "$SRC_DIR" -type f \( -name '*.test.*' -o -name '*.spec.*' \) \
  ! -path '*/node_modules/*' 2>/dev/null | wc -l
echo "(test files found)"

echo ""
echo "## Style/CSS file patterns"
find "$SRC_DIR" -type f \( -name '*.css' -o -name '*.scss' -o -name '*.less' -o -name '*.module.*' \) \
  ! -path '*/node_modules/*' ! -path '*/dist/*' 2>/dev/null | \
  sed 's/.*\.//' | sort | uniq -c | sort -rn || true

echo ""

# ─── 9. DUPLICATION INDICATORS ─────────────────────────────────
echo "=== SECTION: DUPLICATION_INDICATORS ==="
echo "## Files with very similar names (potential duplicated concepts)"
find "$SRC_DIR" -type f \( -name '*.ts' -o -name '*.tsx' \) \
  ! -path '*/node_modules/*' ! -path '*/dist/*' ! -name '*.d.ts' ! -name '*.test.*' \
  -exec basename {} \; 2>/dev/null | sort | uniq -d || true

echo ""
echo "## Repeated multi-line patterns (exact duplicates, 3+ lines)"
# Find files with identical content (exact duplicates)
find "$SRC_DIR" -type f \( -name '*.ts' -o -name '*.tsx' \) \
  ! -path '*/node_modules/*' ! -path '*/dist/*' ! -name '*.d.ts' ! -name '*.test.*' \
  -exec md5sum {} + 2>/dev/null | sort | uniq -w32 -d | head -20 || true

echo ""

# ─── 10. ERROR & ASYNC PATTERNS ─────────────────────────────────
echo "=== SECTION: ERROR_AND_ASYNC ==="
echo "## Try/catch density per file (top files by catch count)"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' -c \
  'catch\s*\(' "$SRC_DIR" 2>/dev/null | sort -t: -k2 -rn | head -20 || true

echo ""
echo "## Async pattern styles"
echo "### async/await files"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' -l \
  'async ' "$SRC_DIR" 2>/dev/null | wc -l || echo "0"

echo "### .then() chain files"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' -l \
  '\.then\(' "$SRC_DIR" 2>/dev/null | wc -l || echo "0"

echo "### callback-style files"
$RG $EXCLUDES --glob='*.ts' --glob='*.tsx' -l \
  'callback\|cb\)' "$SRC_DIR" 2>/dev/null | wc -l || echo "0"

echo ""
echo "=== END DISCOVERY ==="
