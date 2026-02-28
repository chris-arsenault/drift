#!/usr/bin/env python3
"""Build or update the drift attack plan from the manifest.

Performs cross-type deduplication (Jaccard on file sets), topological sort
with impact weighting, and merges with any existing plan.

Usage:
    python3 plan-build.py <project-root> [--merge-threshold 0.5] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _drift_common import (
    IMPACT_ORDER,
    TYPE_ORDER,
    area_files,
    error,
    info,
    jaccard,
    load_manifest,
    load_plan,
    now_iso,
    resolve_project_root,
    save_manifest,
    save_plan,
    success,
    warn,
)


# ── Cross-type deduplication ──────────────────────────────────────────

def deduplicate(areas: list[dict], threshold: float) -> tuple[list[dict], list[dict]]:
    """Merge areas with file overlap above threshold.

    Returns (surviving_areas, merges_log).
    """
    # Precompute file sets
    file_sets = {a["id"]: area_files(a) for a in areas}
    absorbed: set[str] = set()
    merges: list[dict] = []
    area_map = {a["id"]: a for a in areas}

    # Sort pairs by Jaccard descending so highest overlaps merge first
    pairs: list[tuple[float, str, str]] = []
    ids = [a["id"] for a in areas]
    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1:]:
            j = jaccard(file_sets[a_id], file_sets[b_id])
            if j > threshold:
                pairs.append((j, a_id, b_id))

    pairs.sort(reverse=True)

    for j_score, a_id, b_id in pairs:
        if a_id in absorbed or b_id in absorbed:
            continue

        a = area_map[a_id]
        b = area_map[b_id]

        # Determine primary: higher impact wins; equal → higher type order
        a_rank = (IMPACT_ORDER.get(a.get("impact", "LOW"), 0),
                  TYPE_ORDER.get(a.get("type", "structural"), 0))
        b_rank = (IMPACT_ORDER.get(b.get("impact", "LOW"), 0),
                  TYPE_ORDER.get(b.get("type", "structural"), 0))

        if b_rank > a_rank:
            primary, secondary = b, a
        else:
            primary, secondary = a, b

        # Merge secondary into primary
        primary_files = file_sets[primary["id"]]
        secondary_files = file_sets[secondary["id"]]
        # No need to merge file lists in variants — just add unique analysis
        addendum = f"\n\nAlso noted by {secondary.get('type', '?')} audit: {secondary.get('analysis', '')}"
        primary["analysis"] = primary.get("analysis", "") + addendum
        primary.setdefault("merged_from", []).append(secondary["id"])

        absorbed.add(secondary["id"])
        merges.append({
            "primary": primary["id"],
            "absorbed": secondary["id"],
            "reason": f"Jaccard file overlap: {j_score:.2f}",
        })

    surviving = [a for a in areas if a["id"] not in absorbed]
    return surviving, merges


# ── Dependency graph + topological sort ───────────────────────────────

def build_dependency_graph(areas: list[dict]) -> dict[str, set[str]]:
    """Build a dependency DAG from file overlaps.

    When two areas share files, the higher-impact one should be done first
    (to avoid double-changing shared files). The lower-impact area depends
    on the higher-impact one.
    """
    deps: dict[str, set[str]] = defaultdict(set)
    file_sets = {a["id"]: area_files(a) for a in areas}
    area_map = {a["id"]: a for a in areas}

    ids = [a["id"] for a in areas]
    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1:]:
            overlap = file_sets[a_id] & file_sets[b_id]
            if not overlap:
                continue

            a = area_map[a_id]
            b = area_map[b_id]
            a_rank = IMPACT_ORDER.get(a.get("impact", "LOW"), 0)
            b_rank = IMPACT_ORDER.get(b.get("impact", "LOW"), 0)

            if a_rank >= b_rank:
                deps[b_id].add(a_id)  # b depends on a
            else:
                deps[a_id].add(b_id)  # a depends on b

    return deps


def topological_sort(areas: list[dict], deps: dict[str, set[str]]) -> list[dict]:
    """Sort areas by dependency tiers, then impact/file-count/variant-count within each tier."""
    remaining = {a["id"] for a in areas}
    area_map = {a["id"]: a for a in areas}
    result: list[dict] = []

    while remaining:
        # Find areas with all dependencies satisfied (not in remaining)
        tier = {
            aid for aid in remaining
            if not (deps.get(aid, set()) & remaining)
        }

        if not tier:
            # Cycle — break by picking highest impact
            tier = {max(remaining, key=lambda x: IMPACT_ORDER.get(area_map[x].get("impact", "LOW"), 0))}

        # Sort within tier
        tier_areas = [area_map[aid] for aid in tier]
        tier_areas.sort(key=lambda a: (
            -IMPACT_ORDER.get(a.get("impact", "LOW"), 0),
            -a.get("total_files", 0),
            len(a.get("variants", [])),
        ))

        result.extend(tier_areas)
        remaining -= tier

    return result


# ── Plan merge ────────────────────────────────────────────────────────

def merge_with_existing(
    sorted_areas: list[dict],
    existing_plan: dict | None,
    deps: dict[str, set[str]],
) -> dict:
    """Create a new plan, preserving phase progress from existing plan."""
    now = now_iso()

    if not existing_plan:
        entries = []
        for rank, area in enumerate(sorted_areas, 1):
            entries.append({
                "area_id": area["id"],
                "rank": rank,
                "depends_on": sorted(deps.get(area["id"], set())),
                "phase": "planned",
                "canonical_variant": None,
                "unify_summary": None,
                "guard_artifacts": [],
            })
        return {"created": now, "updated": now, "merges": [], "plan": entries}

    # Existing plan — preserve phase progress
    old_entries = {e["area_id"]: e for e in existing_plan.get("plan", [])}
    new_area_ids = {a["id"] for a in sorted_areas}
    regressions: list[str] = []

    entries = []
    for rank, area in enumerate(sorted_areas, 1):
        aid = area["id"]
        if aid in old_entries:
            entry = old_entries[aid]
            entry["rank"] = rank
            entry["depends_on"] = sorted(deps.get(aid, set()))
            # Check for regression: was completed but area still in manifest
            if entry.get("phase") == "completed":
                regressions.append(aid)
            entries.append(entry)
        else:
            entries.append({
                "area_id": aid,
                "rank": rank,
                "depends_on": sorted(deps.get(aid, set())),
                "phase": "planned",
                "canonical_variant": None,
                "unify_summary": None,
                "guard_artifacts": [],
            })

    plan = {
        "created": existing_plan.get("created", now),
        "updated": now,
        "merges": existing_plan.get("merges", []),
        "plan": entries,
    }

    if regressions:
        plan.setdefault("regressions", []).extend(regressions)

    return plan


# ── Human-readable output ─────────────────────────────────────────────

def format_plan(plan: dict, merges: list[dict], area_map: dict[str, dict]) -> str:
    """Format the plan as human-readable text."""
    entries = plan.get("plan", [])
    completed = [e for e in entries if e.get("phase") == "completed"]
    in_progress = [e for e in entries if e.get("phase") in ("unify", "guard")]
    ready = [e for e in entries if e.get("phase") in ("pending", "planned")
             and not any(d for d in e.get("depends_on", [])
                        if any(x["area_id"] == d and x.get("phase") != "completed"
                              for x in entries))]
    blocked = [e for e in entries if e.get("phase") in ("pending", "planned")
               and e not in ready]
    regressions = plan.get("regressions", [])

    total = len(entries)
    lines = [f"Drift Attack Plan ({total} areas, {len(completed)} completed, {total - len(completed)} remaining)\n"]

    if merges:
        lines.append("Merges applied:")
        for m in merges:
            lines.append(f"  [M] \"{m['primary']}\" absorbed \"{m['absorbed']}\" ({m['reason']})")
        lines.append("")

    if ready:
        lines.append("Ready to unify:")
        for e in ready:
            a = area_map.get(e["area_id"], {})
            dep_str = ""
            if e.get("depends_on"):
                dep_str = f" -- depends on {', '.join(e['depends_on'])}"
            lines.append(
                f"  {e['rank']}. [{a.get('impact', '?')}] {a.get('name', e['area_id'])} "
                f"({a.get('total_files', '?')} files, {len(a.get('variants', []))} variants){dep_str}"
            )
        lines.append("")

    if in_progress:
        lines.append("In progress:")
        for e in in_progress:
            a = area_map.get(e["area_id"], {})
            lines.append(f"  {e['rank']}. [{a.get('impact', '?')}] {a.get('name', e['area_id'])} -- {e['phase']} phase")
        lines.append("")

    if completed:
        lines.append("Completed:")
        for e in completed:
            a = area_map.get(e["area_id"], {})
            lines.append(f"  + {a.get('name', e['area_id'])} -- unified + guarded")
        lines.append("")

    if blocked:
        lines.append("Blocked:")
        for e in blocked:
            a = area_map.get(e["area_id"], {})
            blockers = ", ".join(e.get("depends_on", []))
            lines.append(f"  {e['rank']}. [{a.get('impact', '?')}] {a.get('name', e['area_id'])} -- blocked by {blockers}")
        lines.append("")

    if regressions:
        lines.append("Regressions:")
        for aid in regressions:
            a = area_map.get(aid, {})
            lines.append(f"  ! {a.get('name', aid)} -- was completed, drift returned")
        lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Build drift attack plan")
    parser.add_argument("project_root", help="Path to project root")
    parser.add_argument("--merge-threshold", type=float, default=0.5, help="Jaccard threshold for dedup (default: 0.5)")
    parser.add_argument("--json", action="store_true", help="Output plan as JSON")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project_root)
    manifest = load_manifest(project_root)
    areas = manifest.get("areas", [])

    if not areas:
        warn("No areas in manifest — nothing to plan.")
        sys.exit(0)

    info(f"Building plan from {len(areas)} manifest areas...")

    # 1. Deduplicate
    surviving, merges = deduplicate(areas, args.merge_threshold)
    if merges:
        info(f"Merged {len(merges)} overlapping area(s).")
        # Update manifest with surviving areas
        manifest["areas"] = surviving
        save_manifest(project_root, manifest)

    # 2. Build dependency graph
    deps = build_dependency_graph(surviving)

    # 3. Topological sort
    sorted_areas = topological_sort(surviving, deps)

    # 4. Merge with existing plan
    existing_plan = load_plan(project_root)
    plan = merge_with_existing(sorted_areas, existing_plan, deps)

    # Add any new merges
    plan["merges"] = plan.get("merges", []) + merges

    # 5. Write plan
    save_plan(project_root, plan)
    success(f"Plan written to .drift-audit/attack-plan.json ({len(plan['plan'])} areas)")

    # 6. Output
    area_map = {a["id"]: a for a in surviving}
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(format_plan(plan, merges, area_map))


if __name__ == "__main__":
    main()
