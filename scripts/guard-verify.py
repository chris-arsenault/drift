#!/usr/bin/env python3
"""Verify guard artifacts: drift markers, ESLint integration, ADR enforcement.

Usage:
    python3 guard-verify.py <project-root> [--check markers|eslint|adr|all] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _drift_common import (
    DRIFT_MARKER,
    MARKER_PATTERNS,
    TYPE_EXTENSIONS,
    error,
    has_drift_marker,
    info,
    load_config,
    resolve_project_root,
    success,
    warn,
)


# ── Markers check ────────────────────────────────────────────────────

def check_markers(project_root: Path, config: dict) -> dict:
    """Check all sync directories for files missing drift markers."""
    sync_map = config.get("sync", {})
    ok: list[str] = []
    failures: list[dict] = []

    for art_type, rel_dir in sync_map.items():
        src_dir = project_root / rel_dir
        if not src_dir.is_dir():
            continue

        exts = TYPE_EXTENSIONS.get(art_type, set())

        for entry in sorted(src_dir.iterdir()):
            if not entry.is_file():
                continue
            if exts and entry.suffix not in exts:
                continue

            rel_path = str(entry.relative_to(project_root))
            if has_drift_marker(entry):
                ok.append(rel_path)
            else:
                expected = MARKER_PATTERNS.get(entry.suffix, DRIFT_MARKER)
                failures.append({
                    "file": rel_path,
                    "type": art_type,
                    "expected_marker": expected,
                })

    total = len(ok) + len(failures)
    return {
        "check": "markers",
        "pass": len(failures) == 0,
        "total": total,
        "ok": len(ok),
        "failures": failures,
    }


# ── ESLint integration check ─────────────────────────────────────────

def find_eslint_config(project_root: Path) -> Path | None:
    """Find the ESLint config file."""
    candidates = [
        "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts",
        ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", ".eslintrc.yaml", ".eslintrc",
    ]
    for name in candidates:
        p = project_root / name
        if p.exists():
            return p
    return None


def check_eslint(project_root: Path) -> dict:
    """Check that ESLint rule files are referenced in the ESLint config."""
    rules_dir = project_root / "eslint-rules"
    if not rules_dir.is_dir():
        return {
            "check": "eslint",
            "pass": True,
            "total": 0,
            "ok": 0,
            "failures": [],
            "note": "No eslint-rules/ directory found",
        }

    rule_files = sorted(
        f for f in rules_dir.iterdir()
        if f.is_file() and f.suffix in {".js", ".cjs", ".mjs", ".ts"}
    )

    if not rule_files:
        return {
            "check": "eslint",
            "pass": True,
            "total": 0,
            "ok": 0,
            "failures": [],
            "note": "No rule files in eslint-rules/",
        }

    config_path = find_eslint_config(project_root)
    if not config_path:
        return {
            "check": "eslint",
            "pass": False,
            "total": len(rule_files),
            "ok": 0,
            "failures": [{"rule": f.name, "reason": "No ESLint config found"} for f in rule_files],
        }

    try:
        config_text = config_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        config_text = ""

    ok: list[dict] = []
    failures: list[dict] = []

    for rf in rule_files:
        stem = rf.stem
        # Check if the file is referenced in the config (import or require)
        imported = (
            stem in config_text
            or rf.name in config_text
            or f"eslint-rules/{rf.name}" in config_text
            or f"./eslint-rules/{rf.name}" in config_text
        )

        # Check if the rule name appears in a rules block
        # Convention: drift-guard/rule-stem
        rule_name = f"drift-guard/{stem}"
        enabled = rule_name in config_text

        if imported and enabled:
            # Try to detect severity
            severity_match = re.search(
                rf"""['"]{re.escape(rule_name)}['"]\s*:\s*['"](\w+)['"]""",
                config_text,
            )
            severity = severity_match.group(1) if severity_match else "unknown"
            ok.append({"rule": rf.name, "status": "INTEGRATED", "severity": severity})
        elif imported:
            failures.append({"rule": rf.name, "reason": "Imported but not enabled in rules block"})
        else:
            failures.append({"rule": rf.name, "reason": "Not referenced in ESLint config"})

    return {
        "check": "eslint",
        "pass": len(failures) == 0,
        "total": len(rule_files),
        "ok": len(ok),
        "integrated": ok,
        "failures": failures,
    }


# ── ADR enforcement check ────────────────────────────────────────────

_ENFORCEMENT_SECTION_RE = re.compile(
    r"^##\s+Enforcement\s*$",
    re.MULTILINE,
)
_STATUS_RE = re.compile(
    r"\*\*Status:\*\*\s*(\w+)|^Status:\s*(\w+)",
    re.MULTILINE,
)
_RULE_REF_RE = re.compile(
    r"(?:drift-guard/[\w-]+|no-restricted-imports|no-restricted-syntax|no-restricted-globals)",
)
_PATH_REF_RE = re.compile(
    r"(?:docs/\S+\.md|eslint-rules/\S+\.(?:js|ts|cjs|mjs)|\S+/REVIEW_CHECKLIST\.md|\S+/CONTRIBUTING\.md)",
)


def parse_adr_enforcement(content: str) -> tuple[str, list[str], list[str]]:
    """Parse an ADR for status, rule references, and path references in the Enforcement section."""
    # Find status
    status_match = _STATUS_RE.search(content)
    status = (status_match.group(1) or status_match.group(2)) if status_match else "Unknown"

    # Find enforcement section
    enforcement_match = _ENFORCEMENT_SECTION_RE.search(content)
    if not enforcement_match:
        return status, [], []

    # Get text from ## Enforcement to next ## or end
    start = enforcement_match.end()
    next_section = re.search(r"^##\s", content[start:], re.MULTILINE)
    end = start + next_section.start() if next_section else len(content)
    enforcement_text = content[start:end]

    rules = _RULE_REF_RE.findall(enforcement_text)
    paths = _PATH_REF_RE.findall(enforcement_text)

    return status, rules, paths


