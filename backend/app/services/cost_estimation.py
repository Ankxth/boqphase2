"""Construction cost estimation for concrete and steel.

Prefers real BOQ-sourced cost rates (from boq_match.py or
project_boq_refinement.py, via project._derived). When BOQ-sourced rates
are used AND the reference project's pricing year is known, an
LLM-based inflation adjustment (cost_adjustment.py) is applied.

Materials are grouped by pricing year and adjusted in ONE batched call
per group (see cost_adjustment.py's module docstring for why batching
matters -- separate per-material calls were shown to converge on the
same generic percentage rather than reasoning about each material's own
distinct cost drivers).

If pricing year is unknown, the raw historical BOQ rate is used as-is.
Falls back to a generic unsourced placeholder rate only when no
BOQ-sourced rate exists at all.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel

from app.schemas.project_schema import ProjectSchema
from app.services.calculation_engine import CalculationResult
from app.services.cost_adjustment import InflationAdjustment, get_inflation_adjustments
from app.services import reference_store

FALLBACK_CONCRETE_COST_PER_M3 = 7000.0   # INR/m3 -- rough, unsourced placeholder
FALLBACK_STEEL_COST_PER_KG = 65.0        # INR/kg -- rough, unsourced placeholder


class CostBreakdown(BaseModel):
    material: str
    quantity: float
    quantity_unit: str
    base_rate: float
    rate_used: float
    rate_unit: str
    rate_provenance: str
    inflation_adjustment: InflationAdjustment
    cost_inr: float


class CostEstimate(BaseModel):
    project_id: str
    gfa_sqm: float
    breakdown: list[CostBreakdown]
    total_cost_inr: float
    cost_per_sqm_inr: float
    scope_note: str = (
        "Concrete + steel only -- same scope as the carbon calculation. "
        "Does not include finishes, MEP, labor overhead beyond what's "
        "embedded in the source BOQ's rates, or any other cost category."
    )
    disclaimer: str = (
        "Cost rates, when BOQ-sourced, start from HISTORICAL prices from "
        "whenever the source BOQ was priced. An inflation adjustment is "
        "applied ONLY when the BOQ's pricing year is known -- see each line "
        "item's inflation_adjustment for whether one was applied and why. "
        "Even when applied, this is an LLM-reasoned estimate of cost trends, "
        "not real market index data. Treat all cost figures as rough "
        "order-of-magnitude, not a quote-ready estimate."
    )


def _get_priced_year(rate_source: str | None) -> int | None:
    if rate_source is None or rate_source == "own_boq":
        return None
    metadata = reference_store.get_metadata(rate_source)
    if metadata is None:
        return None
    return metadata.get("priced_year")


def estimate_cost(project: ProjectSchema, carbon_result: CalculationResult) -> CostEstimate:
    gfa = carbon_result.gfa_sqm
    derived = project.__dict__.get("_derived", {}) or {}

    # --- Pass 1: figure out each item's base rate, provenance, and
    # (if BOQ-sourced) which pricing-year group it belongs to. Materials
    # with a known priced_year get grouped together so they can be
    # adjusted in a single batched LLM call per group, rather than one
    # call per material. ---
    items_info = []  # list of dicts, one per carbon_result.breakdown item that has a recognized unit
    groups: dict[int, list[str]] = defaultdict(list)  # priced_year -> list of material labels in that group

    for item in carbon_result.breakdown:
        if item.quantity_unit == "m3":
            base_rate = derived.get("concrete_cost_per_m3")
            rate_source = derived.get("concrete_cost_source")
            material_label = "concrete"
            rate_unit = "INR/m3"
        elif item.quantity_unit == "kg":
            base_rate = derived.get("steel_cost_per_kg")
            rate_source = derived.get("steel_cost_source")
            material_label = "reinforcement steel"
            rate_unit = "INR/kg"
        else:
            continue

        if base_rate is not None:
            provenance = "own-boq-extracted" if rate_source == "own_boq" else f"boq-sourced ({rate_source})"
            priced_year = _get_priced_year(rate_source)
        else:
            base_rate = FALLBACK_CONCRETE_COST_PER_M3 if item.quantity_unit == "m3" else FALLBACK_STEEL_COST_PER_KG
            provenance = "fallback-placeholder (unsourced)"
            priced_year = None

        items_info.append(
            {
                "item": item,
                "material_label": material_label,
                "base_rate": base_rate,
                "rate_unit": rate_unit,
                "provenance": provenance,
                "priced_year": priced_year,
            }
        )
        if priced_year is not None:
            groups[priced_year].append(material_label)

    # --- Pass 2: one batched adjustment call per distinct priced_year
    # group. Materials with no priced_year (unsourced fallback, or
    # own-BOQ with no reference metadata) get a no-op adjustment without
    # any LLM call at all. ---
    adjustments_by_material: dict[str, InflationAdjustment] = {}
    for priced_year, materials_in_group in groups.items():
        adjustments_by_material.update(get_inflation_adjustments(materials_in_group, priced_year))

    # --- Pass 3: assemble the final breakdown ---
    breakdown: list[CostBreakdown] = []
    for info in items_info:
        material_label = info["material_label"]
        base_rate = info["base_rate"]

        if info["priced_year"] is not None and material_label in adjustments_by_material:
            adjustment = adjustments_by_material[material_label]
        else:
            adjustment = InflationAdjustment(
                multiplier=1.0,
                priced_year=info["priced_year"],
                current_year=datetime.now().year,
                cumulative_pct_increase=0.0,
                reasoning=(
                    "No BOQ-sourced rate available -- using unsourced placeholder, no adjustment applicable."
                    if info["provenance"] == "fallback-placeholder (unsourced)"
                    else "Pricing year unknown for this rate's source -- no adjustment applied."
                ),
                applied=False,
            )

        rate_used = base_rate * adjustment.multiplier
        cost_inr = info["item"].quantity * rate_used

        breakdown.append(
            CostBreakdown(
                material=info["item"].material,
                quantity=info["item"].quantity,
                quantity_unit=info["item"].quantity_unit,
                base_rate=base_rate,
                rate_used=rate_used,
                rate_unit=info["rate_unit"],
                rate_provenance=info["provenance"],
                inflation_adjustment=adjustment,
                cost_inr=cost_inr,
            )
        )

    total_cost = sum(b.cost_inr for b in breakdown)

    return CostEstimate(
        project_id=project.project_id,
        gfa_sqm=gfa,
        breakdown=breakdown,
        total_cost_inr=total_cost,
        cost_per_sqm_inr=total_cost / gfa if gfa else 0.0,
    )