"""Stage 1b: CSS extraction and fingerprinting.

Walks the project for .css files, parses them into rules with selectors and
declarations, computes per-rule fingerprints (propertyValueHash, propertySetHash),
and per-file aggregates (propertyFrequency, categoryProfile, custom property sets).

Links CSS files to the JS/TS components that import them via code-units.json.

Output: css-units.json
"""

import hashlib
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

from .io_utils import write_artifact

# ---------------------------------------------------------------------------
# Property categories for the categoryProfile vector
# ---------------------------------------------------------------------------

PROPERTY_CATEGORIES: dict[str, set[str]] = {
    "layout": {
        "display", "flex", "flex-direction", "flex-wrap", "flex-grow",
        "flex-shrink", "flex-basis", "grid-template-columns",
        "grid-template-rows", "align-items", "justify-content",
        "align-self", "place-items", "order", "gap", "row-gap", "column-gap",
    },
    "spacing": {
        "margin", "margin-top", "margin-right", "margin-bottom",
        "margin-left", "padding", "padding-top", "padding-right",
        "padding-bottom", "padding-left",
    },
    "sizing": {
        "width", "height", "min-width", "max-width", "min-height",
        "max-height", "overflow", "overflow-x", "overflow-y", "box-sizing",
    },
    "typography": {
        "font-family", "font-size", "font-weight", "line-height",
        "letter-spacing", "text-align", "text-decoration",
        "text-transform", "color", "white-space", "word-break",
    },
    "visual": {
        "background", "background-color", "background-image",
        "border", "border-radius", "box-shadow", "opacity",
        "outline", "border-color", "border-width", "border-style", "filter",
    },
    "positioning": {
        "position", "top", "right", "bottom", "left",
        "z-index", "transform", "inset",
    },
    "animation": {
        "transition", "animation", "animation-duration",
        "animation-delay", "animation-name",
    },
}

CATEGORY_ORDER = ["layout", "spacing", "sizing", "typography", "visual", "positioning", "animation"]

# Precompute property-to-category lookup
_PROP_TO_CATEGORY: dict[str, str] = {}
for _cat, _props in PROPERTY_CATEGORIES.items():
    for _p in _props:
        _PROP_TO_CATEGORY[_p] = _cat

# Directories and patterns to skip
_SKIP_DIRS = {"node_modules", "dist", ".git", "__pycache__", ".next", "build", "coverage"}

