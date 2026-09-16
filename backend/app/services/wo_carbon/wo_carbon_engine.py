"""Work Order -> embodied carbon calculation engine.

Companion to app/services/boq_carbon/engine.py (which works from a raw
xlsx BOQ, classifying line items with regex). This module works from a
Work Order PDF (wo_pdf_parser.py) and a pre-classified master item-code
dataset (Provident_Combined_Master_Item_Codes.xlsx, converted to JSON by
build_master_factors_json.py, then LEANED by
scripts/migrate_master_item_codes_v2.py -- see that script's docstring)
-- classification here is a lookup by Activity Number, not a regex
guess, because the master dataset already carries a per-code Contributes
to Carbon / Material Category / Unit Conversion Note verdict.

As of Workstream 01 (one emission-factor source), the master file's rows
no longer carry their own embedded ef_kgco2e_per_kg / ef_source /
evidence_tier -- just `material_category` (already the clean canonical
key -- see app.services.emission_factors's docstring for the full
category list) plus `unit` / `unit_note` / `kg_per_unit`. The actual
number is resolved at calculation time, per line, from exactly the same
place boq_carbon/engine.py reads it: app.services.ice_factors for
concrete/reinforcement steel (grade/cement-type dependent -- grade and
cement type are now detected from the Activity Code's own `desc` text
using classifier.py's own regexes, the same way boq_carbon detects them
from a BOQ line's text) and app.services.emission_factors for every
other category. See _resolve_ef() below.

Formula selection mirrors the master file's own Unit Conversion Note
field exactly (see each branch below), applied programmatically instead
of by reading the note text at request time. IMPORTANT: a "yes"
Contributes-to-Carbon row is NOT always computable -- some rows are
flagged "NEEDS AREAL-MASS ASSUMPTION" (an area-priced material with a
real, sourced per-kg factor but no documented kg/m2 conversion yet) or
"NEEDS REVIEW" (an odd unit with no established conversion) or
"Not applicable" (category outside this round's factor-mapping scope,
e.g. tile/plaster/paint/blockwork as of the Combined Master's first
cut). Those rows are excluded here exactly as the master file intends,
and show up in the result's `excluded_no_formula` list rather than being
silently dropped -- see this module's test script for the real coverage
gap this currently leaves (roughly a quarter of WO contract value, by
the Ecopolitan WO KPIL run).

Validated end-to-end against the real Ecopolitan WO KPIL PDF: reproduces
the manually-verified total (see scripts/test_wo_carbon_engine.py).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from app.services import coverage as coverage_service
from app.services.emission_factors import (
    detect_cement_type,
    detect_grade,
    get_concrete_factor_per_kg,
    get_steel_rebar_factor_per_kg,
)
from app.services.ice_factors import get_concrete_density_kg_per_m3
from app.services.wo_carbon.wo_pdf_parser import WoLineItem, parse_work_order_pdf

SQFT_TO_SQM = 10.7639
ALUMINIUM_AREAL_MASS_KG_PER_M2 = 12.0
GLASS_AREAL_MASS_KG_PER_M2 = 15.0
TIMBER_ASSUMED_MASS_KG_PER_FRAME = 20.0

# Categories with no computation branch below yet -- kept in one place so
# a new canonical category from emission_factors.json doesn't silently
# fall through to "no computation branch yet" without a deliberate look.
_KNOWN_NO_BRANCH_YET = {
    "steel_gi_galvanized", "steel_stainless", "upvc_window_door_frame",
    "blockwork_aac", "blockwork_dense", "plaster_cement", "plaster_gypsum",
    "tile_ceramic", "tile_vitrified", "natural_stone", "cement_bagged",
    "cement_mortar", "insulation_mineral_wool", "insulation_generic",
    "waterproofing", "copper", "pvc_pipe_fitting", "bitumen_asphalt",
}

FloorAreaBasis = Literal["net_internal_gia", "built_up_total", "carpet_saleable", "other"]


def _resolve_ef(material_category: Optional[str], desc: Optional[str]) -> tuple[Optional[float], str, Optional[str]]:
    """Looks up the emission factor for one master-file row's category,
    from the single canonical source (see module docstring). Returns
    (ef_kgco2e_per_kg or None, a short provenance label for basis_note,
    evidence_tier or None) -- the evidence_tier is what used to be a
    per-row field on the master file itself; it's now resolved alongside
    the factor value since both come from the same canonical place.

    Concrete and steel_reinforcement are cement-type/grade dependent, so
    `desc` (the Activity Code's own description text, e.g. "CRE- Plain
    Concrete M25 for Support str") is scanned with classifier.py's own
    cement-type/grade regexes -- confirmed real grade tokens (M10, M20,
    M25...) are genuinely present in these descriptions, the same way
    they're present in a BOQ line's text. No grade found -> the M40-
    anchor/scale=1.0 default, same fallback ice_factors.py already
    documents for a BOQ line with no stated grade; no cement-type keyword
    found -> PPC default, matching classifier.py's own stated default.
    """
    if material_category is None:
        return None, "uncategorized", None

    text = desc or ""

    if material_category == "concrete":
        cement_type = detect_cement_type(text) or "PPC"
        grade = detect_grade(text)
        per_kg, source = get_concrete_factor_per_kg(cement_type=cement_type, grade=grade, apply_cea=True)
        return per_kg, f"{cement_type}, {grade or 'grade unstated -> M40-equivalent'}, {source}, CEA-adjusted", source

    if material_category == "reinforcement_steel":
        per_kg, source = get_steel_rebar_factor_per_kg(apply_cea=True)
        return per_kg, f"{source}, CEA-adjusted", source

    try:
        from app.services.emission_factors import get_factor as _get_canonical_entry

        entry = _get_canonical_entry(material_category)
        return entry["ef_kgco2e_per_kg"], "emission_factors.json", entry.get("evidence_tier")
    except KeyError:
        return None, f"no canonical emission factor for category '{material_category}'", None


@lru_cache(maxsize=4)
def _load_master_factors(master_json_path: str) -> dict:
    with open(master_json_path) as f:
        return json.load(f)


def compute_line_gwp_kg(material_category: Optional[str], unit: Optional[str], qty: float, ef: Optional[float], unit_note: Optional[str], kg_per_unit: Optional[float] = None) -> tuple[Optional[float], str]:
    """Returns (gwp_kg_co2e or None, reason). `material_category` is the
    master file's own clean canonical category key as of Workstream 01's
    migration (scripts/migrate_master_item_codes_v2.py) -- e.g. "concrete",
    "structural_steel" -- no parenthetical stripping needed here anymore
    (the caller no longer does it either, see calculate_from_work_order).
    `ef` is resolved by the caller via _resolve_ef(), from the single
    canonical factor source, not read off this row directly.

    `kg_per_unit`, when present, comes from the classification-enhancement
    pipeline's dimension-mining or standard-weight-table resolution (see
    enhance_master_classification.py / dimension_miner.py /
    standard_weight_tables.py) -- a real, row-specific mass-per-unit
    figure computed once at data-build time from the row's own
    description text (embedded dimensions, an explicit weight hint, or a
    matched IS-standard section/pipe weight), rather than one flat
    category-wide assumption. When set, it takes priority over every
    category-specific branch below: qty (already in the row's own NOS/EA/
    RMT/M unit) x kg_per_unit x ef.
    """
    if ef is None:
        return None, "no emission factor on file for this code"

    if kg_per_unit is not None:
        gwp = qty * kg_per_unit * ef
        return gwp, f"{qty:g} x {kg_per_unit:g} kg/unit (dimension-mined/weight-table) x {ef} kgCO2e/kg"

    note = unit_note or ""
    u = (unit or "").strip().upper()

    # Only aluminium and glass have a documented areal-mass assumption
    # so far -- every other area-priced category explicitly flagged
    # "NEEDS AREAL-MASS ASSUMPTION" is NOT computable yet even though it
    # has a real per-kg factor. Check this before the per-category
    # branches below so a future new area-priced category defaults to
    # excluded rather than silently guessing a formula for it.
    if "NEEDS AREAL-MASS ASSUMPTION" in note and material_category not in ("aluminium", "glass"):
        return None, "area-priced, no documented areal-mass assumption for this category yet"

    if material_category == "concrete":
        density = get_concrete_density_kg_per_m3()
        if u in ("CUM", "M3"):
            return qty * density * ef, f"{qty:g} m3 x {density:g} kg/m3 x {ef} kgCO2e/kg"
        if u == "MT":
            return qty * 1000.0 * ef, f"{qty:g} MT x 1000 x {ef} kgCO2e/kg"
        if u == "KG":
            return qty * ef, f"{qty:g} kg x {ef} kgCO2e/kg"
        return None, f"concrete line with unhandled unit '{unit}'"

    if material_category in ("reinforcement_steel", "structural_steel", "steel_gi_galvanized", "steel_stainless"):
        if u in ("KG", "KGS"):
            return qty * ef, f"{qty:g} kg x {ef} kgCO2e/kg"
        if u == "MT":
            return qty * 1000.0 * ef, f"{qty:g} MT x 1000 x {ef} kgCO2e/kg"
        return None, f"{material_category} line with unhandled unit '{unit}'"

    if material_category == "aluminium":
        if u == "KGS":
            return qty * ef, f"{qty:g} kg x {ef} kgCO2e/kg"
        if u == "SQM":
            gwp = qty * ALUMINIUM_AREAL_MASS_KG_PER_M2 * ef
            return gwp, f"{qty:g} m2 x {ALUMINIUM_AREAL_MASS_KG_PER_M2} kg/m2 (assumed) x {ef} kgCO2e/kg"
        return None, f"aluminium line with unhandled unit '{unit}'"

    if material_category == "glass":
        if u == "SQM":
            gwp = qty * GLASS_AREAL_MASS_KG_PER_M2 * ef
            return gwp, f"{qty:g} m2 x {GLASS_AREAL_MASS_KG_PER_M2} kg/m2 (assumed) x {ef} kgCO2e/kg"
        if u == "FT2":
            sqm = qty / SQFT_TO_SQM
            gwp = sqm * GLASS_AREAL_MASS_KG_PER_M2 * ef
            return gwp, f"{qty:g} ft2 -> {sqm:.2f} m2 x {GLASS_AREAL_MASS_KG_PER_M2} kg/m2 (assumed) x {ef} kgCO2e/kg"
        return None, f"glass line with unhandled unit '{unit}'"

    if material_category == "timber_wood":
        if u == "NOS":
            gwp = qty * TIMBER_ASSUMED_MASS_KG_PER_FRAME * ef
            return gwp, f"{qty:g} Nos x {TIMBER_ASSUMED_MASS_KG_PER_FRAME} kg/frame (assumed) x {ef} kgCO2e/kg"
        return None, f"timber line with unhandled unit '{unit}'"

    if material_category == "sand":
        if u == "MT":
            return qty * 1000.0 * ef, f"{qty:g} MT x 1000 x {ef} kgCO2e/kg"
        return None, f"sand line with unhandled unit '{unit}'"

    if material_category in _KNOWN_NO_BRANCH_YET:
        return None, f"'{material_category}' has a real, sourced emission factor but no unit-conversion formula wired up yet"
    return None, f"'{material_category}' has no computation branch yet (and is not in the known-gaps list -- worth a look)"


class WoLineItemResult(BaseModel):
    code: str
    description: Optional[str] = None
    unit: str
    qty: float
    rate: float
    amount: float
    contributes: Optional[str] = None
    material_category: Optional[str] = None
    evidence_tier: Optional[str] = None
    gwp_kg_co2e: Optional[float] = None
    basis_note: str
    # Workstream 07: the master item-code dataset's own per-Activity-Code
    # top5 flag (human-curated, present since that dataset was first
    # built -- see app.services.coverage's module docstring for why this
    # engine reads it directly rather than recomputing from
    # material_category the way boq_carbon has to). None when the code
    # wasn't found in the master file at all (top5 status unknown).
    top5: Optional[bool] = None


class WoCategoryTotal(BaseModel):
    category: str
    gwp_kg_co2e: float
    line_item_count: int
    wo_amount_covered: float
    pct_of_total: float


class WoCarbonResult(BaseModel):
    source_file: str
    n_line_items_parsed: int
    n_line_items_computed: int
    total_gwp_kg_co2e: float
    total_gwp_tonnes_co2e: float
    by_category: list[WoCategoryTotal]
    floor_area_sqm: Optional[float] = None
    floor_area_basis: Optional[FloorAreaBasis] = None
    gwp_per_sqm: Optional[float] = None
    gwp_per_sqft: Optional[float] = None
    total_wo_amount: float
    computed_wo_amount: float
    parse_checksum_ok: Optional[bool] = None  # parsed line-item Amounts sum to the WO's own BOQ SUMMARY grand total
    line_items: list[WoLineItemResult] = []
    # Workstream 06: set by app/api/wo_carbon.py, not by this engine
    # itself (calculate_from_work_order has no company_id/reference-
    # registration concept). Left None for any caller that doesn't go
    # through the auto-registration path -- purely additive.
    registered_as_reference: Optional[bool] = None
    reference_slug: Optional[str] = None
    registration_note: Optional[str] = None
    # Workstream 07: value-weighted coverage summary (computed vs. total
    # WO Amount, broken down by a fixed six-reason taxonomy) plus the
    # same figures restricted to top5=="yes" line items -- see
    # app.services.coverage's module docstring. This is the piece that
    # finally reads the master file's own top5 flag, previously inert
    # metadata (see the roadmap's WS07 entry).
    coverage: Optional[coverage_service.Coverage] = None


def _classify_wo_exclusion_reason(basis_note: str, contributes: Optional[str]) -> str:
    """Buckets one excluded WO line item into the fixed six-reason
    taxonomy (app.services.coverage). wo_carbon's PDF parser always
    yields a real qty/unit for a parsed line, so this engine never emits
    NO_QUANTITY -- that reason is boq_carbon-only.
    """
    if contributes is not None and contributes != "yes":
        return coverage_service.REASON_NOT_CONTRIBUTING if contributes == "no" else coverage_service.REASON_NEEDS_REVIEW
    if basis_note == "Activity Number not found in master item-code dataset":
        return coverage_service.REASON_UNCLASSIFIED
    if basis_note == "no emission factor on file for this code":
        return coverage_service.REASON_NO_EMISSION_FACTOR
    return coverage_service.REASON_UNHANDLED_UNIT


def calculate_from_work_order(
    pdf_path: str,
    master_json_path: str,
    floor_area_sqm: Optional[float] = None,
    floor_area_basis: Optional[FloorAreaBasis] = None,
) -> WoCarbonResult:
    parsed = parse_work_order_pdf(pdf_path)
    master = _load_master_factors(master_json_path)

    checksum_ok = None
    if parsed.summary_grand_total is not None:
        checksum_ok = abs(parsed.total_amount_parsed - parsed.summary_grand_total) < 1.0  # within Re. 1 rounding

    line_results: list[WoLineItemResult] = []
    by_cat: dict[str, dict] = {}

    for it in parsed.items:
        m = master.get(it.code)
        if m is None:
            line_results.append(WoLineItemResult(
                code=it.code, unit=it.unit, qty=it.qty, rate=it.rate, amount=it.amount,
                basis_note="Activity Number not found in master item-code dataset",
            ))
            continue

        contributes = (m.get("contributes") or "").strip().lower()
        # As of Workstream 01's migration, material_category on the master
        # file is already the clean canonical key -- no parenthetical
        # stripping needed here anymore (compare the pre-migration
        # "concrete (RCC, PPC, grade M30 ...)" -> "concrete" split this
        # used to do at every single row, every request).
        category = m.get("material_category") or None
        desc = m.get("desc")
        # Workstream 07: the master file's own human-curated top5 flag
        # (a plain JSON true/false as of the migration; tolerate a
        # legacy "yes"/"no" string too since this reads directly off
        # disk rather than through a schema).
        top5_raw = m.get("top5")
        top5 = top5_raw if isinstance(top5_raw, bool) else (str(top5_raw).strip().lower() == "yes" if top5_raw is not None else None)

        if contributes != "yes":
            line_results.append(WoLineItemResult(
                code=it.code, description=desc, unit=it.unit, qty=it.qty, rate=it.rate, amount=it.amount,
                contributes=contributes, material_category=category, top5=top5,
                basis_note=f"Contributes to Carbon = '{contributes}'",
            ))
            continue

        ef, ef_note, evidence_tier = _resolve_ef(category, desc)

        # Use the master's OWN registered unit (authoritative, one per
        # code) rather than the WO-parsed unit for the formula decision --
        # the WO text occasionally mis-tokenizes a unit-like substring
        # inside a description (e.g. "M" in "Spreading M Sand On Podium"
        # before the real "CUM" column). Confirmed zero mismatches
        # between the two for any contributes=="yes" code on the
        # reference WO, so this is a safety fix, not an observed
        # correction, but it removes a whole class of risk.
        gwp_kg, note = compute_line_gwp_kg(category, m.get("unit"), it.qty, ef, m.get("unit_note"), m.get("kg_per_unit"))
        if gwp_kg is not None:
            note = f"{note} ({ef_note})"

        line_results.append(WoLineItemResult(
            code=it.code, description=desc, unit=it.unit, qty=it.qty, rate=it.rate, amount=it.amount,
            contributes=contributes, material_category=category, evidence_tier=evidence_tier,
            gwp_kg_co2e=gwp_kg, basis_note=note, top5=top5,
        ))

        if gwp_kg is not None:
            c = by_cat.setdefault(category, {"gwp": 0.0, "count": 0, "amount": 0.0})
            c["gwp"] += gwp_kg
            c["count"] += 1
            c["amount"] += it.amount

    total_gwp = sum(v["gwp"] for v in by_cat.values())
    by_category = [
        WoCategoryTotal(
            category=cat, gwp_kg_co2e=v["gwp"], line_item_count=v["count"],
            wo_amount_covered=v["amount"],
            pct_of_total=(v["gwp"] / total_gwp * 100) if total_gwp else 0.0,
        )
        for cat, v in sorted(by_cat.items(), key=lambda kv: -kv[1]["gwp"])
    ]

    total_wo_amount = sum(it.amount for it in parsed.items)
    computed_wo_amount = sum(v["amount"] for v in by_cat.values())
    n_computed = sum(1 for r in line_results if r.gwp_kg_co2e is not None)

    coverage_rows = [
        {
            "value": r.amount or 0.0,
            "computed": r.gwp_kg_co2e is not None,
            "is_top5": bool(r.top5),
            "reason": None if r.gwp_kg_co2e is not None else _classify_wo_exclusion_reason(r.basis_note, r.contributes),
        }
        for r in line_results
    ]

    result = WoCarbonResult(
        source_file=Path(pdf_path).name,
        n_line_items_parsed=len(parsed.items),
        n_line_items_computed=n_computed,
        total_gwp_kg_co2e=total_gwp,
        total_gwp_tonnes_co2e=total_gwp / 1000.0,
        by_category=by_category,
        total_wo_amount=total_wo_amount,
        computed_wo_amount=computed_wo_amount,
        parse_checksum_ok=checksum_ok,
        line_items=line_results,
        coverage=coverage_service.build_coverage(coverage_rows),
    )

    if floor_area_sqm and floor_area_basis:
        result.floor_area_sqm = floor_area_sqm
        result.floor_area_basis = floor_area_basis
        result.gwp_per_sqm = total_gwp / floor_area_sqm
        result.gwp_per_sqft = total_gwp / floor_area_sqm / SQFT_TO_SQM

    return result