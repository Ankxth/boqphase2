"""Runs the full conceptual carbon calculator pipeline end to end and
prints a readable summary of every stage's output.

Stages exercised: form intake -> BOQ matching -> LLM fallback ->
IFC/CEA-adjusted calculation -> GRIHA-style typical-building benchmark ->
GRIHA V6.0 Criterion 21 estimate -> substitution suggestions.

Usage (from backend/):
    python scripts/test_full_pipeline.py

Edit the INPUT block below to test different project parameters.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas.project_schema import (
    FieldValue,
    ProjectSchema,
    StructuralSystemType,
)
from app.services.boq_match import match_boq_defaults
from app.services.llm_fallback import fill_missing_fields
from app.services.calculation_engine import calculate_embodied_carbon
from app.services.cost_estimation import estimate_cost
from app.services.benchmark import compute_benchmark
from app.services.griha_criterion21 import estimate_criterion_21
from app.services.substitution import suggest_substitutions


# --- INPUT: edit these to test different scenarios -------------------------
GFA_SQM = 50000
STRUCTURAL_SYSTEM = StructuralSystemType.rcc_frame
NUM_FLOORS = None          # set an int to test a specific floor band, or leave None to let LLM fallback estimate it
CEMENT_TYPE = None         # set to CementType.opc / .psc / .ppc to force it, or leave None for LLM fallback
STEEL_RATIO_KG_PER_SQM = None  # set a float to force it, or leave None for LLM fallback
# -----------------------------------------------------------------------------


def section(title: str):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():
    section("STAGE 1: Form intake")
    p = ProjectSchema(project_id="pipeline-test")
    p.mandatory.gfa_sqm = FieldValue(value=GFA_SQM, source="user-entered", confidence=1.0)
    p.mandatory.structural_system_type = FieldValue(value=STRUCTURAL_SYSTEM, source="user-entered", confidence=1.0)
    if NUM_FLOORS is not None:
        p.tier2.num_floors = FieldValue(value=NUM_FLOORS, source="user-entered", confidence=1.0)
    if CEMENT_TYPE is not None:
        p.tier3.cement_type = FieldValue(value=CEMENT_TYPE, source="user-entered", confidence=1.0)
    if STEEL_RATIO_KG_PER_SQM is not None:
        p.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(
            value=STEEL_RATIO_KG_PER_SQM, source="user-entered", confidence=1.0
        )
    print(f"GFA: {GFA_SQM} sqm | Structural system: {STRUCTURAL_SYSTEM.value}")
    print(f"Completeness before fill: {p.completeness()}")

    section("STAGE 2: BOQ matching (reference project scaling)")
    p = match_boq_defaults(p)
    derived = p.__dict__.get("_derived", {})
    if derived.get("matched_reference"):
        print(f"Matched reference: {derived['matched_reference']}")
        print(f"Concrete vol/sqm from match: {derived.get('concrete_vol_per_sqm')}")
    else:
        print("No BOQ match applied (expected until reference GFA is filled in).")

    section("STAGE 3: LLM fallback (remaining unset fields)")
    p = fill_missing_fields(p)
    print(f"Completeness after fill: {p.completeness()}")
    print("\nTier 3 fields after fallback:")
    for name in ["cement_type", "concrete_grade_mix", "steel_reinforcement_ratio_kg_per_sqm"]:
        fv = getattr(p.tier3, name)
        print(f"  {name}: value={fv.value!r} source={fv.source} confidence={fv.confidence}")

    section("STAGE 4: Calculation (IFC/CEA-adjusted)")
    result = calculate_embodied_carbon(p)
    for item in result.breakdown:
        print(f"  {item.material}")
        print(
            f"    {item.quantity:,.2f} {item.quantity_unit} x {item.factor_used:.4f} "
            f"{item.factor_unit} ({item.factor_source}) = {item.carbon_kg:,.0f} kgCO2e"
        )
        print(f"    quantity_source: {item.quantity_source}")
    print(f"\n  TOTAL: {result.total_carbon_tonnes:,.1f} tonnes CO2e")
    print(f"  Carbon/sqm: {result.carbon_per_sqm:.2f} kgCO2e/sqm")
    print(f"  Carbon/sqft: {result.carbon_per_sqft:.2f} kgCO2e/sqft")

    section("STAGE 5: Cost estimation")
    cost = estimate_cost(p, result)
    for b in cost.breakdown:
        print(f"  {b.material}")
        print(f"    Base rate: Rs.{b.base_rate:,.2f} {b.rate_unit} ({b.rate_provenance})")
        adj = b.inflation_adjustment
        if adj.applied:
            print(f"    Inflation adjustment: x{adj.multiplier:.3f} ({adj.priced_year} -> {adj.current_year}, +{adj.cumulative_pct_increase:.1f}%)")
            print(f"      Reasoning: {adj.reasoning}")
        else:
            print(f"    No inflation adjustment applied: {adj.reasoning}")
        print(f"    {b.quantity:,.2f} {b.quantity_unit} x Rs.{b.rate_used:,.2f} {b.rate_unit} = Rs.{b.cost_inr:,.0f}")
    print(f"\n  TOTAL COST: Rs.{cost.total_cost_inr:,.0f}")
    print(f"  Cost/sqm: Rs.{cost.cost_per_sqm_inr:,.2f}/sqm")
    print(f"  {cost.disclaimer}")

    section("STAGE 6: GRIHA-style typical-building benchmark")
    bench = compute_benchmark(p, result)
    print(f"  Actual:   {bench.actual_carbon_per_sqm:.2f} kgCO2e/sqm")
    print(f"  Baseline: {bench.baseline_carbon_per_sqm:.2f} kgCO2e/sqm ({bench.floor_band_used} typical)")
    print(f"  Difference: {bench.pct_difference_from_baseline:+.2f}% -- {bench.comparison_label}")

    section("STAGE 7: GRIHA V6.0 Criterion 21 estimate")
    griha = estimate_criterion_21(p, result)
    print(f"  Baseline GWP (OPC assumption): {griha.baseline_gwp_kg:,.0f} kg")
    print(f"  Design GWP (actual):           {griha.design_gwp_kg:,.0f} kg")
    print(f"  Reduction: {griha.pct_reduction:+.2f}%")
    print(f"  Estimated points: {griha.points_estimated} / {griha.max_points}")
    print(f"  {griha.scope_note}")

    section("STAGE 8: Substitution suggestions")
    suggestions = suggest_substitutions(p, result)
    if not suggestions:
        print("  No suggestions -- project is already at the lowest-carbon options tracked.")
    for s in suggestions:
        review_flag = " [REQUIRES ENGINEERING REVIEW]" if s.requires_engineering_review else ""
        print(f"\n  {s.description}{review_flag}")
        print(f"    {s.current_value} -> {s.suggested_value}")
        print(f"    Savings: {s.savings_kg:,.0f} kg ({s.savings_pct:.2f}%)")
        print(f"    {s.reasoning}")

    section("DONE")
    print(f"Pipeline ran end to end for project '{p.project_id}'.")


if __name__ == "__main__":
    main()