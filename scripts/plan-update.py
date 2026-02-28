#!/usr/bin/env python3
"""Update attack plan state: finalize areas or check for regressions.

Usage:
    python3 plan-update.py <project-root> --finalize <area-id> [--guard-artifacts file1 file2 ...]
    python3 plan-update.py <project-root> --check-regressions [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _drift_common import (
    error,
    info,
    load_manifest,
    load_plan,
    now_iso,
    resolve_project_root,
    save_manifest,
    save_plan,
    success,
    warn,
)


# ── Finalize ──────────────────────────────────────────────────────────

def finalize_area(project_root: Path, area_id: str, guard_artifacts: list[str]) -> None:
    """Mark an area as completed in both plan and manifest."""
    plan = load_plan(project_root)
    if not plan:
        error("No attack-plan.json found.")
        sys.exit(1)

    manifest = load_manifest(project_root)

    # Update plan entry
    entry = None
    for e in plan.get("plan", []):
        if e["area_id"] == area_id:
            entry = e
            break

    if not entry:
        error(f"Area '{area_id}' not found in attack plan.")
        sys.exit(1)

    entry["phase"] = "completed"
    entry["guard_artifacts"] = guard_artifacts
    plan["updated"] = now_iso()
    save_plan(project_root, plan)

    # Update manifest area status
    for area in manifest.get("areas", []):
        if area.get("id") == area_id:
            area["status"] = "completed"
            break

    save_manifest(project_root, manifest)
    success(f"Area '{area_id}' marked as completed with {len(guard_artifacts)} guard artifact(s).")


# ── Regression detection ──────────────────────────────────────────────

def check_regressions(project_root: Path, as_json: bool) -> None:
    """Check completed plan entries for regressions in the manifest."""
    plan = load_plan(project_root)
    if not plan:
        error("No attack-plan.json found.")
        sys.exit(1)

    manifest = load_manifest(project_root)
    manifest_areas = {a["id"]: a for a in manifest.get("areas", [])}

    completed = [e for e in plan.get("plan", []) if e.get("phase") == "completed"]
    if not completed:
        info("No completed areas to check.")
        sys.exit(0)

    regressions: list[dict] = []
    clean: list[str] = []

    for entry in completed:
        aid = entry["area_id"]
        area = manifest_areas.get(aid)

        if not area:
            # Area removed from manifest entirely — no regression
            clean.append(aid)
            continue

        if area.get("status") == "completed":
            clean.append(aid)
            continue

        # Area is in manifest and NOT completed — regression
        reg: dict = {
            "area_id": aid,
            "area_name": area.get("name", aid),
            "manifest_status": area.get("status", "?"),
        }

        # Check for ADR violation
        adr_artifacts = [
            a for a in entry.get("guard_artifacts", [])
            if "adr" in a.lower() or a.startswith("docs/adr/")
        ]
        if adr_artifacts:
            reg["adr_violation"] = True
            reg["adr_files"] = adr_artifacts
        else:
            reg["adr_violation"] = False

        reg["guard_artifacts"] = entry.get("guard_artifacts", [])
        regressions.append(reg)

    if as_json:
        print(json.dumps({
            "regressions": regressions,
            "clean": clean,
            "regression_count": len(regressions),
            "clean_count": len(clean),
        }, indent=2))
    else:
        if regressions:
            print(f"Regressions Detected ({len(regressions)}):\n")
            for r in regressions:
                print(f"  ! {r['area_name']} (status: {r['manifest_status']})")
                if r["adr_violation"]:
                    for adr in r["adr_files"]:
                        print(f"    ADR violation: enforcement failed ({adr})")
                if r["guard_artifacts"]:
                    arts = ", ".join(r["guard_artifacts"])
                    print(f"    Guard artifacts: {arts}")
            print()

        if clean:
            print(f"No regressions: {len(clean)} completed area(s) remain clean.")

    if regressions:
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Update drift attack plan state")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--finalize", metavar="AREA_ID", help="Mark area as completed")
    group.add_argument("--check-regressions", action="store_true", help="Check for regressions")

    parser.add_argument("project_root", help="Path to project root")
    parser.add_argument("--guard-artifacts", nargs="*", default=[], help="Guard artifact paths (with --finalize)")
    parser.add_argument("--json", action="store_true", help="Output as JSON (with --check-regressions)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project_root)

    if args.finalize:
        finalize_area(project_root, args.finalize, args.guard_artifacts)
    else:
        check_regressions(project_root, args.json)


if __name__ == "__main__":
    main()
