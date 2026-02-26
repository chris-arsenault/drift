"""Inspection commands for exploring pipeline output.

All output goes to stdout as formatted text.
"""

import json
from pathlib import Path

from .io_utils import read_artifact, read_code_units


def _load_optional(name: str, output_dir: Path) -> dict | list | None:
    """Load an artifact, returning None if it doesn't exist."""
    try:
        return read_artifact(name, output_dir)
    except FileNotFoundError:
        return None


def inspect_unit(unit_id: str, output_dir: Path) -> None:
    """Show all data for a single unit across every artifact."""
    units = read_code_units(output_dir)
    units_by_id = {u["id"]: u for u in units if "id" in u}
    unit = units_by_id.get(unit_id)
    if not unit:
        print(f"Unit not found: {unit_id}")
        return

    print(f"=== {unit.get('name', unit_id)} ===")
    print(f"  ID:       {unit_id}")
    print(f"  Kind:     {unit.get('kind', '?')}")
    print(f"  File:     {unit.get('filePath', '?')}")
    print(f"  Lines:    {unit.get('startLine', '?')}-{unit.get('endLine', '?')}")
    print(f"  Callees:  {len(unit.get('callees', []))}")
    print(f"  Consumers:{len(unit.get('consumers', []))}")
    print()

    fingerprints = _load_optional("structural-fingerprints.json", output_dir)
    if isinstance(fingerprints, dict) and unit_id in fingerprints:
        fp = fingerprints[unit_id]
        print("Structural Fingerprint:")
        print(f"  JSX hash (exact): {fp.get('jsxHash', {}).get('exact', 'n/a')}")
        print(f"  JSX hash (fuzzy): {fp.get('jsxHash', {}).get('fuzzy', 'n/a')}")
        print(f"  Hook profile:     {fp.get('hookProfile', [])}")
        print(f"  Behavior flags:   {fp.get('behaviorFlags', [])}")
        imports = fp.get("importConstellation", {})
        if imports:
            top = sorted(imports.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"  Top imports:      {', '.join(k for k, _ in top)}")
        print()

    typesigs = _load_optional("type-signatures.json", output_dir)
    if isinstance(typesigs, dict) and unit_id in typesigs:
        sig = typesigs[unit_id]
        print("Type Signature:")
        print(f"  Canonical:    {sig.get('canonical', '?')}")
        print(f"  Arity:        {sig.get('arity', '?')}")
        print(f"  Strict hash:  {sig.get('strict_hash', 'n/a')}")
        print(f"  Loose hash:   {sig.get('loose_hash', 'n/a')}")
        print()

    callgraph = _load_optional("call-graph.json", output_dir)
    if isinstance(callgraph, dict) and unit_id in callgraph:
        cg = callgraph[unit_id]
        vec = cg.get("calleeSetVector", {})
        print("Call Graph:")
        print(f"  Depth profile:    {cg.get('depthProfile', [])}")
        print(f"  Callee set size:  {len(vec)}")
        seq_hashes = cg.get("sequenceHashes", {})
        if seq_hashes:
            print(f"  Sequence hashes:  {', '.join(seq_hashes.keys())}")
        chain_hashes = cg.get("chainPatternHashes", [])
        if chain_hashes:
            print(f"  Chain patterns:   {len(chain_hashes)}")
        print()

    depctx = _load_optional("dependency-context.json", output_dir)
    if isinstance(depctx, dict) and unit_id in depctx:
        dc = depctx[unit_id]
        print("Dependency Context:")
        profile = dc.get("consumerProfile", [])
        if len(profile) >= 3:
            print(f"  Consumer count (norm): {profile[0]:.3f}")
            print(f"  Kind entropy:          {profile[1]:.3f}")
            print(f"  Directory spread:      {profile[2]:.3f}")
        co_vec = dc.get("cooccurrenceVector", {})
        if co_vec:
            top_co = sorted(co_vec.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"  Top co-occurrences:    {', '.join(f'{k}({v:.2f})' for k, v in top_co)}")
        print(f"  Neighborhood r1:       {dc.get('neighborhoodHash_r1', 'n/a')[:16]}...")
        print(f"  Neighborhood r2:       {dc.get('neighborhoodHash_r2', 'n/a')[:16]}...")
        print()


def inspect_similar(unit_id: str, top: int, output_dir: Path) -> None:
    """Show top N units most similar to the given unit."""
    scored_pairs = read_artifact("similarity-matrix.json", output_dir)
    matches: list[dict] = []
    for pair in scored_pairs:
        if pair["unitA"] == unit_id:
            matches.append(
                {
                    "unit": pair["unitB"],
                    "score": pair["score"],
                    "dominantSignal": pair.get("dominantSignal", ""),
                    "signals": pair.get("signals", {}),
                }
            )
        elif pair["unitB"] == unit_id:
            matches.append(
                {
                    "unit": pair["unitA"],
                    "score": pair["score"],
                    "dominantSignal": pair.get("dominantSignal", ""),
                    "signals": pair.get("signals", {}),
                }
            )

    matches.sort(key=lambda m: m["score"], reverse=True)
    matches = matches[:top]

    if not matches:
        print(f"No similar units found for: {unit_id}")
        return

    units = read_code_units(output_dir)
    units_by_id = {u["id"]: u for u in units if "id" in u}

    print(f"Top {len(matches)} similar to: {unit_id}")
    print(f"{'Score':<8} {'Dominant':<18} {'Name':<28} {'Kind':<12} {'File'}")
    print("-" * 90)
    for m in matches:
        u = units_by_id.get(m["unit"], {})
        name = u.get("name", m["unit"])
        kind = u.get("kind", "?")
        fp = u.get("filePath", "?")
        if len(fp) > 35:
            fp = "..." + fp[-32:]
        print(f"{m['score']:<8.4f} {m['dominantSignal']:<18} {name:<28} {kind:<12} {fp}")
        top_sigs = sorted(m["signals"].items(), key=lambda x: x[1], reverse=True)[:3]
        sig_str = ", ".join(f"{k}:{v:.3f}" for k, v in top_sigs)
        print(f"         {sig_str}")


