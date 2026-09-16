"""End-to-end test: runs the actual wo_carbon_engine against the real
Ecopolitan WO KPIL PDF and checks it reproduces the manually-verified
numbers (checksum against the WO's own BOQ SUMMARY grand total, plus the
known total/per-sqm figures from the manual verification pass).

Usage (from backend/):
    python scripts/test_wo_carbon_engine.py <path_to_wo.pdf> <path_to_master.json> [floor_area_sqm]
"""
import sys
from pathlib import Path

# Same pattern as scripts/test_boq_carbon_pipeline.py -- this script lives
# in backend/scripts/, so backend/ (the parent of scripts/) needs to be on
# sys.path for `app.services...` imports to resolve, since it isn't run
# as an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.wo_carbon.wo_carbon_engine import calculate_from_work_order

_passed = 0
_failed = 0


def check(label, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("You ran this with no arguments -- it needs the WO PDF path and the master JSON path, e.g.:\n")
        print('  python scripts/test_wo_carbon_engine.py "app/data/work_orders/Provident_Ecopolitan_WO_KPIL_1.pdf" "app/data/companies/provident/master_item_codes.json" 205981.65\n')
        print("(quote any path that has spaces in it, like yours under 'phase 2 (2)')")
        sys.exit(1)

    pdf_path = sys.argv[1]
    master_json_path = sys.argv[2]
    floor_area = float(sys.argv[3]) if len(sys.argv) > 3 else 205981.65

    result = calculate_from_work_order(pdf_path, master_json_path, floor_area_sqm=floor_area, floor_area_basis="built_up_total")

    print(f"\nSource: {result.source_file}")
    print(f"Line items parsed: {result.n_line_items_parsed}")
    print(f"Line items computed: {result.n_line_items_computed}")
    print(f"Total WO amount: Rs {result.total_wo_amount:,.2f}")
    print(f"Computed WO amount: Rs {result.computed_wo_amount:,.2f}")
    print(f"\nTOTAL: {result.total_gwp_tonnes_co2e:,.2f} tonnes CO2e")
    print(f"PER SQM: {result.gwp_per_sqm:,.2f} kg CO2e/sqm (floor area {floor_area:,.2f} sqm)")
    print("\nBy category:")
    for c in result.by_category:
        print(f"  {c.category:22s} {c.gwp_kg_co2e:>15,.0f} kg CO2e  ({c.pct_of_total:5.1f}%)  n={c.line_item_count}")

    print("\n--- Checks ---")
    check("Parse checksum OK (parsed Amounts == WO's own BOQ SUMMARY grand total)", result.parse_checksum_ok is True)
    check("All 7,910 line-item occurrences parsed", result.n_line_items_parsed == 7910, f"got {result.n_line_items_parsed}")
    check("No exception raised end-to-end", True)
    # This was a tight, Ecopolitan-specific historical ballpark
    # (35,000-45,000) that predates both the classification-enhancement
    # pass and Workstream 01's factor unification -- both legitimately
    # moved the real total (currently ~46,646 t CO2e for Ecopolitan) and
    # that old range was never updated to track it, so it was already
    # stale before this change. Loosened to a wide, non-brittle sanity
    # check -- the real, precise authority on "did this change on
    # purpose" is now tests/test_wo_carbon_golden.py (Workstream 00),
    # which pins the exact expected number and fails loudly with a real
    # diff instead of a vague ballpark miss.
    check("Total is in a sane order of magnitude (20,000-70,000 t CO2e)", 20000 <= result.total_gwp_tonnes_co2e <= 70000, f"got {result.total_gwp_tonnes_co2e}")

    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    main()