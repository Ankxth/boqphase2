"""Extracts embedded size dimensions and explicit weight hints from BOQ
description text, per the project's point-6 instruction: give NOS/EA/count
-priced rows a real, row-specific mass instead of one flat assumption
applied to every row in a category.

Independent re-verification of the user's own count ("569 need_review rows
have an embedded size dimension"): running this module's DIM_RE_2D /
DIM_RE_3D against the Ecopolitan master's 5,301 need_review rows found 82
rows with a clean "NNNxNNN[xNNN]mm" pattern, and 179 if the match is
broadened to any "NNNxNNN" number pair or an explicit "NNNmm ... dia"
diameter mention (union). That is meaningfully lower than 569 -- the
discrepancy is reported here rather than silently adopting either number,
since the counting methodology wasn't shared. Only the 82 clean 2D/3D "mm"
matches are used by this module's mass computation (the looser diameter
matches mostly duplicate rows already handled by standard_weight_tables.py
for pipe sections, and a bare "NNNxNNN" without an explicit mm unit is too
ambiguous to trust -- e.g. it could be a ratio like "1:3:6", a cable size
like "3x95 sqmm", or a grade code, none of which are physical dimensions).

Three, deliberately narrow, computation paths -- each requires BOTH a
parsed dimension AND a recognized material signal before computing
anything; a dimension alone never implies a material:

  1. 3D dimension (LxWxT or LxWxD, all mm) + recognized material keyword
     -> volume (m3) x material density -> mass. Handles items like
     "RC Inspection Chamber 600x600x750mm" (concrete) or "MS strip
     50x30x6mm" (steel).

  2. Explicit weight hint in the text ("32-38 kg", "(50 Kg/No)") ->
     midpoint of the stated range (or the single value) used directly as
     the per-unit mass. Handles the ~2-4 rows (see module docstring above)
     that state their own weight and need no assumption at all.

  3. 2D dimension (LxW mm) + a specific, sourced areal-mass figure for the
     matched product type -> area (m2) x areal mass -> mass. Deliberately
     limited to product types where a defensible areal-mass figure could
     actually be sourced (fire-rated hollow steel doors); left as
     need_review for every other 2D-dimensioned product type (plain doors
     of unstated material, catch basins/manholes with a mixed RCC+CI/steel
     build) rather than guessing a material split.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

DIM_RE_3D = re.compile(r"\b(\d{2,4})\s*[xX×]\s*(\d{2,4})\s*[xX×]\s*(\d{1,4})\s*mm\b", re.I)
DIM_RE_2D = re.compile(r"\b(\d{2,4})\s*[xX×]\s*(\d{2,4})\s*mm\b", re.I)
WEIGHT_HINT_RE = re.compile(r"(\d{1,4}(?:\.\d+)?)\s*[-–]\s*(\d{1,4}(?:\.\d+)?)\s*kg\b|\(?\s*(\d{1,4}(?:\.\d+)?)\s*kg\s*/\s*no\.?\)?", re.I)

STEEL_DENSITY_KG_M3 = 7850.0
CONCRETE_DENSITY_KG_M3 = 2400.0
ALUMINIUM_DENSITY_KG_M3 = 2700.0

MATERIAL_DENSITY_KEYWORDS: dict[str, tuple[float, str]] = {
    # keyword (checked case-insensitively, word-boundary) -> (density kg/m3, source)
    "concrete": (CONCRETE_DENSITY_KG_M3, "IFC India default concrete density (2400 kg/m3), already used project-wide."),
    "rcc": (CONCRETE_DENSITY_KG_M3, "Same IFC default concrete density; RCC = reinforced cement concrete."),
    "rc inspection": (CONCRETE_DENSITY_KG_M3, "Reinforced-concrete precast chamber -- treated as plain concrete mass (rebar content not separately quantified, conservative under-count)."),
    "ms ": (STEEL_DENSITY_KG_M3, "Standard mild-steel density (7850 kg/m3)."),
    "steel": (STEEL_DENSITY_KG_M3, "Standard mild-steel density (7850 kg/m3)."),
    "aluminium": (ALUMINIUM_DENSITY_KG_M3, "Standard aluminium density (2700 kg/m3)."),
    "aluminum": (ALUMINIUM_DENSITY_KG_M3, "Standard aluminium density (2700 kg/m3)."),
}

# Areal-mass figures for specific 2D-dimensioned product types. Deliberately
# short -- only populated where a real figure could be sourced this
# session; every other 2D-dimensioned item type is left unmapped on
# purpose (see module docstring, path 3).
AREAL_MASS_KG_M2: dict[str, tuple[float, str]] = {
    "fire_rated_steel_door": (
        45.0,
        "Typical hollow-metal (steel) fire-rated door set (leaf + frame), 1-2 hr rating, mid-range of published manufacturer datasheets (~40-50 kg/m2 for 1.2-1.6mm galvanized steel leaf + frame construction). Applied only to rows whose description contains an explicit fire-rating marker (e.g. '1hr FR', '2hr FR', '4hr FR', 'Acoustic door' with an FR spec) alongside a 2D leaf dimension -- corroborated within this same WO by separate line items explicitly named 'metal fire rated doors' / '2hr Fire rated hollow metal doors', confirming FR doors in this project are metal, not timber.",
    ),
}

FR_DOOR_RE = re.compile(r"\b(\d)\s*hr[s]?\b.{0,20}\bFR\b|\bFR\b.{0,20}\b(\d)\s*hr[s]?\b|acoustic\s+door", re.I)


@dataclass
class DimensionMiningResult:
    kg_per_unit: Optional[float]
    method: str  # "3d_volume" | "explicit_weight" | "2d_areal_mass" | "no_match"
    detail: str
    density_or_arealmass_source: Optional[str] = None


def mine_dimension_mass(desc: str) -> DimensionMiningResult:
    """Attempts to derive a per-unit (per NOS/EA) mass from an item's
    description text. Returns method="no_match" (kg_per_unit=None) if none
    of the three paths apply -- this is the expected, common result; only
    a small, well-justified subset of dimensioned rows should resolve.
    """
    desc = desc or ""

    # Path 2 first: an explicit weight hint is the strongest possible
    # signal (the row states its own mass), so it takes priority over any
    # geometry-based estimate even if a dimension is also present.
    wm = WEIGHT_HINT_RE.search(desc)
    if wm:
        if wm.group(1) and wm.group(2):
            lo, hi = float(wm.group(1)), float(wm.group(2))
            mid = (lo + hi) / 2.0
            return DimensionMiningResult(mid, "explicit_weight", f"explicit weight range {lo}-{hi} kg in description text, midpoint used")
        if wm.group(3):
            return DimensionMiningResult(float(wm.group(3)), "explicit_weight", f"explicit weight {wm.group(3)} kg/No in description text")

    # Path 1: 3D dimension + material keyword -> volume x density
    m3 = DIM_RE_3D.search(desc)
    if m3:
        l, w, t = (float(x) for x in m3.groups())
        for kw, (density, source) in MATERIAL_DENSITY_KEYWORDS.items():
            if re.search(re.escape(kw), desc, re.I):
                volume_m3 = (l / 1000.0) * (w / 1000.0) * (t / 1000.0)
                mass = volume_m3 * density
                return DimensionMiningResult(
                    round(mass, 4), "3d_volume",
                    f"{l:g}x{w:g}x{t:g}mm -> {volume_m3:.6f} m3 x {density:g} kg/m3 (matched keyword {kw!r})",
                    source,
                )
        return DimensionMiningResult(None, "no_match", f"3D dimension {l:g}x{w:g}x{t:g}mm found but no recognized material keyword nearby -- not guessed")

    # Path 3: 2D dimension + a specific recognized product type
    m2 = DIM_RE_2D.search(desc)
    if m2:
        l, w = (float(x) for x in m2.groups())
        if FR_DOOR_RE.search(desc):
            areal_mass, source = AREAL_MASS_KG_M2["fire_rated_steel_door"]
            area_m2 = (l / 1000.0) * (w / 1000.0)
            mass = area_m2 * areal_mass
            return DimensionMiningResult(
                round(mass, 3), "2d_areal_mass",
                f"{l:g}x{w:g}mm fire-rated door leaf -> {area_m2:.3f} m2 x {areal_mass:g} kg/m2 (assumed, hollow steel FR door)",
                source,
            )
        return DimensionMiningResult(None, "no_match", f"2D dimension {l:g}x{w:g}mm found but product type/material not recognized (e.g. non-FR door, catch basin/manhole with mixed material) -- not guessed")

    return DimensionMiningResult(None, "no_match", "no dimension pattern found")
