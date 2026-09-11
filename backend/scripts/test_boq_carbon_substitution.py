"""Runs Phase 2's material substitution engine end to end against a real
BOQ file -- no server, no upload, just the same calculate_from_boq() +
apply_substitutions() the API endpoint uses. Standalone from
test_boq_carbon_pipeline.py (which only runs the base calculation).

Usage (from backend/):
    python scripts/test_boq_carbon_substitution.py <path_to_boq.xlsx> [sheet_name] --area 181150 --basis built_up_total --sub opc_to_psc:40 --sub brick_to_aac_block:80

Each --sub takes "<substitution_id>:<user_pct>". Pass more than one --sub
to see combined_impact (and, if they overlap on the same lines, the
explanatory note instead of a summed number -- see
substitution_engine.py's module docstring for why).

Try it against the two reference BOQs already in this repo:
    python scripts/test_boq_carbon_substitution.py app/data/reference_boqs/Botanico_BOQ.xlsx "Part-A & B_BOQ " --area 181150 --basis built_up_total --sub opc_to_psc:40 --sub brick_to_aac_block:60
    python scripts/test_boq_carbon_substitution.py app/data/reference_boqs/Ecopolitan_BOQ.xlsx "Part-A & B_BOQ" --area 180169 --basis built_up_total --sub opc_to_ppc:60 --sub brick_to_aac_block:100
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.boq_carbon.engine import calculate_from_boq
from app.services.boq_carbon.parser import extract_from_first_primary_sheet
from app.services.boq_carbon.substitution_engine import SubstitutionRequest, apply_substitutions
from app.services.boq_extractor import SUPPLEMENTARY_SHEET_PATTERNS


def section(title: str):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def parse_sub(s: str) -> SubstitutionRequest:
    sub_id, pct = s.rsplit(":", 1)
    return SubstitutionRequest(substitution_id=sub_id, user_pct=float(pct))


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
    parser.add_argument("--sub", action="append", default=[], help="<substitution_id>:<user_pct>, repeatable")
    args = parser.parse_args()

    if (args.floor_area_sqm is None) != (args.floor_area_basis is None):
        print("Error: --area and --basis must be given together, or not at all.")
        sys.exit(1)
    if not args.sub:
        print("Error: pass at least one --sub <substitution_id>:<user_pct>")
        sys.exit(1)

    section("STAGE 1: Locate sheet + calculate base result")
    sheet_name = args.sheet_name
    if sheet_name is None:
        sheet_name, _ = extract_from_first_primary_sheet(args.boq_path, SUPPLEMENTARY_SHEET_PATTERNS)
        print(f"No sheet given -- auto-picked first non-supplementary sheet: '{sheet_name}'")

    base_result = calculate_from_boq(
        args.boq_path, sheet_name, floor_area_sqm=args.floor_area_sqm, floor_area_basis=args.floor_area_basis
    )
    print(f"Base total: {base_result.total_gwp_tonnes_co2e:,.1f} t CO2e ({base_result.total_gwp_kg_co2e:,.0f} kg)")
    if base_result.gwp_per_sqm:
        print(f"Base per-sqm: {base_result.gwp_per_sqm:.1f} kg CO2e/sqm")

    section("STAGE 2: Apply requested substitutions")
    requests = [parse_sub(s) for s in args.sub]
    response = apply_substitutions(requests, base_result)

    for r in response.substitutions:
        print(f"\n--- {r.substitution_id} @ {r.user_pct:g}% (cap {r.max_recommended_pct:g}%) ---")
        print(f"  Label: {r.label}")
        print(f"  Affected line items: {r.affected_line_item_count}")
        print(f"  Original: {r.original_gwp_kg_co2e:,.0f} kg  ->  New: {r.new_gwp_kg_co2e:,.0f} kg")
        print(f"  Savings: {r.savings_kg_co2e:,.0f} kg ({r.savings_pct_of_affected_lines:.1f}% of affected lines, "
              f"{r.savings_pct_of_total_boq:.2f}% of total BOQ)")
        if r.exceeds_recommended:
            print(f"  ** EXCEEDS RECOMMENDED CEILING -- requires engineering review **")
        if r.requires_engineering_review:
            print(f"  Caveat: {r.structural_caveat}")
        print(f"  Reasoning: {r.reasoning}")
        print(f"  Source: {r.source}")

    section("STAGE 3: Combined impact")
    ci = response.combined_impact
    if ci is None:
        print("  (only meaningful with 2+ substitutions)")
    elif ci.note:
        print(f"  NOT COMBINED: {ci.note}")
    else:
        print(f"  Total savings: {ci.total_savings_kg_co2e:,.0f} kg ({ci.total_savings_pct_of_total_boq:.2f}% of total BOQ)")
        if ci.requires_engineering_review:
            print("  Includes at least one substitution requiring engineering review.")

    section("DONE")


if __name__ == "__main__":
    main()
