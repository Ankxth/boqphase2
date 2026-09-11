"""Runs Phase 2 (full-BOQ embodied carbon) end to end against a real BOQ
file and prints a readable summary -- no server, no form, no project
persistence. Standalone from test_full_pipeline.py (which exercises
Phase 1, the tiered conceptual estimator).

Usage (from backend/):
    python scripts/test_boq_carbon_pipeline.py <path_to_boq.xlsx> [sheet_name]
    python scripts/test_boq_carbon_pipeline.py <path_to_boq.xlsx> [sheet_name] --area 181150 --basis built_up_total

If sheet_name is omitted, auto-picks the first non-supplementary sheet
(same filtering app/services/boq_extractor.py applies).

--area / --basis are optional TOGETHER -- pass both or neither. Valid
--basis values: net_internal_gia, built_up_total, carpet_saleable, other.
See app/services/boq_carbon/engine.py's module docstring for why the
basis matters as much as the number itself.

Try it against the two reference BOQs already in this repo:
    python scripts/test_boq_carbon_pipeline.py app/data/reference_boqs/Botanico_BOQ.xlsx "Part-A & B_BOQ " --area 181150 --basis built_up_total
    python scripts/test_boq_carbon_pipeline.py app/data/reference_boqs/Ecopolitan_BOQ.xlsx "Part-A & B_BOQ" --area 205981.65 --basis built_up_total
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.boq_carbon.engine import calculate_from_boq
from app.services.boq_carbon.parser import extract_from_first_primary_sheet
from app.services.boq_extractor import SUPPLEMENTARY_SHEET_PATTERNS


def section(title: str):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("boq_path")
    parser.add_argument("sheet_name", nargs="?", default=None)
    parser.add_argument("--area", type=float, default=None, dest="floor_area_sqm")
    parser.add_argument(
        "--basis",
        choices=["net_internal_gia", "built_up_total", "carpet_saleable", "other"],
        default=None,
        dest="floor_area_basis",
    )
    parser.add_argument(
        "--show-lines",
        type=int,
        default=0,
        help="Print this many individual line-item results (sorted by GWP, highest first). Default 0 (category summary only).",
    )
    args = parser.parse_args()

    if (args.floor_area_sqm is None) != (args.floor_area_basis is None):
        print("Error: --area and --basis must be given together, or not at all.")
        sys.exit(1)

    section("STAGE 1: Locate sheet")
    sheet_name = args.sheet_name
    if sheet_name is None:
        sheet_name, _ = extract_from_first_primary_sheet(args.boq_path, SUPPLEMENTARY_SHEET_PATTERNS)
        print(f"No sheet given -- auto-picked first non-supplementary sheet: '{sheet_name}'")
    else:
        print(f"Using given sheet: '{sheet_name}'")

    section("STAGE 2: Extract + classify + calculate")
    result = calculate_from_boq(
        args.boq_path,
        sheet_name,
        floor_area_sqm=args.floor_area_sqm,
        floor_area_basis=args.floor_area_basis,
    )

    print(f"Source file: {result.source_file} (sheet: {result.sheet_name})")
    print(f"Lines total: {result.n_lines_total}")
    print(f"Lines classified (matched a material category): {result.n_lines_classified}")
    print(f"Lines computed (classified AND unit successfully converted): {result.n_lines_computed}")
    coverage = result.n_lines_computed / result.n_lines_total * 100 if result.n_lines_total else 0
    print(f"Coverage: {coverage:.1f}% of billable lines contribute to the total")

    section("STAGE 3: Totals by category")
    for c in result.by_category:
        print(f"  {c.category:22s} {c.gwp_kg_co2e:>15,.0f} kg CO2e  ({c.pct_of_total:5.1f}%)  n={c.line_item_count}")

    section("STAGE 4: Grand total")
    print(f"  TOTAL: {result.total_gwp_tonnes_co2e:,.1f} tonnes CO2e ({result.total_gwp_kg_co2e:,.0f} kg)")
    if result.floor_area_sqm:
        print(f"  Floor area: {result.floor_area_sqm:,.1f} sqm (basis: {result.floor_area_basis})")
        print(f"  -> {result.gwp_per_sqm:.1f} kg CO2e/sqm  |  {result.gwp_per_sqft:.2f} kg CO2e/sqft")
        print(f"\n  Basis note: {result.floor_area_basis_note}")
    else:
        print("  (No floor area given -- pass --area and --basis for a per-sqm figure.)")

    print(f"\n  {result.scope_note}")
    print(f"\n  {result.factor_disclaimer}")

    if args.show_lines:
        section(f"STAGE 5: Top {args.show_lines} line items by GWP")
        computed = [li for li in result.line_items if li.gwp_kg_co2e is not None]
        computed.sort(key=lambda li: -li.gwp_kg_co2e)
        for li in computed[: args.show_lines]:
            print(f"\n  row {li.row}  [{li.category}]  {li.gwp_kg_co2e:,.0f} kg CO2e")
            print(f"    {li.enriched_description[:140]}")
            print(f"    {li.basis_note}")

    section("DONE")


if __name__ == "__main__":
    main()