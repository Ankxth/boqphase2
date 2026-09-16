"""Matches a project's mandatory fields against extracted reference BOQ
data to derive Tier 3 defaults, scaled by GFA -- now also derives real
BOQ-sourced cost rates (INR per m3 concrete, INR per kg steel) for
cost_estimation.py to use, alongside the existing carbon-relevant ratios.

Goes through app.services.reference_store rather than touching
reference_stats.json or boq_cache.py directly.

Workstream 04: matches against project.company_id's own reference
projects only, never another company's -- see reference_store.py's
docstring.

Workstream 06: reference_store.find_candidates() now ranks by GFA
closeness when given the project's own target GFA, replacing the old
"v1: first match wins" behavior (whichever reference happened to be
first in an arbitrary list) with a genuine nearest-size match -- the
gap reference_store.py's own prior docstring already flagged as the
intended next step. This module's only change is passing its own
project's gfa through as target_gfa_sqm; the "take candidates[0]" line
below is unchanged, but what candidates[0] now MEANS has changed.
"""

from __future__ import annotations

from app.schemas.project_schema import FieldValue, ProjectSchema
from app.services import boq_cache, reference_store


def match_boq_defaults(project: ProjectSchema) -> ProjectSchema:
    gfa = project.mandatory.gfa_sqm.value
    if gfa is None or gfa <= 0:
        return project

    system_type = project.mandatory.structural_system_type.value
    system_type_str = system_type.value if system_type else None

    candidates = reference_store.find_candidates(
        structural_system_type=system_type_str, target_gfa_sqm=gfa, company_id=project.company_id
    )
    if not candidates:
        return project

    # Workstream 06: candidates are now ranked by GFA closeness (see
    # find_candidates), so this is a genuine nearest-size match, not an
    # arbitrary first-in-list pick.
    selected = candidates[0]
    slug = selected["slug"]
    ref_gfa = selected["gfa_sqm"]
    extraction = boq_cache.load_extraction(slug, company_id=project.company_id)
    materials = extraction.get("materials", {}) if extraction else {}

    derived = project.__dict__.setdefault("_derived", {})

    # --- Steel ---
    steel = materials.get("reinforcement_steel", {})
    steel_det = steel.get("deterministic")
    steel_kg_total = None
    if steel_det:
        unit = (steel_det.get("unit") or "").lower()
        qty = steel_det.get("quantity", 0)
        steel_kg_total = qty * 1000 if unit == "mt" else qty

        if project.tier3.steel_reinforcement_ratio_kg_per_sqm.source == "unset":
            steel_per_sqm = steel_kg_total / ref_gfa
            project.tier3.steel_reinforcement_ratio_kg_per_sqm = FieldValue(
                value=round(steel_per_sqm, 2),
                source="boq-matched",
                confidence=0.6,
            )

        # Steel cost rate (INR/kg) -- real BOQ-sourced rate, if the source
        # sheet had an Amount column. cost_total is in whatever currency
        # the source BOQ used (assumed INR).
        if steel_det.get("cost_total") and steel_kg_total:
            derived["steel_cost_per_kg"] = steel_det["cost_total"] / steel_kg_total
            derived["steel_cost_source"] = slug

    # --- Concrete: RCC only (structural), not PCC (blinding/leveling) ---
    rcc = materials.get("rcc", {})
    rcc_det = rcc.get("deterministic")
    if rcc_det and rcc_det.get("quantity"):
        concrete_vol_per_sqm = rcc_det["quantity"] / ref_gfa
        derived["concrete_vol_per_sqm"] = concrete_vol_per_sqm
        derived["matched_reference"] = slug

        # Concrete cost rate (INR/m3) -- real BOQ-sourced rate.
        if rcc_det.get("cost_total"):
            derived["concrete_cost_per_m3"] = rcc_det["cost_total"] / rcc_det["quantity"]
            derived["concrete_cost_source"] = slug

    return project