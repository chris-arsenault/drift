"""Stage 6: Report generation.

Reads all pipeline artifacts and generates:
- semantic-drift-report.md: human-readable markdown report
- drift-manifest.json entries with type "semantic"
- dependency-atlas.json: graph structure for visualization
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .io_utils import read_artifact, read_code_units, write_artifact

MAX_TITLE_MEMBERS = 4


def _load_optional(name: str, output_dir: Path) -> dict | list | None:
    """Load an artifact, returning None if it doesn't exist."""
    try:
        return read_artifact(name, output_dir)
    except FileNotFoundError:
        return None


def _format_signals(signals: dict[str, float], top_n: int = 4) -> str:
    """Format top signals as a compact string like 'jsx:0.9, hooks:0.8'."""
    sorted_sigs = sorted(signals.items(), key=lambda x: x[1], reverse=True)
    parts = [f"{name}:{val:.2f}" for name, val in sorted_sigs[:top_n] if val > 0]
    return ", ".join(parts)


def _dominant_signal(signals: dict[str, float]) -> str:
    """Return the name of the highest-weighted signal, or empty string."""
    if not signals:
        return ""
    return max(signals, key=signals.get)


def _shorten_path(file_path: str, max_len: int = 50) -> str:
    """Shorten a file path for display, keeping the tail."""
    if len(file_path) <= max_len:
        return file_path
    return "..." + file_path[-(max_len - 3) :]


def _render_cluster_section(
    cluster: dict,
    units_by_id: dict[str, dict],
    finding: dict | None,
) -> list[str]:
    """Render a single cluster as markdown lines."""
    lines: list[str] = []
    cid = cluster.get("id", "unknown")
    members = cluster.get("members", [])
    signals = cluster.get("signalBreakdown", {})
    avg_sim = cluster.get("avgSimilarity", 0)
    dir_spread = cluster.get("directorySpread", 0)
    dominant = _dominant_signal(signals)

    # Title: use finding role if available, else member names
    if finding and finding.get("role"):
        title = finding["role"]
    else:
        member_names = []
        for uid in members[:MAX_TITLE_MEMBERS]:
            u = units_by_id.get(uid, {})
            member_names.append(u.get("name", uid.split("::")[-1] if "::" in uid else uid))
        if len(members) > MAX_TITLE_MEMBERS:
            member_names.append(f"+{len(members) - MAX_TITLE_MEMBERS} more")
        title = ", ".join(member_names)

    lines.append(f"### {cid}: {title}")
    lines.append(
        f"**Members:** {cluster.get('memberCount', len(members))} | "
        f"**Avg Similarity:** {avg_sim:.2f} | "
        f"**Spread:** {dir_spread} directories"
    )
    if dominant:
        lines.append(f"**Dominant Signal:** {dominant}")
    lines.append("")

    # Member table
    lines.append("| Unit | Kind | File | Key Signals |")
    lines.append("|------|------|------|-------------|")
    for uid in members:
        u = units_by_id.get(uid, {})
        name = u.get("name", uid)
        kind = u.get("kind", "?")
        file_path = _shorten_path(u.get("filePath", "?"))
        key_sigs = _format_signals(signals) if signals else ""
        lines.append(f"| {name} | {kind} | {file_path} | {key_sigs} |")
    lines.append("")

    # Finding details or pending note
    if finding:
        lines.extend(_render_finding_details(finding))
    else:
        lines.append("*Pending semantic verification*")
        lines.append("")

    return lines


_FINDING_FIELDS = [
    ("sharedBehavior", "Shared Behavior"),
    ("meaningfulDifferences", "Meaningful Differences"),
    ("accidentalDifferences", "Accidental Differences"),
    ("featureGaps", "Feature Gaps"),
    ("consolidationComplexity", "Consolidation Complexity"),
    ("consolidationReasoning", "Consolidation Reasoning"),
    ("consumerImpact", "Consumer Impact"),
]


def _render_finding_details(finding: dict) -> list[str]:
    """Render a finding's verdict and detail fields as markdown lines."""
    lines = [
        f"**Verdict:** {finding.get('verdict', '')} (confidence: {finding.get('confidence', '')})"
    ]
    for key, label in _FINDING_FIELDS:
        if finding.get(key):
            lines.append(f"**{label}:** {finding[key]}")
    lines.append("")
    return lines