def check_adr(project_root: Path) -> dict:
    """Check ADR enforcement sections for broken references."""
    adr_dir = project_root / "docs" / "adr"
    if not adr_dir.is_dir():
        return {
            "check": "adr",
            "pass": True,
            "total": 0,
            "ok": 0,
            "degraded": 0,
            "broken": 0,
            "details": [],
            "note": "No docs/adr/ directory found",
        }

    adr_files = sorted(adr_dir.glob("*.md"))
    if not adr_files:
        return {
            "check": "adr",
            "pass": True,
            "total": 0,
            "ok": 0,
            "degraded": 0,
            "broken": 0,
            "details": [],
        }

    # Read ESLint config for rule verification
    config_path = find_eslint_config(project_root)
    config_text = ""
    if config_path:
        try:
            config_text = config_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass

    results: list[dict] = []
    ok_count = 0
    degraded_count = 0
    broken_count = 0

    for adr_file in adr_files:
        try:
            content = adr_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        status, rules, paths = parse_adr_enforcement(content)
        if status.lower() not in ("accepted", "proposed"):
            continue

        issues: list[str] = []
        total_mechanisms = len(rules) + len(paths)

        if total_mechanisms == 0:
            issues.append("No enforcement mechanisms declared")

        # Check rules
        for rule in rules:
            if rule.startswith("drift-guard/"):
                rule_stem = rule.split("/", 1)[1]
                rule_file = project_root / "eslint-rules" / f"{rule_stem}.js"
                if not rule_file.exists():
                    rule_file = project_root / "eslint-rules" / f"{rule_stem}.ts"
                if not rule_file.exists():
                    issues.append(f"Rule file missing: {rule}")
                elif rule not in config_text:
                    issues.append(f"Rule not enabled in ESLint config: {rule}")

        # Check paths
        for path_ref in paths:
            ref_path = project_root / path_ref
            if not ref_path.exists():
                issues.append(f"Referenced file missing: {path_ref}")

        adr_name = adr_file.stem
        if not issues:
            status_label = "OK"
            ok_count += 1
        elif any("missing" in i for i in issues):
            status_label = "BROKEN"
            broken_count += 1
        else:
            status_label = "DEGRADED"
            degraded_count += 1

        results.append({
            "adr": adr_name,
            "file": str(adr_file.relative_to(project_root)),
            "status": status_label,
            "mechanisms": total_mechanisms,
            "issues": issues,
        })

    all_pass = broken_count == 0 and degraded_count == 0
    return {
        "check": "adr",
        "pass": all_pass,
        "total": len(results),
        "ok": ok_count,
        "degraded": degraded_count,
        "broken": broken_count,
        "details": results,
    }


# ── Human-readable formatting ─────────────────────────────────────────

def format_results(checks: list[dict]) -> str:
    """Format verification results as human-readable text."""
    lines = ["Guard Verification Report\n"]

    for check in checks:
        name = check["check"].title()
        lines.append(f"{name}:")

        if check["check"] == "markers":
            if check["pass"]:
                lines.append(f"  OK: {check['ok']}/{check['total']} files have drift markers")
            else:
                lines.append(f"  {check['ok']}/{check['total']} files have drift markers")
                for f in check["failures"]:
                    lines.append(f"    MISSING: {f['file']}  (add \"{f['expected_marker']}\" as line 1)")

        elif check["check"] == "eslint":
            if check.get("note"):
                lines.append(f"  {check['note']}")
            else:
                for r in check.get("integrated", []):
                    lines.append(f"  {r['rule']:40} INTEGRATED ({r['severity']})")
                for f in check["failures"]:
                    lines.append(f"  {f['rule']:40} NOT INTEGRATED -- {f['reason']}")
                lines.append(f"  {check['ok']}/{check['total']} rules integrated")

        elif check["check"] == "adr":
            if check.get("note"):
                lines.append(f"  {check['note']}")
            else:
                for d in check["details"]:
                    status_str = f"{d['status']} ({d['mechanisms']} mechanism(s))"
                    lines.append(f"  {d['adr']:40} {status_str}")
                    for issue in d["issues"]:
                        lines.append(f"    - {issue}")
                lines.append(f"  {check['ok']}/{check['total']} OK, {check['degraded']} degraded, {check['broken']} broken")

        lines.append("")

    # Scoreboard
    all_pass = all(c["pass"] for c in checks)
    lines.append(f"Overall: {'PASS' if all_pass else 'FAIL'}")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Verify guard artifacts")
    parser.add_argument("project_root", help="Path to project root")
    parser.add_argument("--check", choices=["markers", "eslint", "adr", "all"], default="all",
                        help="Which checks to run (default: all)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project_root)
    checks_to_run = [args.check] if args.check != "all" else ["markers", "eslint", "adr"]

    config = None
    if "markers" in checks_to_run:
        config = load_config(project_root)

    results: list[dict] = []
    for check_name in checks_to_run:
        if check_name == "markers":
            results.append(check_markers(project_root, config))
        elif check_name == "eslint":
            results.append(check_eslint(project_root))
        elif check_name == "adr":
            results.append(check_adr(project_root))

    if args.json:
        overall = all(r["pass"] for r in results)
        print(json.dumps({"checks": {r["check"]: r for r in results}, "overall_pass": overall}, indent=2))
    else:
        print(format_results(results))

    if not all(r["pass"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
