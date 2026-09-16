"""Shared helpers for golden-file regression tests -- Workstream 00 of the
Foundation Plan ("capture current behaviour first, before Workstream 01
starts touching emission factors").

A golden file is a small, committed JSON snapshot of one pipeline's
output against one real reference document (the same four documents this
whole project has been validated against by hand all along: Ecopolitan
and Botanico, each as a BOQ Excel and a Work Order PDF). Both
generate_golden_files.py (which WRITES these files) and the
test_*_golden.py modules (which READ and compare against them) import
this module, so the comparison logic only exists once.

Design choices, and why:

  - Compares the FULL by-category breakdown, not just the top-line total.
    A compensating error (one category's total quietly moving down while
    another moves up by a similar amount) would pass a total-only check
    and still represent a real, silent regression -- this is the whole
    reason to test the categories, not just the headline number.

  - Floating-point comparison uses a small RELATIVE tolerance (not exact
    equality) -- the underlying calculations are deterministic, but
    allowing a hair of tolerance avoids flaking on a harmless
    floating-point summation-order difference across Python/platform
    versions, while still catching any regression that actually changes
    a real number (a 1e-6 relative tolerance would never mask, say, a
    unit-conversion bug that's off by even 1%).

  - A golden file that doesn't exist yet, or whose source document isn't
    available in the current environment (see botanico_wo.json's
    "verified_by": "user_terminal_output" case), is reported as SKIPPED,
    never as a silent pass -- see tests/test_wo_carbon_golden.py's
    file-existence check.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

REL_TOLERANCE = 1e-6  # relative tolerance for kg CO2e / tonnes / per-sqm float comparisons


def load_golden(name: str) -> dict:
    path = GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No golden file at {path}. Run `python scripts/generate_golden_files.py --write` "
            f"to create it from the current pipeline output (only do this when the change is "
            f"INTENTIONAL -- see that script's own docstring)."
        )
    with open(path) as f:
        return json.load(f)


def _approx_equal(a: float, b: float, rel_tol: float = REL_TOLERANCE) -> bool:
    if a == b:
        return True
    if a == 0 or b == 0:
        return abs(a - b) < 1e-6
    return abs(a - b) / max(abs(a), abs(b)) <= rel_tol


def diff_result(golden: dict, current: dict, scalar_fields: list[str]) -> list[str]:
    """Returns a list of human-readable difference lines (empty list = no
    difference within tolerance). Used both by the pytest assertions
    (which turn a non-empty list into a failure message) and by
    generate_golden_files.py's dry-run diff preview.
    """
    diffs: list[str] = []

    for field in scalar_fields:
        g_val = golden.get(field)
        c_val = current.get(field)
        if isinstance(g_val, (int, float)) and isinstance(c_val, (int, float)):
            if not _approx_equal(float(g_val), float(c_val)):
                diffs.append(f"{field}: golden={g_val!r} -> current={c_val!r}")
        elif g_val != c_val:
            diffs.append(f"{field}: golden={g_val!r} -> current={c_val!r}")

    g_cats = {c["category"]: c for c in golden.get("by_category", [])}
    c_cats = {c["category"]: c for c in current.get("by_category", [])}

    for cat in sorted(set(g_cats) - set(c_cats)):
        diffs.append(f"by_category: {cat!r} present in golden but MISSING from current run")
    for cat in sorted(set(c_cats) - set(g_cats)):
        diffs.append(f"by_category: {cat!r} present in current run but NOT in golden (new category?)")
    for cat in sorted(set(g_cats) & set(c_cats)):
        g, c = g_cats[cat], c_cats[cat]
        if not _approx_equal(g["gwp_kg_co2e"], c["gwp_kg_co2e"]):
            diffs.append(f"by_category[{cat!r}].gwp_kg_co2e: golden={g['gwp_kg_co2e']:,.2f} -> current={c['gwp_kg_co2e']:,.2f}")
        if g["line_item_count"] != c["line_item_count"]:
            diffs.append(f"by_category[{cat!r}].line_item_count: golden={g['line_item_count']} -> current={c['line_item_count']}")

    return diffs


def source_file_exists(golden: dict) -> Optional[str]:
    """Returns None if the golden file's declared source document exists
    on disk (from backend/, i.e. the repo root this runs from), otherwise
    a human-readable reason string to use as a pytest.skip() message.
    """
    src = golden.get("_meta", {}).get("source_path")
    if src is None:
        return None
    if not Path(src).exists():
        return (
            f"Source document not present in this environment: {src!r}. "
            f"This golden file's expected numbers were recorded from "
            f"{golden['_meta'].get('verified_by', 'a prior run')} -- place the real file at "
            f"that path to turn this into a live regression test."
        )
    return None