def inspect_cluster(cluster_id: str, output_dir: Path) -> None:
    """Show cluster details including members, signals, and findings."""
    clusters = read_artifact("clusters.json", output_dir)
    for cluster in clusters:
        if cluster.get("id") == cluster_id:
            units = read_code_units(output_dir)
            units_by_id = {u["id"]: u for u in units if "id" in u}

            print(f"Cluster: {cluster_id}")
            print(f"Members:          {cluster.get('memberCount', 0)}")
            print(f"Avg Similarity:   {cluster.get('avgSimilarity', 0):.4f}")
            print(f"Rank Score:       {cluster.get('rankScore', 0):.4f}")
            print(f"Directory Spread: {cluster.get('directorySpread', 0)}")
            print(f"Kind Mix:         {json.dumps(cluster.get('kindMix', {}))}")
            print(f"Consumer Overlap: {cluster.get('consumerOverlap', 0):.4f}")
            print()

            shared = cluster.get("sharedCallees", [])
            if shared:
                print(f"Shared Callees: {', '.join(shared)}")
                print()

            print("Signal Breakdown:")
            for sig, val in sorted(
                cluster.get("signalBreakdown", {}).items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                bar = "#" * int(val * 40)
                print(f"  {sig:<20} {val:.4f} {bar}")
            print()

            print("Members:")
            print(f"  {'Name':<30} {'Kind':<12} {'File'}")
            print("  " + "-" * 70)
            for uid in cluster.get("members", []):
                u = units_by_id.get(uid, {})
                name = u.get("name", uid)
                kind = u.get("kind", "?")
                fp = u.get("filePath", "?")
                if len(fp) > 45:
                    fp = "..." + fp[-42:]
                print(f"  {name:<30} {kind:<12} {fp}")

            # Show findings if available
            findings_data = _load_optional("findings.json", output_dir)
            if isinstance(findings_data, list):
                for finding in findings_data:
                    if finding.get("clusterId") == cluster_id:
                        print()
                        print("Finding:")
                        print(f"  Verdict:        {finding.get('verdict', '?')}")
                        print(f"  Confidence:     {finding.get('confidence', '?')}")
                        role = finding.get("roleDescription", "")
                        if role:
                            print(f"  Role:           {role}")
                        assessment = finding.get("consolidationAssessment", "")
                        if assessment:
                            print(f"  Consolidation:  {assessment}")
                        break
            return

    print(f"Cluster not found: {cluster_id}")


def inspect_consumers(unit_id: str, output_dir: Path) -> None:
    """Show who imports this unit."""
    units = read_code_units(output_dir)
    units_by_id = {u["id"]: u for u in units if "id" in u}
    unit = units_by_id.get(unit_id)
    if not unit:
        print(f"Unit not found: {unit_id}")
        return

    consumers = unit.get("consumers", [])
    if not consumers:
        print(f"No consumers found for: {unit_id}")
        return

    print(f"Consumers of {unit.get('name', unit_id)} ({len(consumers)}):")
    print(f"  {'Name':<30} {'Kind':<12} {'File'}")
    print("  " + "-" * 60)
    for c in consumers:
        if isinstance(c, dict):
            cid = c.get("id", c.get("unitId", ""))
            cu = units_by_id.get(cid, c)
            name = cu.get("name", cid)
            kind = cu.get("kind", "?")
            fp = cu.get("filePath", c.get("file", "?"))
        else:
            cid = str(c)
            cu = units_by_id.get(cid, {})
            name = cu.get("name", cid)
            kind = cu.get("kind", "?")
            fp = cu.get("filePath", "?")
        if len(fp) > 40:
            fp = "..." + fp[-37:]
        print(f"  {name:<30} {kind:<12} {fp}")


def inspect_callers(unit_id: str, output_dir: Path) -> None:
    """Show what this unit calls (its callees list)."""
    units = read_code_units(output_dir)
    units_by_id = {u["id"]: u for u in units if "id" in u}
    unit = units_by_id.get(unit_id)
    if not unit:
        print(f"Unit not found: {unit_id}")
        return

    callees = unit.get("callees", [])
    if not callees:
        print(f"No callees found for: {unit_id}")
        return

    print(f"Callees of {unit.get('name', unit_id)} ({len(callees)}):")
    print(f"  {'Target':<35} {'Context':<12} {'File'}")
    print("  " + "-" * 65)

    seen: set[str] = set()
    for callee in callees:
        if isinstance(callee, dict):
            target = callee.get("target", "")
            context = callee.get("context", "?")
        else:
            target = str(callee)
            context = "?"

        if not target or target in seen:
            continue
        seen.add(target)

        tu = units_by_id.get(target, {})
        name = tu.get("name", target)
        fp = tu.get("filePath", "?")
        if len(fp) > 35:
            fp = "..." + fp[-32:]
        print(f"  {name:<35} {context:<12} {fp}")
