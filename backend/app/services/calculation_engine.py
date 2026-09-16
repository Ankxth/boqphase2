"""Deterministic embodied carbon calculation engine.

Now uses IFC India data as the primary emission factor source (via
ice_factors.py), with CEA grid-factor adjustment applied (via
cea_adjustment.py), falling back to unadjusted ICE M-grade factors when
cement_type isn't available. Scope is still concrete + steel only --
cement/mortar, bricks, glass, insulation, paint, and MEP are not yet
included.

Workstream 08: calculate_embodied_carbon() gained an optional
`steel_factor_override_kgco2e_per_kg` parameter so a caller can recompute
against a specific supplier's own already-sourced per-kg GWP figure (e.g.
an EPD-verified low-carbon rebar product from the shared
app/services/supplier_catalog.py) instead of the default CEA-adjusted
IFC anchor -- same reasoning app/services/boq_carbon/substitution_engine.py
already established for its own fixed-factor substitutions: a supplier's
own declared, verified figure already reflects their real electricity
mix, so CEA (which exists to scale a generic anchor to a project's LOCAL
grid) is deliberately NOT applied on top of it. Defaults to None, which
reproduces the exact pre-Workstream-08 default-anchor behavior -- every
existing caller that doesn't pass this argument is unaffected.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from app.schemas.project_schema import CementType, ProjectSchema
from app.services.ice_factors import get_concrete_factor_per_m3, get_steel_rebar_factor_per_kg

SQM_TO_SQFT = 10.7639

# Used only when no BOQ-derived concrete volume ratio is available
# (i.e. no reference BOQ has GFA filled in yet, no structural-system
# match, and no own-BOQ refinement has run) -- a generic placeholder for
# RCC-framed residential/commercial construction. NOT derived from real
# reference projects -- replace with a BOQ-derived ratio as soon as one
# is available.
FALLBACK_CONCRETE_VOL_PER_SQM = 0.45  # m3 concrete per sqm GFA

# Used only when steel_reinforcement_ratio_kg_per_sqm is still unset
# after BOQ matching AND LLM fallback (shouldn't normally happen, but
# kept as a last-resort safety net).
FALLBACK_STEEL_RATIO_KG_PER_SQM = 65.0


class MaterialBreakdown(BaseModel):
    material: str
    quantity: float
    quantity_unit: str
    factor_used: float
    factor_unit: str
    factor_source: str  # "ifc_india" | "ice_fallback"
    carbon_kg: float
    quantity_source: str  # "boq-matched" | "own-boq-extracted" | "llm-estimated" | "user-entered" | "fallback-default"


class CalculationResult(BaseModel):
    project_id: str
    gfa_sqm: float
    breakdown: list[MaterialBreakdown]
    total_carbon_kg: float
    total_carbon_tonnes: float
    carbon_per_sqm: float
    carbon_per_sqft: float
    scope_note: str = (
        "Concrete + steel only. Does not yet include cement/mortar, "
        "bricks, glass, insulation, paint, or MEP. Concrete/steel factors "
        "use IFC India data (CEA-adjusted) where cement_type is known, "
        "falling back to unadjusted ICE M-grade factors otherwise."
    )


def calculate_embodied_carbon(
    project: ProjectSchema,
    steel_factor_override_kgco2e_per_kg: Optional[float] = None,
    steel_factor_override_label: Optional[str] = None,
) -> CalculationResult:
    gfa = project.mandatory.gfa_sqm.value
    if gfa is None or gfa <= 0:
        raise ValueError("Cannot calculate without a valid GFA")

    breakdown: list[MaterialBreakdown] = []

    # --- Concrete ---
    cement_type_field = project.tier3.cement_type
    raw_cement_value = cement_type_field.value
    # raw_cement_value may be a real CementType enum member (e.g. set via
    # a properly-typed API request) or a plain string (e.g. written by
    # llm_fallback.py, which assigns an untyped FieldValue and so bypasses
    # Pydantic's enum coercion -- validate_assignment is not enabled on
    # this schema). Handle both shapes rather than assuming one.
    if isinstance(raw_cement_value, CementType):
        cement_type = raw_cement_value.value
    elif raw_cement_value is not None:
        cement_type = str(raw_cement_value).upper()
    else:
        cement_type = None
    grade_field = project.tier3.concrete_grade_mix
    grade = grade_field.value

    if cement_type is None and grade is None:
        grade = "M30"  # last-resort default so calculation can still proceed
        grade_provenance = "fallback-default"
    else:
        grade_provenance = grade_field.source if grade_field.source != "unset" else "fallback-default"
    cement_provenance = cement_type_field.source if cement_type_field.source != "unset" else "fallback-default"

    concrete_factor_per_m3, factor_source = get_concrete_factor_per_m3(
        cement_type=cement_type, grade=grade, apply_cea=True
    )

    derived = getattr(project, "_derived", {}) or {}
    concrete_vol_per_sqm = derived.get("concrete_vol_per_sqm")
    vol_source = derived.get("matched_reference")
    if concrete_vol_per_sqm is None:
        concrete_vol_per_sqm = FALLBACK_CONCRETE_VOL_PER_SQM
        vol_source = "fallback-default"
    elif vol_source == "own_boq":
        vol_source = "own-boq-extracted"
    else:
        vol_source = "boq-matched"

    concrete_vol_m3 = gfa * concrete_vol_per_sqm
    concrete_carbon_kg = concrete_vol_m3 * concrete_factor_per_m3

    material_label = f"Concrete ({cement_type or grade}, {factor_source})"
    breakdown.append(
        MaterialBreakdown(
            material=material_label,
            quantity=concrete_vol_m3,
            quantity_unit="m3",
            factor_used=concrete_factor_per_m3,
            factor_unit="kgCO2e/m3",
            factor_source=factor_source,
            carbon_kg=concrete_carbon_kg,
            quantity_source=f"cement_type:{cement_provenance}, grade:{grade_provenance}, volume:{vol_source}",
        )
    )

    # --- Steel ---
    steel_field = project.tier3.steel_reinforcement_ratio_kg_per_sqm
    steel_ratio = steel_field.value
    steel_source = steel_field.source
    if steel_ratio is None:
        steel_ratio = FALLBACK_STEEL_RATIO_KG_PER_SQM
        steel_source = "fallback-default"

    steel_kg = gfa * steel_ratio
    if steel_factor_override_kgco2e_per_kg is not None:
        # A specific, already-sourced supplier figure (see module
        # docstring) -- used as-is, no CEA adjustment layered on top.
        steel_factor_per_kg = steel_factor_override_kgco2e_per_kg
        steel_factor_source = "supplier_epd_fixed"
        material_label = "Reinforcement steel (rebar)" + (
            f" -- {steel_factor_override_label}" if steel_factor_override_label else " -- supplier override"
        )
    else:
        steel_factor_per_kg, steel_factor_source = get_steel_rebar_factor_per_kg(apply_cea=True)
        material_label = "Reinforcement steel (rebar)"
    steel_carbon_kg = steel_kg * steel_factor_per_kg

    breakdown.append(
        MaterialBreakdown(
            material=material_label,
            quantity=steel_kg,
            quantity_unit="kg",
            factor_used=steel_factor_per_kg,
            factor_unit="kgCO2e/kg",
            factor_source=steel_factor_source,
            carbon_kg=steel_carbon_kg,
            quantity_source=steel_source,
        )
    )

    total_carbon_kg = sum(item.carbon_kg for item in breakdown)

    return CalculationResult(
        project_id=project.project_id,
        gfa_sqm=gfa,
        breakdown=breakdown,
        total_carbon_kg=total_carbon_kg,
        total_carbon_tonnes=total_carbon_kg / 1000,
        carbon_per_sqm=total_carbon_kg / gfa,
        carbon_per_sqft=total_carbon_kg / gfa / SQM_TO_SQFT,
    )