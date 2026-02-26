#!/usr/bin/env bash
# Run ast-grep structural pattern matching and produce structural-patterns.json.
#
# Usage: bash run-patterns.sh <project-root> <output-dir>
#
# Scans the project with each YAML rule file in rules/, collects matches,
# and outputs a JSON file mapping file paths (or unit IDs) to arrays of
# pattern tags. The scoring pipeline uses this for pairwise similarity.
#
# Output: <output-dir>/structural-patterns.json
# Format: { "relative/path.tsx": ["button-bar", "list-with-map"], ... }
#         or, if code-units.json exists in the output dir, unit IDs as keys.
#
# Special handling:
#   - Rule IDs ending in -jsx/-tsx/-ts are normalized to a single tag
#     (e.g. button-bar-jsx and button-bar-tsx both become "button-bar")
#   - multi-useState rules count per-file; only files with 3+ matches
#     receive the "multi-useState" tag

set -euo pipefail

PROJECT_ROOT="${1:-.}"
OUTPUT_DIR="${2:-.drift-audit/semantic}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULES_DIR="$SCRIPT_DIR/rules"

# Resolve project root to absolute path for relpath calculation
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
mkdir -p "$OUTPUT_DIR"

# Check sg is available
if ! command -v sg &>/dev/null; then
    echo '{}' > "$OUTPUT_DIR/structural-patterns.json"
    echo "  WARNING: ast-grep (sg) not found. Skipping structural patterns." >&2
    exit 0
fi

# Temporary file for collecting all raw JSON match arrays
TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

RULE_COUNT=0

for rule_file in "$RULES_DIR"/*.yml; do
    [ -f "$rule_file" ] || continue
    RULE_COUNT=$((RULE_COUNT + 1))
    basename_rule="$(basename "$rule_file")"
    echo "  Scanning $basename_rule ..." >&2

    # sg scan --json=compact outputs one JSON array per invocation.
    # Append each array on its own line for later merging.
    if output=$(sg scan --rule "$rule_file" --json=compact "$PROJECT_ROOT" 2>/dev/null); then
        if [ -n "$output" ] && [ "$output" != "[]" ]; then
            echo "$output" >> "$TMPFILE"
        fi
    fi
done

echo "  Scanned $RULE_COUNT rule files." >&2

# Process all matches with Python to build the output mapping.
# Pass parameters via environment variables since heredoc stdin doesn't
# support positional arguments.
SG_TMPFILE="$TMPFILE" \
SG_PROJECT_ROOT="$PROJECT_ROOT" \
SG_OUTPUT_PATH="$OUTPUT_DIR/structural-patterns.json" \
SG_CODE_UNITS_PATH="$OUTPUT_DIR/code-units.json" \
python3 -c '
import json
import os
import re
import sys
from collections import Counter, defaultdict

tmpfile = os.environ["SG_TMPFILE"]
project_root = os.environ["SG_PROJECT_ROOT"]
output_path = os.environ["SG_OUTPUT_PATH"]
code_units_path = os.environ["SG_CODE_UNITS_PATH"]

# -- Parse all match arrays from the temp file --------------------------------

all_matches = []
with open(tmpfile, "r") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, list):
                all_matches.extend(parsed)
            elif isinstance(parsed, dict):
                all_matches.append(parsed)
        except json.JSONDecodeError:
            pass

if not all_matches:
    with open(output_path, "w") as out:
        json.dump({}, out, indent=2)
    print("  0 matches across 0 files.", file=sys.stderr)
    sys.exit(0)

# -- Normalize rule IDs to canonical tag names --------------------------------
# Strip -jsx, -tsx, -ts suffix so both language variants produce one tag.

LANG_SUFFIX = re.compile(r"-(jsx|tsx|ts)$")

def normalize_rule_id(rule_id: str) -> str:
    return LANG_SUFFIX.sub("", rule_id)

# -- Build file -> tags mapping -----------------------------------------------

# For most rules: file gets the tag if any match exists.
# For multi-useState: file gets the tag only if 3+ matches in that file.
COUNTING_TAGS = {"multi-useState"}

file_tags: dict[str, set[str]] = defaultdict(set)
counting_hits: dict[str, Counter] = defaultdict(Counter)

for match in all_matches:
    if not isinstance(match, dict):
        continue
    file_path = match.get("file", "")
    rule_id = match.get("ruleId", "")
    if not file_path or not rule_id:
        continue

    tag = normalize_rule_id(rule_id)

    # Make path relative to project root
    if os.path.isabs(file_path):
        try:
            file_path = os.path.relpath(file_path, project_root)
        except ValueError:
            pass

    if tag in COUNTING_TAGS:
        counting_hits[file_path][tag] += 1
    else:
        file_tags[file_path].add(tag)

# Apply counting-based tags (only files with 3+ hits get the tag)
for fpath, counter in counting_hits.items():
    for tag, count in counter.items():
        if count >= 3:
            file_tags[fpath].add(tag)

# -- Expand file paths to unit IDs if code-units.json is available ------------
# The scoring pipeline indexes by unit ID (path::ExportName), not file path.
# If code-units.json exists, expand each file entry to all units in that file.

file_to_units: dict[str, list[str]] = {}

if os.path.exists(code_units_path):
    try:
        with open(code_units_path, "r") as f:
            cu_data = json.load(f)
        units = cu_data if isinstance(cu_data, list) else cu_data.get("units", [])
        for unit in units:
            uid = unit.get("id", "")
            fp = unit.get("filePath", "")
            if uid and fp:
                file_to_units.setdefault(fp, []).append(uid)
    except (json.JSONDecodeError, KeyError):
        pass

result: dict[str, list[str]] = {}

if file_to_units:
    # Expand file paths to unit IDs
    for fpath, tags in file_tags.items():
        unit_ids = file_to_units.get(fpath, [])
        if unit_ids:
            for uid in unit_ids:
                existing = set(result.get(uid, []))
                existing.update(tags)
                result[uid] = sorted(existing)
        else:
            # No units found for this file -- keep file path as key
            result[fpath] = sorted(tags)
else:
    # No code-units.json -- output file paths directly
    for fpath, tags in file_tags.items():
        result[fpath] = sorted(tags)

with open(output_path, "w") as out:
    json.dump(result, out, indent=2, sort_keys=True)

total_tags = sum(len(v) for v in result.values())
print(
    f"  {len(all_matches)} matches -> {len(result)} entries, {total_tags} total tags.",
    file=sys.stderr,
)
'

echo "  Wrote $OUTPUT_DIR/structural-patterns.json" >&2
