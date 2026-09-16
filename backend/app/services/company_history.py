"""Workstream 06: a company's own historical project ranges, computed
from its registered reference projects -- the second half of "Phase 1
learns from Phase 2 history" (the first half is ranked GFA-closeness
matching in reference_store.find_candidates / boq_match.py; this module
is what feeds llm_fallback.py's prompt so an LLM-estimated tier field is
grounded in what THIS company has actually built, not a generic
Indian-construction default).

Deliberately reads app.services.reference_store.list_references()
rather than find_candidates() -- this wants every reference project a
company has on file for typology/structural-system/GFA context, not
just the subset that happens to have a cached quantity extraction (a
Work-Order-sourced reference registered via Workstream 06's
auto-registration in app/api/wo_carbon.py has real GFA/typology/
structural-system metadata but, deliberately, no cached extraction --
see that endpoint's own docstring for why -- so it should still count
here even though it can't contribute a steel/concrete ratio).

Numeric ranges (steel_reinforcement_ratio_kg_per_sqm,
concrete_vol_per_sqm) are computed independently from boq_match.py's own
per-request selected-reference calculation, using the same unit-
conversion logic (MT -> kg via *1000) but aggregated across EVERY
reference with a usable extraction, not just the one GFA-nearest match --
these two call sites answer different questions (boq_match.py: "what
should THIS new project's default be, from its single best match" vs.
this module: "what range has this company's history actually shown,
for grounding an LLM prompt") and are kept separate on purpose rather
than sharing a return value that would have to serve both.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from app.services import boq_cache, company_store, reference_store


def _steel_kg_per_sqm(materials: dict, gfa_sqm: float) -> Optional[float]:
    steel_det = materials.get("reinforcement_steel", {}).get("deterministic")
    if not steel_det or not gfa_sqm:
        return None
    unit = (steel_det.get("unit") or "").lower()
    qty = steel_det.get("quantity", 0)
    steel_kg_total = qty * 1000 if unit == "mt" else qty
    return steel_kg_total / gfa_sqm


def _concrete_m3_per_sqm(materials: dict, gfa_sqm: float) -> Optional[float]:
    rcc_det = materials.get("rcc", {}).get("deterministic")
    if not rcc_det or not rcc_det.get("quantity") or not gfa_sqm:
        return None
    return rcc_det["quantity"] / gfa_sqm


def _range_summary(values: list[float]) -> Optional[dict]:
    if not values:
        return None
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(sum(values) / len(values), 2),
        "n": len(values),
    }


def historical_ranges(company_id: str = company_store.DEFAULT_COMPANY_ID) -> dict:
    """Returns a JSON-safe summary of this company's own reference-project
    history:

      n_reference_projects: how many reference projects this company has
        on file at all (metadata only, regardless of extraction).
      typology_counts / structural_system_type_counts: frequency, so a
        prompt can say "this company has built N typology X projects"
        rather than assuming.
      gfa_sqm_range: min/max/avg/n across every reference with a known
        GFA.
      steel_reinforcement_ratio_kg_per_sqm / concrete_vol_per_sqm: min/
        max/avg/n across references that ALSO have a cached quantity
        extraction (see module docstring on why this is a strict subset
        of n_reference_projects).

    Returns all-empty/zero values (never raises) for a brand-new company
    with no reference projects yet -- llm_fallback.py's prompt builder
    is responsible for omitting the company-history section entirely
    when n_reference_projects is 0, not this function.
    """
    references = reference_store.list_references(company_id=company_id)

    typology_counts = Counter(r["typology"] for r in references if r["typology"])
    structural_counts = Counter(r["structural_system_type"] for r in references if r["structural_system_type"])
    gfa_values = [r["gfa_sqm"] for r in references if r["gfa_sqm"]]

    steel_ratios: list[float] = []
    concrete_ratios: list[float] = []
    for r in references:
        if not r["has_extraction"] or not r["gfa_sqm"]:
            continue
        extraction = boq_cache.load_extraction(r["slug"], company_id=company_id)
        if not extraction:
            continue
        materials = extraction.get("materials", {})
        steel = _steel_kg_per_sqm(materials, r["gfa_sqm"])
        if steel is not None:
            steel_ratios.append(steel)
        concrete = _concrete_m3_per_sqm(materials, r["gfa_sqm"])
        if concrete is not None:
            concrete_ratios.append(concrete)

    return {
        "company_id": company_id,
        "n_reference_projects": len(references),
        "typology_counts": dict(typology_counts),
        "structural_system_type_counts": dict(structural_counts),
        "gfa_sqm_range": _range_summary(gfa_values),
        "steel_reinforcement_ratio_kg_per_sqm": _range_summary(steel_ratios),
        "concrete_vol_per_sqm": _range_summary(concrete_ratios),
    }