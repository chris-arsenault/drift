"""Search commands for finding related units.

All output goes to stdout as formatted text.
"""

from pathlib import Path

from .io_utils import read_artifact, read_code_units


def search_calls(unit_id: str, output_dir: Path) -> None:
    """Find units that call the same things as this unit (shared callees)."""
    callgraph = read_artifact("call-graph.json", output_dir)
    target_entry = callgraph.get(unit_id)
    if not target_entry:
        print(f"Unit not found in call graph: {unit_id}")
        return

    target_callees = set(target_entry.get("calleeSetVector", {}).keys())
    if not target_callees:
        print(f"No callees found for: {unit_id}")
        return

    units = read_code_units(output_dir)
    units_by_id = {u["id"]: u for u in units if "id" in u}

    overlaps: list[tuple[str, int, int]] = []
    for uid, entry in callgraph.items():
        if uid == unit_id:
            continue
        other_callees = set(entry.get("calleeSetVector", {}).keys())
        shared = len(target_callees & other_callees)
        if shared > 0:
            overlaps.append((uid, shared, len(other_callees)))

    overlaps.sort(key=lambda x: x[1], reverse=True)

    if not overlaps:
        print(f"No units share callees with: {unit_id}")
        return

    unit_name = units_by_id.get(unit_id, {}).get("name", unit_id)
    print(f"Units sharing callees with {unit_name} ({len(target_callees)} callees):")
    print(f"  {'Shared':<8} {'Their#':<8} {'Name':<28} {'Kind':<12} {'File'}")
    print("  " + "-" * 75)
    for uid, shared, total in overlaps[:20]:
        u = units_by_id.get(uid, {})
        name = u.get("name", uid)
        kind = u.get("kind", "?")
        fp = u.get("filePath", "?")
        if len(fp) > 30:
            fp = "..." + fp[-27:]
        print(f"  {shared:<8} {total:<8} {name:<28} {kind:<12} {fp}")


def search_called_by(unit_id: str, output_dir: Path) -> None:
    """Find units consumed by the same set of consumers as this unit."""
    units = read_code_units(output_dir)
    units_by_id = {u["id"]: u for u in units if "id" in u}
    unit = units_by_id.get(unit_id)
    if not unit:
        print(f"Unit not found: {unit_id}")
        return

    def _extract_consumer_ids(consumers: list) -> set[str]:
        ids: set[str] = set()
        for c in consumers:
            if isinstance(c, dict):
                cid = c.get("id", c.get("unitId", ""))
            else:
                cid = str(c)
            if cid:
                ids.add(cid)
        return ids

    target_consumers = _extract_consumer_ids(unit.get("consumers", []))
    if not target_consumers:
        print(f"No consumers found for: {unit_id}")
        return

    overlaps: list[tuple[str, int, int]] = []
    for u in units:
        uid = u.get("id", "")
        if not uid or uid == unit_id:
            continue
        other_consumers = _extract_consumer_ids(u.get("consumers", []))
        shared = len(target_consumers & other_consumers)
        if shared > 0:
            overlaps.append((uid, shared, len(other_consumers)))

    overlaps.sort(key=lambda x: x[1], reverse=True)

    if not overlaps:
        print(f"No units share consumers with: {unit_id}")
        return

    unit_name = unit.get("name", unit_id)
    print(f"Units sharing consumers with {unit_name} ({len(target_consumers)} consumers):")
    print(f"  {'Shared':<8} {'Their#':<8} {'Name':<28} {'Kind':<12} {'File'}")
    print("  " + "-" * 75)
    for uid, shared, total in overlaps[:20]:
        u = units_by_id.get(uid, {})
        name = u.get("name", uid)
        kind = u.get("kind", "?")
        fp = u.get("filePath", "?")
        if len(fp) > 30:
            fp = "..." + fp[-27:]
        print(f"  {shared:<8} {total:<8} {name:<28} {kind:<12} {fp}")


def search_co_occurs(unit_id: str, output_dir: Path) -> None:
    """Find units that co-occur with this unit (frequently imported alongside)."""
    depctx = read_artifact("dependency-context.json", output_dir)
    entry = depctx.get(unit_id)
    if not entry:
        print(f"Unit not found in dependency context: {unit_id}")
        return

    co_vec = entry.get("cooccurrenceVector", {})
    if not co_vec:
        print(f"No co-occurrences found for: {unit_id}")
        return

    units = read_code_units(output_dir)
    units_by_id = {u["id"]: u for u in units if "id" in u}

    entries = sorted(co_vec.items(), key=lambda x: x[1], reverse=True)

    unit_name = units_by_id.get(unit_id, {}).get("name", unit_id)
    print(f"Units co-occurring with {unit_name} ({len(entries)}):")
    print(f"  {'Score':<8} {'Name':<28} {'Kind':<12} {'File'}")
    print("  " + "-" * 65)
    for uid, weight in entries[:20]:
        u = units_by_id.get(uid, {})
        name = u.get("name", uid)
        kind = u.get("kind", "?")
        fp = u.get("filePath", "?")
        if len(fp) > 30:
            fp = "..." + fp[-27:]
        print(f"  {weight:<8.4f} {name:<28} {kind:<12} {fp}")


def search_type_like(unit_id: str, output_dir: Path) -> None:
    """Find units with similar type signatures (strict hash match, then loose)."""
    typesigs = read_artifact("type-signatures.json", output_dir)
    target_sig = typesigs.get(unit_id)
    if not target_sig:
        print(f"No type signature found for: {unit_id}")
        return

    units = read_code_units(output_dir)
    units_by_id = {u["id"]: u for u in units if "id" in u}

    matches: list[tuple[str, str, str]] = []
    for uid, sig in typesigs.items():
        if uid == unit_id:
            continue
        if target_sig.get("strict_hash") and sig.get("strict_hash") == target_sig["strict_hash"]:
            matches.append((uid, "strict", sig.get("canonical", "")))
        elif target_sig.get("loose_hash") and sig.get("loose_hash") == target_sig["loose_hash"]:
            matches.append((uid, "loose", sig.get("canonical", "")))

    if not matches:
        print(f"No type-similar units found for: {unit_id}")
        return

    # Sort: strict matches first, then loose
    matches.sort(key=lambda x: (0 if x[1] == "strict" else 1, x[0]))

    unit_name = units_by_id.get(unit_id, {}).get("name", unit_id)
    canonical = target_sig.get("canonical", "?")
    print(f"Units with similar type to {unit_name}: {canonical}")
    print(f"  {'Match':<8} {'Name':<28} {'Kind':<12} {'File':<30} {'Canonical'}")
    print("  " + "-" * 90)
    for uid, match_type, can in matches:
        u = units_by_id.get(uid, {})
        name = u.get("name", uid)
        kind = u.get("kind", "?")
        fp = u.get("filePath", "?")
        if len(fp) > 28:
            fp = "..." + fp[-25:]
        print(f"  {match_type:<8} {name:<28} {kind:<12} {fp:<30} {can}")