# At-rules to skip entirely (their blocks are not style rules)
_SKIP_AT_RULES = re.compile(r"^@(keyframes|font-face|charset|import|namespace)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# CSS Parser
# ---------------------------------------------------------------------------


def _strip_comments(css: str) -> str:
    """Remove /* ... */ comments."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _parse_declarations(block: str) -> list[dict]:
    """Parse a declaration block into [{name, value}, ...]."""
    declarations: list[dict] = []
    # Split on semicolons, handling values that may contain semicolons in strings
    for decl in block.split(";"):
        decl = decl.strip()
        if not decl or ":" not in decl:
            continue
        colon_idx = decl.index(":")
        prop = decl[:colon_idx].strip().lower()
        value = decl[colon_idx + 1:].strip()
        if prop:
            declarations.append({"name": prop, "value": value})
    return declarations


def _extract_class_names(selector: str) -> list[str]:
    """Extract CSS class names from a selector."""
    return re.findall(r"\.([\w-]+)", selector)


def _extract_prefix(class_name: str) -> str:
    """Extract BEM block prefix from a class name.

    'filter-panel-header' → 'filter-panel'
    'filter-panel__header' → 'filter-panel'
    'filter-panel--active' → 'filter-panel'
    'btn' → 'btn'
    """
    # BEM: split on __ or -- first
    base = re.split(r"__|--", class_name)[0]
    # For hyphenated names like 'filter-panel-header', take up to the last hyphen
    # if there are 3+ segments
    parts = base.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:-1])
    return base


def parse_css(content: str, file_path: str = "") -> list[dict]:
    """Parse CSS content into a list of rule dicts.

    Each rule has: selector, properties, classNames, mediaQuery, lineRange,
    propertyValueHash, propertySetHash.

    Handles @media nesting (1 level). Skips @keyframes, @font-face, etc.
    """
    cleaned = _strip_comments(content)
    rules: list[dict] = []

    # Track line numbers by counting newlines in consumed text
    lines = content.split("\n")
    char_to_line: dict[int, int] = {}
    pos = 0
    for line_num, line in enumerate(lines, 1):
        for _ in range(len(line) + 1):  # +1 for newline
            char_to_line[pos] = line_num
            pos += 1

    # State machine: walk the cleaned CSS
    depth = 0
    current_selector = ""
    current_media = None
    block_start = 0
    selector_start = 0
    i = 0

    while i < len(cleaned):
        ch = cleaned[i]

        if ch == "{":
            if depth == 0:
                selector_text = cleaned[selector_start:i].strip()

                if _SKIP_AT_RULES.match(selector_text):
                    # Skip this entire at-rule block
                    skip_depth = 1
                    i += 1
                    while i < len(cleaned) and skip_depth > 0:
                        if cleaned[i] == "{":
                            skip_depth += 1
                        elif cleaned[i] == "}":
                            skip_depth -= 1
                        i += 1
                    selector_start = i
                    continue

                if selector_text.startswith("@media"):
                    current_media = selector_text
                    depth = 1
                    block_start = i + 1
                else:
                    current_selector = selector_text
                    depth = 1
                    block_start = i + 1
            elif depth == 1 and current_media is not None:
                # Nested selector inside @media
                current_selector = cleaned[block_start:i].strip()
                depth = 2
                block_start = i + 1
            else:
                depth += 1
            i += 1

        elif ch == "}":
            if depth == 1 and current_media is None:
                # End of a top-level rule
                block_content = cleaned[block_start:i]
                declarations = _parse_declarations(block_content)
                if declarations and current_selector:
                    rule = _build_rule(
                        current_selector, declarations, None,
                        selector_start, i, char_to_line,
                    )
                    rules.append(rule)
                current_selector = ""
                depth = 0
                selector_start = i + 1
            elif depth == 2 and current_media is not None:
                # End of a rule inside @media
                block_content = cleaned[block_start:i]
                declarations = _parse_declarations(block_content)
                if declarations and current_selector:
                    rule = _build_rule(
                        current_selector, declarations, current_media,
                        selector_start, i, char_to_line,
                    )
                    rules.append(rule)
                current_selector = ""
                depth = 1
                block_start = i + 1
            elif depth == 1 and current_media is not None:
                # End of @media block
                current_media = None
                depth = 0
                selector_start = i + 1
            else:
                depth = max(0, depth - 1)
            i += 1
        else:
            i += 1

    return rules


def _build_rule(
    selector: str,
    declarations: list[dict],
    media_query: str | None,
    start_char: int,
    end_char: int,
    char_to_line: dict[int, int],
) -> dict:
    """Build a complete rule dict with fingerprints."""
    class_names = _extract_class_names(selector)

    # Property-value hash: exact match detection
    pv_pairs = sorted(f"{d['name']}:{d['value']}" for d in declarations)
    pv_hash = hashlib.sha256("|".join(pv_pairs).encode()).hexdigest()[:16]

    # Property-set hash: value-agnostic match
    ps_names = sorted(d["name"] for d in declarations)
    ps_hash = hashlib.sha256("|".join(ps_names).encode()).hexdigest()[:16]

    start_line = char_to_line.get(start_char, 0)
    end_line = char_to_line.get(end_char, 0)

    return {
        "selector": selector,
        "classNames": class_names,
        "properties": declarations,
        "mediaQuery": media_query,
        "lineRange": [start_line, end_line],
        "propertyValueHash": pv_hash,
        "propertySetHash": ps_hash,
    }


# ---------------------------------------------------------------------------
# File-level aggregation
# ---------------------------------------------------------------------------


def _compute_file_aggregates(rules: list[dict]) -> dict:
    """Compute per-file fingerprints from parsed rules."""
    # Selector prefixes
    all_prefixes: set[str] = set()
    for rule in rules:
        for cn in rule.get("classNames", []):
            all_prefixes.add(_extract_prefix(cn))

    # Custom property declarations and references
    custom_decls: set[str] = set()
    custom_refs: set[str] = set()
    prop_freq: Counter[str] = Counter()

    for rule in rules:
        for decl in rule.get("properties", []):
            name = decl["name"]
            value = decl["value"]
            prop_freq[name] += 1
            if name.startswith("--"):
                custom_decls.add(name)
            for ref in re.findall(r"var\((--[\w-]+)\)", value):
                custom_refs.add(ref)

    # Category profile
    category_counts = {cat: 0 for cat in CATEGORY_ORDER}
    for rule in rules:
        cats_seen: set[str] = set()
        for decl in rule.get("properties", []):
            cat = _PROP_TO_CATEGORY.get(decl["name"])
            if cat:
                cats_seen.add(cat)
        for cat in cats_seen:
            category_counts[cat] += 1
    category_profile = [category_counts[cat] for cat in CATEGORY_ORDER]

    return {
        "selectorPrefixes": sorted(all_prefixes - {""}),
        "customPropertyDeclarations": sorted(custom_decls),
        "customPropertyReferences": sorted(custom_refs),
        "propertyFrequency": dict(prop_freq.most_common()),
        "categoryProfile": category_profile,
    }


# ---------------------------------------------------------------------------
# Component linking
# ---------------------------------------------------------------------------


def _build_import_map(code_units_path: Path) -> dict[str, list[str]]:
    """Build a map from CSS file path → list of importing component unit IDs.

    Reads code-units.json and resolves relative CSS import paths.
    """
    import_map: dict[str, list[str]] = {}

    if not code_units_path.exists():
        return import_map

    import json
    with open(code_units_path, encoding="utf-8") as f:
        data = json.load(f)

    units = data if isinstance(data, list) else data.get("units", [])

    for unit in units:
        uid = unit.get("id", "")
        file_path = unit.get("filePath", "")
        if not file_path:
            continue

        file_dir = os.path.dirname(file_path)

        for imp in unit.get("imports", []):
            source = imp.get("source", "")
            if not source.endswith(".css"):
                continue
            # Resolve relative path
            if source.startswith("./") or source.startswith("../"):
                resolved = os.path.normpath(os.path.join(file_dir, source))
            else:
                resolved = source
            # Normalize path separators
            resolved = resolved.replace("\\", "/")
            import_map.setdefault(resolved, []).append(uid)

    return import_map


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _discover_css_files(project_root: Path) -> list[Path]:
    """Walk project root and find all .css files, skipping excluded dirs."""
    css_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        # Prune excluded directories
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for fname in filenames:
            if fname.endswith(".css"):
                css_files.append(Path(dirpath) / fname)

    return sorted(css_files)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_css(project_root: Path, output_dir: Path) -> None:
    """Extract CSS units from all .css files in the project.

    Writes css-units.json to output_dir.
    """
    t0 = time.time()
    project_root = project_root.resolve()
    css_files = _discover_css_files(project_root)

    if not css_files:
        print("  No CSS files found.", file=sys.stderr)
        write_artifact("css-units.json", {"metadata": {}, "units": []}, output_dir)
        return

    print(f"  Found {len(css_files)} CSS files.", file=sys.stderr)

    # Build import map from code-units.json if available
    code_units_path = output_dir / "code-units.json"
    import_map = _build_import_map(code_units_path)

    units: list[dict] = []
    total_rules = 0

    for css_path in css_files:
        rel_path = str(css_path.relative_to(project_root)).replace("\\", "/")

        try:
            content = css_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"  WARN: cannot read {rel_path}: {e}", file=sys.stderr)
            continue

        rules = parse_css(content, rel_path)
        if not rules:
            continue

        total_rules += len(rules)
        aggregates = _compute_file_aggregates(rules)

        # Strip full property list from rules to keep artifact size reasonable
        # Keep only fingerprints and selector info per rule
        compact_rules = []
        for rule in rules:
            compact_rules.append({
                "selector": rule["selector"],
                "classNames": rule["classNames"],
                "propertyCount": len(rule["properties"]),
                "propertyNames": sorted({d["name"] for d in rule["properties"]}),
                "mediaQuery": rule["mediaQuery"],
                "lineRange": rule["lineRange"],
                "propertyValueHash": rule["propertyValueHash"],
                "propertySetHash": rule["propertySetHash"],
            })

        unit = {
            "id": rel_path,
            "filePath": rel_path,
            "isModule": ".module." in rel_path,
            "importedBy": import_map.get(rel_path, []),
            "ruleCount": len(rules),
            "rules": compact_rules,
            **aggregates,
        }
        units.append(unit)

    elapsed = time.time() - t0

    result = {
        "metadata": {
            "projectRoot": str(project_root),
            "timestamp": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "fileCount": len(units),
            "totalRules": total_rules,
            "extractionTimeMs": int(elapsed * 1000),
        },
        "units": units,
    }

    write_artifact("css-units.json", result, output_dir)
    print(
        f"  Extracted {total_rules} rules from {len(units)} CSS files in {elapsed:.2f}s.",
        file=sys.stderr,
    )


def run(project_root: Path, output_dir: Path) -> None:
    """Entry point for the css-extract stage."""
    extract_css(project_root, output_dir)
