#!/usr/bin/env python3
"""Merge partial audit JSON files into a unified manifest and report.

Usage: merge-audit-partials.py <partials-dir> <manifest-path> <report-path>

Reads all *.json files from <partials-dir>, each containing a JSON array of
manifest area objects. Merges them into a single manifest and generates a
human-readable report.
"""
import json
import os
import sys
from datetime import datetime

if len(sys.argv) < 4:
    print("Usage: merge-audit-partials.py <partials-dir> <manifest-path> <report-path>", file=sys.stderr)
    sys.exit(1)

partials_dir = sys.argv[1]
manifest_path = sys.argv[2]
report_path = sys.argv[3]

# Collect all areas from partial files
all_areas = []
sources = {}  # filename -> count

for fname in sorted(os.listdir(partials_dir)):
    if not fname.endswith(".json"):
        continue
    fpath = os.path.join(partials_dir, fname)
    try:
        with open(fpath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  WARN: skipping {fname}: {e}", file=sys.stderr)
        continue

    if not isinstance(data, list):
        print(f"  WARN: skipping {fname}: expected array, got {type(data).__name__}", file=sys.stderr)
        continue

    domain = fname.replace(".json", "")
    count = 0
    for area in data:
        if not isinstance(area, dict):
            continue
        # Ensure required fields
        if "id" not in area:
            area["id"] = f"{domain}-{count}"
        if "type" not in area:
            area["type"] = "structural" if domain == "structural" else "behavioral"
        if "status" not in area:
            area["status"] = "new"
        area["source_domain"] = domain
        all_areas.append(area)
        count += 1

    sources[domain] = count
    print(f"  {domain}: {count} areas")

# Deduplicate by ID
seen_ids = set()
deduped = []
for area in all_areas:
    aid = area["id"]
    if aid in seen_ids:
        print(f"  WARN: duplicate ID {aid}, keeping first occurrence")
        continue
    seen_ids.add(aid)
    deduped.append(area)

# Build manifest
manifest = {
    "version": "1.0",
    "generated": datetime.now().isoformat(),
    "summary": {
        "total_areas": len(deduped),
        "structural": sum(1 for a in deduped if a.get("type") == "structural"),
        "behavioral": sum(1 for a in deduped if a.get("type") == "behavioral"),
        "sources": sources,
    },
    "areas": deduped,
}

# Write manifest
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)
print(f"  Wrote {manifest_path}: {len(deduped)} areas")

# Generate report
lines = [
    "# Drift Audit Report",
    f"Generated: {datetime.now().strftime('%Y-%m-%d')}",
    "",
    "## Summary",
    "",
    f"- **Total drift areas:** {len(deduped)}",
    f"- **Structural:** {manifest['summary']['structural']}",
    f"- **Behavioral:** {manifest['summary']['behavioral']}",
    "",
]

# Group by type then domain
structural = [a for a in deduped if a.get("type") == "structural"]
behavioral = [a for a in deduped if a.get("type") == "behavioral"]

if structural:
    lines.append("## Structural Drift")
    lines.append("")
    for area in structural:
        lines.append(f"### {area.get('name', area['id'])}")
        if area.get("description"):
            lines.append(f"\n{area['description']}")
        if area.get("files"):
            lines.append(f"\n**Files:** {len(area['files'])} affected")
        if area.get("recommendation"):
            lines.append(f"\n**Recommendation:** {area['recommendation']}")
        lines.append("")

if behavioral:
    # Group by domain
    by_domain = {}
    for area in behavioral:
        d = area.get("domain", area.get("source_domain", "other"))
        by_domain.setdefault(d, []).append(area)

    lines.append("## Behavioral Drift")
    lines.append("")
    for domain, areas in by_domain.items():
        lines.append(f"### {domain}")
        lines.append("")
        for area in areas:
            lines.append(f"#### {area.get('name', area['id'])}")
            if area.get("description"):
                lines.append(f"\n{area['description']}")
            if area.get("variants"):
                lines.append(f"\n**Variants:** {len(area['variants'])}")
            if area.get("recommendation"):
                lines.append(f"\n**Recommendation:** {area['recommendation']}")
            lines.append("")

with open(report_path, "w") as f:
    f.write("\n".join(lines))
print(f"  Wrote {report_path}")
