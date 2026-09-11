"""Refines an existing project's schema using its OWN BOQ, once one
becomes available later in the design process (Phase C). Now also
derives real cost rates from the project's own BOQ, same mechanism as
boq_match.py -- these take priority over reference-project cost rates,
same logic as why own-boq-extracted outranks boq-matched for quantities.

Unlike boq_match.py, which borrows ratios from a reference project, this
uses the project's OWN already-known GFA as the denominator directly.

Fields refined this way get source="own-boq-extracted", confidence 0.9.

Plausibility check: real extracted data isn't clamped the way an LLM
guess is -- an extracted number is real, not a guess, so silently
correcting it would hide a genuine problem rather than flag one. A
wildly implausible result is checked against a plausible range and a
warning is printed, never silently accepted or altered.

Known gap, stated plainly: this module only builds the refinement LOGIC.
Wiring it into an API endpoint requires project persistence, which does
not exist yet in this codebase.
"""

from __future__ import annotations

from app.schemas.project_schema import FieldValue, ProjectSchema
from app.services.boq_extractor import extract_boq

OWN_BOQ_CONFIDENCE = 0.9  # higher than boq-matched (0.6) -- this is the project's own real data, not a borrowed proxy

# Same plausible range used in llm_fallback.py's clamping -- here it's a
# warning threshold, not a clamp, since this is real extracted data, not
# a guess to correct.
PLAUSIBLE_STEEL_RATIO_RANGE = (50, 130)  # kg/sqm


def refine_project_with_boq(
    project: ProjectSchema, boq_file_path: str, use_llm_fallback: bool = True
) -> ProjectSchema:
    """Extracts quantities AND cost from the project's own BOQ and
    OVERWRITES Tier 3 fields (steel ratio, concrete volume, cost rates)
    with source="own-boq-extracted" -- regardless of what was there
    before, since the project's own real data supersedes any earlier
    proxy or guess.

    Requires project.mandatory.gfa_sqm to already be set.

    Does NOT set concrete_grade_mix -- same limitation as boq_match.py.
    """
    gfa = project.mandatory.gfa_sqm.value
    if gfa is None or gfa <= 0:
        raise ValueError("Cannot refine with BOQ data without a valid project GFA")

    extraction = extract_boq(boq_file_path, use_llm_fallback=use_llm_fallback)
    materials = extraction.get("materials", {})
    derived = project.__dict__.setdefault("_derived", {})

    # --- Steel ---
    steel = materials.get("reinforcement_steel", {})
    steel_det = steel.get("deterministic")
    if steel_det and steel_det.get("quantity"):
        unit = (steel_det.get("unit") or "").lower()
        qty = steel_det.get("quantity", 0)
        steel_kg_total = qty * 1000 if unit == "mt" else qty
        steel_per_sqm = steel_kg_total / gfa

        lo, hi = PLAUSIBLE_STEEL_RATIO_RANGE
        if not (lo <= steel_per_sqm <= hi):
            print(
                f"[project_boq_refinement] WARNING: extracted steel ratio "
                f"{steel_per_sqm:.2f} kg/sqm is outside the plausible range "
                f"({lo}-{hi}). NOT clamped or altered -- this is real extracted "
                f"data, so the value is kept as-is, but this is worth checking: "
                f"confirm the project's GFA and the uploaded BOQ actually belong "
                f"to the same building before trusting this number."
            )

        project.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(
            value=round(steel_per_sqm, 2),
            source="own-boq-extracted",
            confidence=OWN_BOQ_CONFIDENCE,
        )

        if steel_det.get("cost_total") and steel_kg_total:
            derived["steel_cost_per_kg"] = steel_det["cost_total"] / steel_kg_total
            derived["steel_cost_source"] = "own_boq"

    # --- Concrete: RCC volume per sqm ---
    rcc = materials.get("rcc", {})
    rcc_det = rcc.get("deterministic")
    if rcc_det and rcc_det.get("quantity"):
        concrete_vol_per_sqm = rcc_det["quantity"] / gfa
        derived["concrete_vol_per_sqm"] = concrete_vol_per_sqm
        derived["matched_reference"] = "own_boq"

        if rcc_det.get("cost_total"):
            derived["concrete_cost_per_m3"] = rcc_det["cost_total"] / rcc_det["quantity"]
            derived["concrete_cost_source"] = "own_boq"

    derived["own_boq_extraction_meta"] = {
        "source_file": extraction["source_file"],
        "unclassified_row_count": extraction["unclassified_row_count"],
    }

    return project