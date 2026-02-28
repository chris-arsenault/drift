#!/usr/bin/env python3
"""Validate drift manifest: recompute summary and run quality gate checks.

Usage:
    python3 audit-validate.py <project-root> [--fix-summary] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _drift_common import (
    IMPACT_ORDER,
    count_sentences,
    error,
    has_line_range,
    has_specific_target,
    info,
    load_manifest,
    resolve_project_root,
    save_manifest,
    success,
    warn,
)


# ── Summary recomputation ─────────────────────────────────────────────

def compute_summary(areas: list[dict]) -> dict:
    """Recompute manifest summary from area data."""
    by_impact = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    by_type: dict[str, int] = {}
    all_files: set[str] = set()
    evidence = {"high": 0, "medium": 0, "low": 0}

    for area in areas:
        impact = area.get("impact", "LOW")
        by_impact[impact] = by_impact.get(impact, 0) + 1

        area_type = area.get("type", "structural")
        by_type[area_type] = by_type.get(area_type, 0) + 1

        for variant in area.get("variants", []):
            for f in variant.get("files", []):
                all_files.add(f.split(":")[0])

        eq = area.get("evidence_quality", "low")
        evidence[eq] = evidence.get(eq, 0) + 1

    return {
        "total_drift_areas": len(areas),
        "total_files_affected": len(all_files),
        "high_impact": by_impact["HIGH"],
        "medium_impact": by_impact["MEDIUM"],
        "low_impact": by_impact["LOW"],
        "by_type": by_type,
        "evidence_coverage": evidence,
    }


# ── Quality gate checks ──────────────────────────────────────────────

def validate_area(area: dict) -> list[str]:
    """Run quality gate checks on a single area. Returns list of failure messages."""
    failures: list[str] = []

    # 1. Code excerpts: every variant has at least one with non-empty snippet
    for variant in area.get("variants", []):
        excerpts = variant.get("code_excerpts", [])
        has_snippet = any(e.get("snippet", "").strip() for e in excerpts)
        if not has_snippet:
            failures.append(
                f"code_excerpts: variant \"{variant.get('name', '?')}\" has no code excerpts"
            )

    # 2. Line ranges: every file path matches path:N-N
    for variant in area.get("variants", []):
        for f in variant.get("files", []):
            if not has_line_range(f):
                failures.append(f"line_ranges: \"{f}\" lacks :startLine-endLine")

    # 3. Analysis depth: 3+ sentences
    analysis = area.get("analysis", "")
    sc = count_sentences(analysis)
    if sc < 3:
        failures.append(f"analysis_depth: {sc} sentence(s), need 3+")

    # 4. Recommendation specificity: 50+ chars with path/interface references
    rec = area.get("recommendation", "")
    if not has_specific_target(rec):
        failures.append("recommendation_specific: too generic or too short (need 50+ chars with specific targets)")

    # 5. Semantic purpose: if type=semantic, check for purpose references
    if area.get("type") == "semantic":
        combined = analysis
        for v in area.get("variants", []):
            combined += " " + v.get("implementation_details", "")
        if "purpose" not in combined.lower():
            failures.append("semantic_purpose: no reference to purpose statements")

    return failures


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate drift manifest")
    parser.add_argument("project_root", help="Path to project root")
    parser.add_argument("--fix-summary", action="store_true", help="Write corrected summary to manifest")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project_root)
    manifest = load_manifest(project_root)
    areas = manifest.get("areas", [])

    if not areas:
        warn("No areas in manifest — nothing to validate.")
        sys.exit(0)

    # Recompute summary
    summary = compute_summary(areas)

    if args.fix_summary:
        manifest["summary"] = summary
        save_manifest(project_root, manifest)
        success("Summary updated in manifest.")

    # Run quality gate
    results: list[dict] = []
    pass_count = 0
    fail_count = 0

    for area in areas:
        failures = validate_area(area)
        passed = len(failures) == 0
        results.append({
            "area_id": area.get("id", "?"),
            "area_name": area.get("name", "?"),
            "pass": passed,
            "failures": failures,
        })
        if passed:
            pass_count += 1
        else:
            fail_count += 1

    if args.json:
        print(json.dumps({
            "summary": summary,
            "quality_gate": results,
            "pass_count": pass_count,
            "fail_count": fail_count,
        }, indent=2))
    else:
        print(f"Manifest Validation ({project_root / '.drift-audit' / 'drift-manifest.json'})\n")

        print("Summary (recomputed):")
        print(f"  Total areas:          {summary['total_drift_areas']}")
        print(f"  HIGH / MEDIUM / LOW:  {summary['high_impact']} / {summary['medium_impact']} / {summary['low_impact']}")
        print(f"  Files affected:       {summary['total_files_affected']}")
        bt = summary["by_type"]
        type_str = ", ".join(f"{k}={v}" for k, v in sorted(bt.items()))
        print(f"  By type:              {type_str}")
        ec = summary["evidence_coverage"]
        print(f"  Evidence coverage:    high={ec['high']}, medium={ec['medium']}, low={ec['low']}")

        print(f"\nQuality Gate:")
        for r in results:
            if r["pass"]:
                print(f"  PASS  {r['area_id']}")
            else:
                print(f"  FAIL  {r['area_id']}")
                for f in r["failures"]:
                    print(f"    - {f}")

        print(f"\nResult: {pass_count}/{pass_count + fail_count} areas pass quality gate")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