def _render_verified_clusters(
    clusters: list[dict],
    units_by_id: dict[str, dict],
    findings_by_cluster: dict[str, dict],
) -> list[str]:
    """Group clusters by verdict and render each group."""
    verdict_order = ["DUPLICATE", "OVERLAPPING", "RELATED", "FALSE_POSITIVE"]
    by_verdict: dict[str, list[tuple[dict, dict]]] = {v: [] for v in verdict_order}
    unverified: list[dict] = []

    for cluster in clusters:
        finding = findings_by_cluster.get(cluster.get("id", ""))
        if finding:
            verdict = finding.get("verdict", "RELATED")
            by_verdict.setdefault(verdict, []).append((cluster, finding))
        else:
            unverified.append(cluster)

    lines: list[str] = []
    for verdict in verdict_order:
        group = by_verdict.get(verdict, [])
        if not group:
            continue
        lines.append(f"## {verdict} ({len(group)})")
        lines.append("")
        for cluster, finding in group:
            lines.extend(_render_cluster_section(cluster, units_by_id, finding))

    if unverified:
        lines.append(f"## Unverified ({len(unverified)})")
        lines.append("")
        for cluster in unverified:
            lines.extend(_render_cluster_section(cluster, units_by_id, None))
    return lines


def _generate_markdown(
    clusters: list[dict],
    units_by_id: dict[str, dict],
    findings_by_cluster: dict[str, dict],
    unit_count: int,
) -> str:
    """Generate the semantic-drift-report.md content."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append("# Semantic Drift Report")
    lines.append(f"Generated: {now}")
    lines.append(f"Units analyzed: {unit_count}")
    lines.append(f"Clusters found: {len(clusters)}")

    verified_count = sum(1 for c in clusters if c.get("id") in findings_by_cluster)
    if findings_by_cluster:
        lines.append(f"Verified clusters: {verified_count}")
    lines.append("")

    if findings_by_cluster:
        lines.extend(_render_verified_clusters(clusters, units_by_id, findings_by_cluster))
    else:
        lines.append("## Preliminary Clusters")
        lines.append("")
        lines.append(
            "> These clusters are based on structural and behavioral similarity signals. "
            "Semantic verification by Claude is pending."
        )
        lines.append("")
        for cluster in clusters:
            lines.extend(_render_cluster_section(cluster, units_by_id, None))

    return "\n".join(lines)


def _generate_dependency_atlas(
    clusters: list[dict],
    scored_pairs: list[dict],
    units_by_id: dict[str, dict],
) -> dict:
    """Generate dependency-atlas.json: nodes = units in clusters, edges = scores."""
    cluster_units: set[str] = set()
    unit_to_cluster: dict[str, str] = {}
    for cluster in clusters:
        cid = cluster.get("id", "")
        for uid in cluster.get("members", []):
            cluster_units.add(uid)
            unit_to_cluster[uid] = cid

    nodes = []
    for uid in sorted(cluster_units):
        u = units_by_id.get(uid, {})
        nodes.append(
            {
                "id": uid,
                "name": u.get("name", uid),
                "kind": u.get("kind", ""),
                "filePath": u.get("filePath", ""),
                "cluster": unit_to_cluster.get(uid, ""),
            }
        )

    edges = []
    for pair in scored_pairs:
        if pair["unitA"] in cluster_units and pair["unitB"] in cluster_units:
            edges.append(
                {
                    "source": pair["unitA"],
                    "target": pair["unitB"],
                    "weight": pair["score"],
                    "dominantSignal": pair.get("dominantSignal", ""),
                }
            )

    return {"nodes": nodes, "edges": edges}


def _build_manifest_entry(
    cluster: dict,
    finding: dict | None,
    units_by_id: dict[str, dict],
) -> dict:
    """Build a single drift-manifest area entry for a cluster."""
    members = cluster.get("members", [])

    # Collect file paths and member details
    files: set[str] = set()
    variants: list[dict] = []
    for uid in members:
        u = units_by_id.get(uid, {})
        fp = u.get("filePath", "")
        if fp:
            files.add(fp)
        variants.append(
            {
                "name": u.get("name", uid),
                "description": u.get("kind", ""),
                "file_count": 1,
                "files": [fp] if fp else [],
                "sample_file": fp,
            }
        )

    if finding:
        verdict = finding.get("verdict", "")
        impact = (
            "HIGH" if verdict == "DUPLICATE" else "MEDIUM" if verdict == "OVERLAPPING" else "LOW"
        )
        name = finding.get("role", f"Cluster {cluster['id']}")
        description = finding.get("sharedBehavior", f"{verdict} cluster: {name}")
        recommendation = finding.get("consolidationReasoning", "Review for consolidation.")
        analysis = (
            f"Verdict: {verdict}, Confidence: {finding.get('confidence', '')}, "
            f"Complexity: {finding.get('consolidationComplexity', 'unknown')}"
        )
    else:
        impact = "LOW"
        name = f"Cluster {cluster.get('id', 'unknown')}"
        description = (
            f"Structurally similar units (avg similarity: {cluster.get('avgSimilarity', 0):.2f})"
        )
        recommendation = "Awaiting semantic verification."
        avg_sim = cluster.get("avgSimilarity", 0)
        spread = cluster.get("directorySpread", 0)
        analysis = f"Avg similarity: {avg_sim:.2f}, spread: {spread} dirs"

    return {
        "id": f"semantic-{cluster['id']}",
        "name": name,
        "type": "semantic",
        "description": description,
        "impact": impact,
        "total_files": len(files),
        "variants": variants,
        "semantic_role": finding.get("role") if finding else None,
        "consolidation_assessment": finding.get("consolidationReasoning") if finding else None,
        "analysis": analysis,
        "recommendation": recommendation,
        "status": "pending",
    }


def _update_manifest(
    clusters: list[dict],
    findings_by_cluster: dict[str, dict],
    units_by_id: dict[str, dict],
    manifest_path: Path | None,
) -> None:
    """Write or update the drift manifest with semantic entries."""
    new_entries: list[dict] = []
    actionable_verdicts = {"DUPLICATE", "OVERLAPPING"}

    for cluster in clusters:
        cid = cluster.get("id", "")
        finding = findings_by_cluster.get(cid)
        verdict = finding.get("verdict", "") if finding else ""
        if finding and verdict in actionable_verdicts:
            new_entries.append(_build_manifest_entry(cluster, finding, units_by_id))

    if not new_entries:
        return

    if manifest_path is None:
        return

    # Read existing manifest or start fresh
    manifest: dict = {"areas": []}
    if manifest_path.exists():
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError):
            manifest = {"areas": []}

    if not isinstance(manifest, dict) or "areas" not in manifest:
        manifest = {"areas": []}

    # Remove existing semantic entries
    manifest["areas"] = [a for a in manifest["areas"] if a.get("type") != "semantic"]

    # Append new semantic entries
    manifest["areas"].extend(new_entries)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(
        f"  Manifest updated: {len(new_entries)} semantic entries -> {manifest_path}",
        file=sys.stderr,
    )


def generate_report(output_dir: Path, manifest_path: Path | None = None) -> None:
    """Read all artifacts and generate report outputs.

    Args:
        output_dir: Directory containing pipeline artifacts.
        manifest_path: Optional path to drift-manifest.json. If provided,
            semantic entries will be written/updated there.
    """
    units = read_code_units(output_dir)
    clusters = read_artifact("clusters.json", output_dir)

    units_by_id: dict[str, dict] = {}
    for u in units:
        uid = u.get("id", "")
        if uid:
            units_by_id[uid] = u

    # Load optional findings
    findings: list[dict] = []
    raw_findings = _load_optional("findings.json", output_dir)
    if isinstance(raw_findings, list):
        findings = raw_findings

    findings_by_cluster: dict[str, dict] = {}
    for f in findings:
        cid = f.get("clusterId", "")
        if cid:
            findings_by_cluster[cid] = f

    # Load scored pairs for atlas
    scored_pairs: list[dict] = []
    raw_pairs = _load_optional("similarity-matrix.json", output_dir)
    if isinstance(raw_pairs, list):
        scored_pairs = raw_pairs

    # Generate markdown report
    md = _generate_markdown(clusters, units_by_id, findings_by_cluster, len(units))
    report_path = output_dir / "semantic-drift-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"  Report written to {report_path}", file=sys.stderr)

    # Generate dependency atlas
    atlas = _generate_dependency_atlas(clusters, scored_pairs, units_by_id)
    write_artifact("dependency-atlas.json", atlas, output_dir)
    print(
        f"  Dependency atlas written ({len(atlas['nodes'])} nodes, {len(atlas['edges'])} edges)",
        file=sys.stderr,
    )

    # Update drift manifest
    _update_manifest(clusters, findings_by_cluster, units_by_id, manifest_path)
