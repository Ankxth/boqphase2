"""Phase 2 calculation engine: raw BOQ file -> embodied carbon (GWP100,
kg CO2e), using the format-agnostic parser (parser.py), the keyword
classifier (classifier.py), and two factor sources -- app.services.ice_factors
/ cea_adjustment (concrete + reinforcement steel, the same real
CEA-adjusted IFC data Phase 1 uses) and extra_factors.py (every other
category, placeholder-quality, see that module's docstring).

Floor area handling -- read this before trusting a kgCO2e/m2 figure:

Comparing this pipeline's real BOQ-derived totals against real EDGE
certification report numbers (two actual projects) showed the single
largest source of a "wrong-looking" per-sqm figure was DIVIDING BY THE
WRONG AREA, not a factor-accuracy problem. One project's declared
"Gross Internal Area" turned out to be just its apartments' net area
(272 units summed), excluding a large basement/podium/parking structure
that the BOQ (correctly) prices concrete and steel for -- an 8.5x gap
between that declared area and the project's true built-up area.
Because of this, calculate_from_boq() takes floor_area_basis as a
REQUIRED, explicit field alongside floor_area_sqm (not just a bare
number) and stamps it onto the result, so nobody downstream can read a
"kg CO2e/m2" figure without also seeing what it was divided by.

Scope, stated plainly: only line items the classifier recognizes AND
whose unit is one this engine knows how to convert contribute to the
total. Everything else is tracked in unclassified_line_items /
unconverted_line_items rather than silently dropped -- so the coverage
gap is always visible on the result, never hidden inside a single
"total" number.

compute_line_gwp() (previously a module-private _compute_line_gwp) is
now also imported directly by substitution_engine.py, which needs to
recompute a line's GWP under an ALTERNATE cement_type/category to
produce a real substitution delta rather than an estimated one -- see
that module's docstring.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

from app.services.boq_carbon.classifier import (
    CATEGORY_ALUMINIUM,
    CATEGORY_BLOCK,
    CATEGORY_BRICK,
    CATEGORY_GLASS,
    CATEGORY_PAINT,
    CATEGORY_PCC,
    CATEGORY_PLASTER,
    CATEGORY_RCC,
    CATEGORY_STEEL_REBAR,
    CATEGORY_STEEL_SECTION,
    CATEGORY_TILE,
    CATEGORY_TIMBER,
    classify_material,
)
from app.services.boq_carbon.extra_factors import get_factor
from app.services.boq_carbon.parser import extract_billable_items
from app.services.ice_factors import get_concrete_factor_per_m3, get_steel_rebar_factor_per_kg

SQM_TO_SQFT = 10.7639

_VOL_UNITS = re.compile(r"^(cum|cu\.?m|m3|m\^3)$", re.I)
_AREA_UNITS = re.compile(r"^(sqm|sq\.?m|m2|m\^2)$", re.I)
_MASS_KG_UNITS = re.compile(r"^(kg|kgs)$", re.I)
_MASS_MT_UNITS = re.compile(r"^(mt|ton|tonne|tonnes|t)$", re.I)
# Linear/running-length units -- added for tile skirting/coping items
# (e.g. "CLAY TILE... skirting... 100mm height", priced in Rmt, not Sqm).
# Confirmed real via diagnose_coverage_gaps.py: these lines were correctly
# classified as 'tile' but silently dropped because the engine only knew
# how to convert Sqm for that category.
_LINEAR_UNITS = re.compile(r"^(rmt|rm|rft|r\.?m\.?t?)$", re.I)
# Count/piece units -- added for timber joinery items. Confirmed real via
# a direct scan of both reference BOQs before adding this category at
# all: every one of Ecopolitan's 75 genuine timber lines (door/window
# frame joinery) is priced in "Nos", none in kg/m3/m2 -- so a count-unit
# conversion path is required for timber to contribute anything, not
# optional the way it was for the mass/area/volume categories.
_COUNT_UNITS = re.compile(r"^(nos\.?|no\.?|each|ea)$", re.I)

CONCRETE_DENSITY_KG_PER_M3 = 2400.0  # matches ice_db_factors.json's own default_density_kg_per_m3

# Assumed skirting/coping height for tile items priced per running metre
# rather than per sqm. 100mm is stated explicitly in the one real example
# checked ("100mm height" note on a clay-tile skirting item) -- standard
# Indian skirting height is commonly 100-150mm, so this is a reasonable,
# evidenced default, not an arbitrary guess, but it IS an assumption
# rather than a per-line-verified figure -- basis_note always says so.
ASSUMED_TILE_SKIRTING_HEIGHT_M = 0.1

FloorAreaBasis = Literal["net_internal_gia", "built_up_total", "carpet_saleable", "other"]

FLOOR_AREA_BASIS_NOTES = {
    "net_internal_gia": (
        "Net internal / Gross Internal Area -- typically the sum of individual "
        "unit areas only (e.g. apartment carpet+wall areas), EXCLUDING common "
        "areas, corridors, basement, podium parking, and terrace/service floors. "
        "Confirmed on a real project to be as little as 1/8.5 of that same "
        "project's true built-up area -- dividing a whole-building carbon total "
        "by this figure will read as a large overestimate versus a report that "
        "uses a narrower area definition, even when the underlying quantities "
        "are correct."
    ),
    "built_up_total": (
        "Total constructed floor area across every level the BOQ actually prices "
        "-- basement, podium/parking, tower floors, terrace, common areas, "
        "everything. This is the area that should be roughly proportional to "
        "the BOQ's own concrete/steel/finishes quantities."
    ),
    "carpet_saleable": (
        "Saleable/carpet area -- usually smaller than net_internal_gia (excludes "
        "wall thickness, balconies counted at reduced weightage, etc.). Rarely "
        "the right denominator for a whole-building carbon total."
    ),
    "other": "Basis not one of the standard categories above -- describe it in a note when reporting this result.",
}


class LineItemResult(BaseModel):
    row: int
    enriched_description: str
    uom: Optional[str]
    qty: Optional[float]
    category: Optional[str]
    cement_type: Optional[str] = None
    grade: Optional[str] = None
    gwp_kg_co2e: Optional[float]
    basis_note: str  # e.g. "12.3 m3 x 227.1 kgCO2e/m3 (PPC, M25)", or the reason it wasn't computed


class CategoryTotal(BaseModel):
    category: str
    gwp_kg_co2e: float
    line_item_count: int
    pct_of_total: float


class BoqCarbonResult(BaseModel):
    source_file: str
    sheet_name: str
    n_lines_total: int
    n_lines_classified: int
    n_lines_computed: int  # classified AND successfully converted to a GWP value
    total_gwp_kg_co2e: float
    total_gwp_tonnes_co2e: float
    by_category: list[CategoryTotal]
    floor_area_sqm: Optional[float] = None
    floor_area_basis: Optional[FloorAreaBasis] = None
    floor_area_basis_note: Optional[str] = None
    gwp_per_sqm: Optional[float] = None
    gwp_per_sqft: Optional[float] = None
    line_items: list[LineItemResult] = []
    scope_note: str = (
        "Covers rcc, pcc, reinforcement_steel, structural_steel, brickwork, "
        "blockwork, plaster, tile, paint, timber, and aluminium_glazing/glass "
        "line items that the classifier recognized AND whose unit this engine "
        "knows how to convert. MEP, sanitary fittings, waterproofing "
        "membranes, and any unrecognized line item are NOT included -- see "
        "n_lines_total vs. n_lines_computed for the coverage gap."
    )
    factor_disclaimer: str = (
        "Concrete (rcc/pcc) and reinforcement steel use the same real, "
        "India-specific, CEA-adjusted IFC factors as the Phase 1 conceptual "
        "estimator (app.services.ice_factors), now grade-differentiated using "
        "ICE v4.1's CEM-I grade curve as a scaling ratio on top of IFC's "
        "cement-type anchor. Every other category (structural steel sections, "
        "brick, block, plaster, tile, paint, aluminium, glass) uses ROUGH "
        "PLACEHOLDER factors -- see extra_factors.py / "
        "boq_carbon_extra_factors.json -- not yet verified line-by-line "
        "against a primary source the way concrete/steel were."
    )


def compute_line_gwp(
    category: Optional[str], cement_type: Optional[str], grade: Optional[str], uom: Optional[str], qty: Optional[float]
) -> tuple[Optional[float], str]:
    if category is None:
        return None, "unclassified"
    if qty is None or qty <= 0:
        return None, "no quantity"
    if uom is None:
        return None, "no unit"

    if category in (CATEGORY_RCC, CATEGORY_PCC):
        if _VOL_UNITS.match(uom):
            per_m3, factor_source = get_concrete_factor_per_m3(cement_type=cement_type, grade=grade, apply_cea=True)
            gwp = qty * per_m3
            return gwp, f"{qty:g} m3 x {per_m3:.1f} kgCO2e/m3 ({cement_type}, {grade}, {factor_source})"
        return None, f"{category} line with non-volume unit '{uom}'"

    if category == CATEGORY_STEEL_REBAR:
        per_kg, factor_source = get_steel_rebar_factor_per_kg(apply_cea=True)
        if _MASS_KG_UNITS.match(uom):
            return qty * per_kg, f"{qty:g} kg x {per_kg:.3f} kgCO2e/kg ({factor_source})"
        if _MASS_MT_UNITS.match(uom):
            return qty * 1000.0 * per_kg, f"{qty:g} MT x 1000 x {per_kg:.3f} kgCO2e/kg ({factor_source})"
        return None, f"reinforcement_steel line with non-mass unit '{uom}'"

    if category == CATEGORY_STEEL_SECTION:
        entry = get_factor("structural_steel")
        per_kg = entry["gwp_kgco2e_per_kg"]
        if _MASS_KG_UNITS.match(uom):
            return qty * per_kg, f"{qty:g} kg x {per_kg} kgCO2e/kg (placeholder)"
        if _MASS_MT_UNITS.match(uom):
            return qty * 1000.0 * per_kg, f"{qty:g} MT x 1000 x {per_kg} kgCO2e/kg (placeholder)"
        return None, f"structural_steel line with non-mass unit '{uom}'"

    if category in (CATEGORY_BRICK, CATEGORY_BLOCK):
        entry = get_factor("aac_block" if category == CATEGORY_BLOCK else "brick_clay")
        per_kg = entry["gwp_kgco2e_per_kg"]
        density = entry["density_kg_per_m3"]
        if _VOL_UNITS.match(uom):
            return qty * density * per_kg, f"{qty:g} m3 x {density} kg/m3 x {per_kg} kgCO2e/kg (placeholder)"
        if _AREA_UNITS.match(uom):
            assumed_thickness_m = 0.2  # standard Indian block/brick wall thickness assumption
            gwp = qty * assumed_thickness_m * density * per_kg
            return gwp, f"{qty:g} m2 x {assumed_thickness_m}m assumed x {density} kg/m3 x {per_kg} kgCO2e/kg (placeholder)"
        return None, f"{category} line with unhandled unit '{uom}'"

    if category == CATEGORY_PLASTER:
        entry = get_factor("cement_plaster")
        per_kg, density, thickness = entry["gwp_kgco2e_per_kg"], entry["density_kg_per_m3"], entry["assumed_thickness_m"]
        if _AREA_UNITS.match(uom):
            return qty * thickness * density * per_kg, f"{qty:g} m2 x {thickness}m x {density} kg/m3 x {per_kg} kgCO2e/kg (placeholder)"
        if _VOL_UNITS.match(uom):
            return qty * density * per_kg, f"{qty:g} m3 x {density} kg/m3 x {per_kg} kgCO2e/kg (placeholder)"
        return None, f"plaster line with unhandled unit '{uom}'"

    if category == CATEGORY_TILE:
        entry = get_factor("ceramic_tile")
        per_kg, areal_mass = entry["gwp_kgco2e_per_kg"], entry["areal_mass_kg_per_m2"]
        if _AREA_UNITS.match(uom):
            return qty * areal_mass * per_kg, f"{qty:g} m2 x {areal_mass} kg/m2 x {per_kg} kgCO2e/kg (placeholder)"
        if _LINEAR_UNITS.match(uom):
            # Skirting/coping priced per running metre -- convert to an
            # equivalent area using an assumed height, then price as area.
            # See ASSUMED_TILE_SKIRTING_HEIGHT_M's comment for the basis.
            h = ASSUMED_TILE_SKIRTING_HEIGHT_M
            gwp = qty * h * areal_mass * per_kg
            return gwp, (
                f"{qty:g} m (linear) x {h}m assumed height x {areal_mass} kg/m2 x "
                f"{per_kg} kgCO2e/kg (placeholder, linear-to-area assumption)"
            )
        return None, f"tile line with unhandled unit '{uom}'"

    if category == CATEGORY_PAINT:
        entry = get_factor("paint")
        per_kg, coverage = entry["gwp_kgco2e_per_kg"], entry["coverage_kg_per_m2"]
        if _AREA_UNITS.match(uom):
            return qty * coverage * per_kg, f"{qty:g} m2 x {coverage} kg/m2 x {per_kg} kgCO2e/kg (placeholder)"
        return None, f"paint line with unhandled unit '{uom}'"

    if category == CATEGORY_ALUMINIUM:
        entry = get_factor("aluminium")
        per_kg, areal_mass = entry["gwp_kgco2e_per_kg"], entry["areal_mass_kg_per_m2"]
        if _AREA_UNITS.match(uom):
            return qty * areal_mass * per_kg, f"{qty:g} m2 x {areal_mass} kg/m2 x {per_kg} kgCO2e/kg (placeholder)"
        if _MASS_KG_UNITS.match(uom):
            return qty * per_kg, f"{qty:g} kg x {per_kg} kgCO2e/kg (placeholder)"
        return None, f"aluminium_glazing line with unhandled unit '{uom}'"

    if category == CATEGORY_GLASS:
        entry = get_factor("glass")
        per_kg, areal_mass = entry["gwp_kgco2e_per_kg"], entry["areal_mass_kg_per_m2"]
        if _AREA_UNITS.match(uom):
            return qty * areal_mass * per_kg, f"{qty:g} m2 x {areal_mass} kg/m2 x {per_kg} kgCO2e/kg (placeholder)"
        return None, f"glass line with unhandled unit '{uom}'"

    if category == CATEGORY_TIMBER:
        entry = get_factor("timber")
        per_kg = entry["gwp_kgco2e_per_kg"]
        # Count units (Nos) first -- this is the ONLY unit real timber
        # lines were found priced in (see _COUNT_UNITS comment). Mass/
        # volume/area paths are kept as a fallback for BOQs that price
        # timber differently, but are unverified against real data the
        # way the Nos path is.
        if _COUNT_UNITS.match(uom):
            mass_per_frame = entry["assumed_mass_kg_per_frame"]
            gwp = qty * mass_per_frame * per_kg
            return gwp, (
                f"{qty:g} Nos x {mass_per_frame} kg/frame (assumed) x "
                f"{per_kg} kgCO2e/kg (ICE v4.1, excl. carbon storage)"
            )
        if _MASS_KG_UNITS.match(uom):
            return qty * per_kg, f"{qty:g} kg x {per_kg} kgCO2e/kg (ICE v4.1, excl. carbon storage)"
        if _MASS_MT_UNITS.match(uom):
            return qty * 1000.0 * per_kg, f"{qty:g} MT x 1000 x {per_kg} kgCO2e/kg (ICE v4.1, excl. carbon storage)"
        if _VOL_UNITS.match(uom):
            density = entry["assumed_density_kg_per_m3"]
            gwp = qty * density * per_kg
            return gwp, f"{qty:g} m3 x {density} kg/m3 (assumed) x {per_kg} kgCO2e/kg (ICE v4.1, excl. carbon storage)"
        if _AREA_UNITS.match(uom):
            areal_mass = entry["assumed_areal_mass_kg_per_m2"]
            gwp = qty * areal_mass * per_kg
            return gwp, f"{qty:g} m2 x {areal_mass} kg/m2 (assumed) x {per_kg} kgCO2e/kg (ICE v4.1, excl. carbon storage)"
        return None, f"timber line with unhandled unit '{uom}'"

    return None, "unclassified"


# Backward-compatible alias -- the function was renamed from a module-
# private name to a shared one (see module docstring) once
# substitution_engine.py needed to import it directly.
_compute_line_gwp = compute_line_gwp


def calculate_from_boq(
    file_path: str,
    sheet_name: str,
    floor_area_sqm: Optional[float] = None,
    floor_area_basis: Optional[FloorAreaBasis] = None,
) -> BoqCarbonResult:
    """Extracts, classifies, and carbon-costs every billable line item in
    one BOQ sheet. floor_area_sqm/floor_area_basis are optional (a totals-
    only result is still useful without them) but if you pass one you
    should pass both -- a bare number with no basis is exactly the
    ambiguity that caused a real 8.5x mismatch on a real project, see the
    module docstring.
    """
    if floor_area_sqm is not None and floor_area_basis is None:
        raise ValueError(
            "floor_area_basis is required whenever floor_area_sqm is given -- "
            "see engine.py's module docstring for why a bare area figure "
            "without its definition caused a real 8.5x mismatch on a real project."
        )

    items = extract_billable_items(file_path, sheet_name)

    line_results: list[LineItemResult] = []
    category_totals: dict[str, dict] = {}

    for item in items:
        cls = classify_material(item.enriched_description)
        gwp, note = compute_line_gwp(cls.category, cls.cement_type, cls.grade, item.uom, item.qty)

        line_results.append(
            LineItemResult(
                row=item.row,
                enriched_description=item.enriched_description,
                uom=item.uom,
                qty=item.qty,
                category=cls.category,
                cement_type=cls.cement_type,
                grade=cls.grade,
                gwp_kg_co2e=gwp,
                basis_note=note,
            )
        )

        if gwp is not None:
            entry = category_totals.setdefault(cls.category, {"gwp": 0.0, "count": 0})
            entry["gwp"] += gwp
            entry["count"] += 1

    total_gwp = sum(v["gwp"] for v in category_totals.values())
    by_category = [
        CategoryTotal(
            category=cat,
            gwp_kg_co2e=v["gwp"],
            line_item_count=v["count"],
            pct_of_total=(v["gwp"] / total_gwp * 100) if total_gwp else 0.0,
        )
        for cat, v in sorted(category_totals.items(), key=lambda kv: -kv[1]["gwp"])
    ]

    n_classified = sum(1 for r in line_results if r.category is not None)
    n_computed = sum(1 for r in line_results if r.gwp_kg_co2e is not None)

    result = BoqCarbonResult(
        source_file=file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        sheet_name=sheet_name,
        n_lines_total=len(line_results),
        n_lines_classified=n_classified,
        n_lines_computed=n_computed,
        total_gwp_kg_co2e=total_gwp,
        total_gwp_tonnes_co2e=total_gwp / 1000.0,
        by_category=by_category,
        line_items=line_results,
    )

    if floor_area_sqm and floor_area_basis:
        result.floor_area_sqm = floor_area_sqm
        result.floor_area_basis = floor_area_basis
        result.floor_area_basis_note = FLOOR_AREA_BASIS_NOTES[floor_area_basis]
        result.gwp_per_sqm = total_gwp / floor_area_sqm
        result.gwp_per_sqft = total_gwp / floor_area_sqm / SQM_TO_SQFT

    return result