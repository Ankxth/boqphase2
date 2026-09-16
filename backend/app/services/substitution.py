"""Material substitution suggestions with real recompute.

Each suggestion is produced by actually building a modified copy of the
project (one field changed) and running it through the same
calculation_embodied_carbon() used everywhere else in the pipeline --
not an estimate of what the saving would be, the real computed number.

Three suggestion types, handled differently on purpose:

1. Cement type swap -- a straightforward, code-comparable substitution.
   If the project isn't already on PPC (the lowest-carbon of the three
   IFC-modeled cement types), suggest switching. No engineering caveat
   needed -- cement type substitution within IS-code-compliant blends is
   a standard specification choice, not a structural safety question.

2. Steel ratio reduction toward the low end of its floor-band's typical
   range -- ALWAYS flagged with an explicit engineering-review
   disclaimer. A carbon calculator has no basis to tell a project it's
   structurally safe to use less steel -- that's an engineer's call,
   informed by actual structural analysis, not a carbon tool's opinion.
   This suggestion is framed as "achievable with optimized design,"
   never as an instruction to simply reduce steel.

3. (Workstream 08) Supplier material swap -- reads the shared
   app/services/supplier_catalog.py for any alternative with its own
   fixed, already-sourced per-kg GWP figure (currently: EPD-verified
   low-carbon reinforcement steel) and recomputes against it via
   calculate_embodied_carbon()'s new steel_factor_override_kgco2e_per_kg
   parameter. This is a genuinely different kind of suggestion from #2
   above -- it changes WHICH PRODUCT is specified, not how much of it is
   used -- so both can be suggested, and applied together, independently.
   ALWAYS flagged for engineering review: reinforcement steel is
   structural by definition, and grade/mechanical-property compatibility
   with the project's design must be confirmed regardless of the
   percentage applied (mirrors the catalog entry's own
   always_requires_review_if_load_bearing flag).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from app.schemas.project_schema import CementType, FieldValue, ProjectSchema
from app.services.calculation_engine import CalculationResult, calculate_embodied_carbon
from app.services.supplier_catalog import list_fixed_factor_alternatives_for_category

# Same floor bands used in benchmark.py and llm_fallback.py's prompt
# guidance -- kept as one source of truth would be better long-term, but
# duplicated here for now since each module currently owns its own copy.
# Revisit if these three constant sets ever need to be consolidated.
STEEL_RATIO_RANGES_BY_BAND = {
    "low_rise": (50.0, 70.0),
    "mid_rise": (70.0, 100.0),
    "high_rise": (100.0, 130.0),
}

CEMENT_CARBON_RANK = [CementType.ppc, CementType.psc, CementType.opc]  # lowest to highest carbon, per IFC data


# Sentinel used as SubstitutionSuggestion.field for the supplier-swap
# suggestion -- it doesn't map onto a real ProjectSchema field (see
# compute_combined_impact's special-case handling below), unlike the
# cement-type and steel-ratio suggestions which mutate a real field.
SUPPLIER_STEEL_FACTOR_PSEUDO_FIELD = "_supplier_steel_factor_override"


class SubstitutionSuggestion(BaseModel):
    field: str
    description: str
    current_value: str
    suggested_value: str
    carbon_kg_before: float
    carbon_kg_after: float
    savings_kg: float
    savings_pct: float
    requires_engineering_review: bool
    reasoning: str
    # Workstream 08, supplier-swap suggestions only (None for the two
    # pre-existing suggestion types): the raw override figure and its
    # catalog identity, carried alongside the display strings above so
    # compute_combined_impact() can re-apply it exactly rather than
    # re-parsing it back out of suggested_value.
    supplier: Optional[str] = None
    evidence_tier: Optional[str] = None
    override_factor_kgco2e_per_kg: Optional[float] = None


def _get_floor_band(num_floors: int | None) -> str:
    if num_floors is None:
        return "mid_rise"
    if num_floors <= 4:
        return "low_rise"
    if num_floors <= 15:
        return "mid_rise"
    return "high_rise"


def _clone_project(project: ProjectSchema) -> ProjectSchema:
    """Deep-copies a project, explicitly carrying over _derived (an
    ad-hoc dict attribute, not a declared Pydantic field, so it isn't
    guaranteed to survive model_copy(deep=True) automatically -- copied
    over explicitly here rather than assuming it does).
    """
    cloned = project.model_copy(deep=True)
    cloned.__dict__["_derived"] = dict(project.__dict__.get("_derived", {}))
    return cloned


def _suggest_cement_swap(
    project: ProjectSchema, actual_result: CalculationResult
) -> SubstitutionSuggestion | None:
    current_field = project.tier3.cement_type
    current_value = current_field.value
    if current_value is None:
        return None  # nothing to suggest against if cement type isn't even known

    current_enum = current_value if isinstance(current_value, CementType) else CementType(str(current_value).upper())

    if current_enum == CEMENT_CARBON_RANK[0]:
        return None  # already on the lowest-carbon option -- no suggestion needed

    suggested_enum = CEMENT_CARBON_RANK[0]  # PPC

    modified = _clone_project(project)
    modified.tier3.cement_type = FieldValue(value=suggested_enum, source="user-entered", confidence=1.0)
    modified_result = calculate_embodied_carbon(modified)

    before = actual_result.total_carbon_kg
    after = modified_result.total_carbon_kg
    savings = before - after
    savings_pct = (savings / before * 100) if before else 0.0

    return SubstitutionSuggestion(
        field="tier3.cement_type",
        description="Switch cement type",
        current_value=current_enum.value,
        suggested_value=suggested_enum.value,
        carbon_kg_before=before,
        carbon_kg_after=after,
        savings_kg=savings,
        savings_pct=round(savings_pct, 2),
        requires_engineering_review=False,
        reasoning=(
            f"{suggested_enum.value} (fly-ash blend) has a lower embodied carbon "
            f"factor than {current_enum.value} per IFC's India-specific material "
            f"data, and is a standard IS-code-compliant specification choice for "
            f"typical structural use -- not a structural safety change."
        ),
    )


def _suggest_steel_reduction(
    project: ProjectSchema, actual_result: CalculationResult
) -> SubstitutionSuggestion | None:
    current_field = project.tier3.steel_reinforcement_ratio_kg_per_sqm
    current_ratio = current_field.value
    if current_ratio is None:
        return None

    floor_band = _get_floor_band(project.tier2.num_floors.value)
    low_end, high_end = STEEL_RATIO_RANGES_BY_BAND[floor_band]

    if current_ratio <= low_end:
        return None  # already at or below the typical low end -- no suggestion needed

    modified = _clone_project(project)
    modified.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(
        value=low_end, source="user-entered", confidence=1.0
    )
    modified_result = calculate_embodied_carbon(modified)

    before = actual_result.total_carbon_kg
    after = modified_result.total_carbon_kg
    savings = before - after
    savings_pct = (savings / before * 100) if before else 0.0

    return SubstitutionSuggestion(
        field="tier3.steel_reinforcement_ratio_kg_per_sqm",
        description="Optimize steel reinforcement ratio",
        current_value=f"{current_ratio:.1f} kg/sqm",
        suggested_value=f"{low_end:.1f} kg/sqm",
        carbon_kg_before=before,
        carbon_kg_after=after,
        savings_kg=savings,
        savings_pct=round(savings_pct, 2),
        requires_engineering_review=True,
        reasoning=(
            f"Current ratio is above the low end of the typical range for a "
            f"{floor_band.replace('_', '-')} building ({low_end:.0f}-{high_end:.0f} "
            f"kg/sqm). Buildings of this height and type have achieved ratios "
            f"toward the lower end of this range through optimized structural "
            f"design -- but this requires verification by a structural engineer "
            f"against the actual design and loading conditions. This is NOT a "
            f"recommendation to simply reduce reinforcement."
        ),
    )


def _current_steel_factor_per_kg(actual_result: CalculationResult) -> Optional[float]:
    """Pulls the effective CEA-adjusted steel factor actual_result was
    already computed with, straight off its own breakdown -- avoids a
    second, possibly-inconsistent call to get_steel_rebar_factor_per_kg()
    just to find out what "current" means for this comparison."""
    for item in actual_result.breakdown:
        if item.material.startswith("Reinforcement steel"):
            return item.factor_used
    return None


def _suggest_supplier_steel_swap(
    project: ProjectSchema, actual_result: CalculationResult
) -> list[SubstitutionSuggestion]:
    """Workstream 08: one suggestion per catalog alternative in
    app/services/supplier_catalog.py that (a) applies to
    reinforcement_steel and (b) carries its own fixed, already-sourced
    per-kg GWP figure -- currently just the ARS 550D EPD-verified entry,
    but written to pick up any future fixed-factor steel entry the
    catalog gains without code changes here.

    Returns a list (not Optional[single]) since more than one verified
    low-carbon supplier could plausibly be in the catalog at once, unlike
    the single cement-swap/steel-ratio suggestions above.
    """
    if project.tier3.steel_reinforcement_ratio_kg_per_sqm.value is None:
        return []  # nothing to swap the factor of if there's no steel quantity basis at all

    current_factor = _current_steel_factor_per_kg(actual_result)
    if current_factor is None:
        return []

    out: list[SubstitutionSuggestion] = []
    for alt in list_fixed_factor_alternatives_for_category("reinforcement_steel"):
        if alt.fixed_gwp_kgco2e_per_kg is None or alt.fixed_gwp_kgco2e_per_kg >= current_factor:
            continue  # not an actual carbon improvement over the project's current effective factor -- don't suggest it

        modified = _clone_project(project)
        modified_result = calculate_embodied_carbon(
            modified,
            steel_factor_override_kgco2e_per_kg=alt.fixed_gwp_kgco2e_per_kg,
            steel_factor_override_label=alt.product_name,
        )

        before = actual_result.total_carbon_kg
        after = modified_result.total_carbon_kg
        savings = before - after
        savings_pct = (savings / before * 100) if before else 0.0

        out.append(
            SubstitutionSuggestion(
                field=SUPPLIER_STEEL_FACTOR_PSEUDO_FIELD,
                description=f"Switch reinforcement steel supplier to {alt.product_name}",
                current_value=f"{current_factor:.3f} kgCO2e/kg (IFC India, CEA-adjusted)",
                suggested_value=f"{alt.fixed_gwp_kgco2e_per_kg:.3f} kgCO2e/kg ({alt.product_name})",
                carbon_kg_before=before,
                carbon_kg_after=after,
                savings_kg=savings,
                savings_pct=round(savings_pct, 2),
                requires_engineering_review=True,  # reinforcement steel is structural by definition -- always
                reasoning=alt.reasoning + " " + alt.structural_caveat,
                supplier=alt.supplier,
                evidence_tier=alt.evidence_tier,
                override_factor_kgco2e_per_kg=alt.fixed_gwp_kgco2e_per_kg,
            )
        )
    return out


def suggest_substitutions(
    project: ProjectSchema, actual_result: CalculationResult
) -> list[SubstitutionSuggestion]:
    """Returns whatever substitution suggestions apply to this project --
    zero or more, depending on current material choices and what the
    shared supplier catalog currently has sourced. Each suggestion's
    savings figures come from a real recompute, not an estimate.
    """
    suggestions = []

    cement_suggestion = _suggest_cement_swap(project, actual_result)
    if cement_suggestion:
        suggestions.append(cement_suggestion)

    steel_suggestion = _suggest_steel_reduction(project, actual_result)
    if steel_suggestion:
        suggestions.append(steel_suggestion)

    suggestions.extend(_suggest_supplier_steel_swap(project, actual_result))

    return suggestions


class CombinedSubstitutionImpact(BaseModel):
    carbon_kg_before: float
    carbon_kg_after_all_applied: float
    total_savings_kg: float
    total_savings_pct: float
    requires_engineering_review: bool
    applied_suggestions: list[str]  # descriptions of what was applied


def compute_combined_impact(
    project: ProjectSchema, actual_result: CalculationResult, suggestions: list[SubstitutionSuggestion]
) -> CombinedSubstitutionImpact | None:
    """Applies ALL given suggestions together in a single cloned project
    and recomputes once, rather than summing each suggestion's
    individually-computed savings_kg.

    This matters here specifically because it's SAFE to sum in this
    pipeline's current scope -- concrete (cement type), steel quantity
    (reinforcement ratio), and now (Workstream 08) steel's own per-kg
    factor (supplier swap) are independent multiplicative terms in
    calculation_engine.py (steel_carbon = steel_kg * steel_factor_per_kg,
    with the ratio suggestion changing steel_kg and the supplier-swap
    suggestion changing steel_factor_per_kg -- two different factors in
    the same product, not two competing values for the same one), so
    applying all of them together and applying each separately then
    summing produce the same total. But that independence is a property
    of the current suggestion scope, not a general guarantee -- if a
    future suggestion type interacts with another (e.g. a facade change
    that also affects structural steel demand), summing individual
    savings would silently become wrong while this function's "clone
    once, apply all, recompute" approach would still be correct. Built
    this way now so it doesn't need revisiting later purely because more
    suggestion types get added.

    Returns None if there are no suggestions to combine.
    """
    if not suggestions:
        return None

    combined = _clone_project(project)
    requires_review = False
    steel_factor_override: float | None = None
    steel_factor_override_label: str | None = None

    for suggestion in suggestions:
        if suggestion.field == SUPPLIER_STEEL_FACTOR_PSEUDO_FIELD:
            # Doesn't map onto a real ProjectSchema field -- carried
            # forward as a recompute parameter instead of a setattr,
            # applied in the single combined calculate_embodied_carbon()
            # call below alongside whatever else was suggested (e.g. a
            # steel-ratio reduction: quantity and per-kg factor are
            # still independent multiplicative terms, so applying both
            # together is exactly as safe as this function's docstring
            # already establishes for cement-type + steel-ratio).
            steel_factor_override = suggestion.override_factor_kgco2e_per_kg
            steel_factor_override_label = suggestion.suggested_value
            if suggestion.requires_engineering_review:
                requires_review = True
            continue

        block_name, field_name = suggestion.field.split(".")
        block = getattr(combined, block_name)
        current_field = getattr(block, field_name)

        # Re-derive the target value from the suggestion's own
        # suggested_value string, matching the type the field expects.
        if field_name == "cement_type":
            target_value = CementType(suggestion.suggested_value)
        elif field_name == "steel_reinforcement_ratio_kg_per_sqm":
            target_value = float(suggestion.suggested_value.split()[0])
        else:
            continue  # unrecognized field -- skip rather than guess how to apply it

        setattr(block, field_name, FieldValue(value=target_value, source="user-entered", confidence=1.0))
        if suggestion.requires_engineering_review:
            requires_review = True

    combined_result = calculate_embodied_carbon(
        combined,
        steel_factor_override_kgco2e_per_kg=steel_factor_override,
        steel_factor_override_label=steel_factor_override_label,
    )

    before = actual_result.total_carbon_kg
    after = combined_result.total_carbon_kg
    savings = before - after
    savings_pct = (savings / before * 100) if before else 0.0

    return CombinedSubstitutionImpact(
        carbon_kg_before=before,
        carbon_kg_after_all_applied=after,
        total_savings_kg=savings,
        total_savings_pct=round(savings_pct, 2),
        requires_engineering_review=requires_review,
        applied_suggestions=[s.description for s in suggestions],
    )