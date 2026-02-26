"""Stage 2c: Type signature normalization.

Reads code-units.json and produces normalized type hashes with identifiers
stripped, enabling structural comparison of function/component signatures.
"""

import hashlib
import json
import re
from pathlib import Path

from .io_utils import read_code_units, write_artifact


def _sha256(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_IDENT_RE = re.compile(r"\b[a-z_]\w*\b", re.IGNORECASE)


def _strip_param_name(param_type: str) -> str:
    """Strip identifier names from a type string, leaving structure."""
    return param_type


def _classify_type(t: str) -> dict[str, bool]:
    """Classify a type string into broad categories."""
    lower = t.lower().strip()
    return {
        "has_void": lower in ("void", "undefined", "never"),
        "has_function": "=>" in t or "function" in lower or "callback" in lower,
        "has_object": lower in ("object",) or t.startswith("{") or "record" in lower,
        "has_array": "[]" in t or lower.startswith("array") or "list" in lower,
    }


def normalize_type(params: list[dict], return_type: str) -> dict:
    """Normalize a function's type signature.

    Args:
        params: List of parameter dicts with at least 'type' (and optionally 'name').
        return_type: The return type string.

    Returns:
        Dict with keys: strict_hash, loose_hash, canonical.
    """
    # Extract ordered parameter types, stripping names
    param_types: list[str] = []
    for p in params:
        ptype = p.get("type", "any")
        param_types.append(ptype)

    # Strict hash: ordered param types + return type, names stripped
    strict_data = {
        "params": param_types,
        "return": return_type,
    }
    strict_hash = _sha256(strict_data)

    # Loose hash: arity + broad type categories
    arity = len(param_types)
    ret_class = _classify_type(return_type)
    has_function_param = any(_classify_type(pt)["has_function"] for pt in param_types)
    has_object_param = any(_classify_type(pt)["has_object"] for pt in param_types)
    has_array_param = any(_classify_type(pt)["has_array"] for pt in param_types)
    loose_data = {
        "arity": arity,
        "has_void_return": ret_class["has_void"],
        "has_function_param": has_function_param,
        "has_object_param": has_object_param,
        "has_array_param": has_array_param,
    }
    loose_hash = _sha256(loose_data)

    # Canonical: human-readable string
    canonical_params = ", ".join(param_types) if param_types else ""
    canonical = f"({canonical_params}) => {return_type}"

    return {
        "strict_hash": strict_hash,
        "loose_hash": loose_hash,
        "canonical": canonical,
    }


def compute_type_signatures(units: list[dict]) -> dict:
    """Compute normalized type signatures for all units.

    Returns a dict keyed by unit id.
    """
    result: dict[str, dict] = {}
    for unit in units:
        uid = unit.get("id", "")
        if not uid:
            continue

        params = unit.get("parameters", unit.get("props", []))
        if not isinstance(params, list):
            params = []

        return_type = unit.get("returnType", "any")
        if not isinstance(return_type, str):
            return_type = "any"

        sig = normalize_type(params, return_type)

        # Also store arity for quick pre-filtering
        sig["arity"] = len(params)

        result[uid] = sig
    return result


def run(output_dir: Path) -> None:
    """Read code-units.json and write type-signatures.json."""
    units = read_code_units(output_dir)
    signatures = compute_type_signatures(units)
    write_artifact("type-signatures.json", signatures, output_dir)
