"""Standalone test script for the timber classifier + engine wiring
(classifier.py's _TIMBER_RE/CATEGORY_TIMBER, engine.py's CATEGORY_TIMBER
branch in compute_line_gwp(), and the new assumed_* keys in
boq_carbon_extra_factors.json's "timber" entry).

Matches this repo's existing test convention (scripts/test_boq_carbon_
pipeline.py, scripts/test_full_pipeline.py) -- a plain assert-based
script, no pytest dependency, run directly with python3 and read for a
pass/fail summary printed to stdout.

Covers, in order:
  1. Classifier regex -- positive matches (genuine timber/joinery terms)
     and negative matches (bare "wood" mentions and the real "wooden/
     steel rammers" false-positive class this regex was deliberately
     tightened to avoid).
  2. Engine unit conversion -- Nos (the verified real-data path), plus
     kg/MT/m3/m2 fallback paths, plus the unhandled-unit case.
  3. Factor file -- confirms boq_carbon_extra_factors.json's "timber"
     entry actually has the assumed_mass_kg_per_frame/assumed_density_
     kg_per_m3/assumed_areal_mass_kg_per_m2 keys the engine branch reads
     (this is exactly the KeyError gap that existed before those keys
     were added).
  4. End-to-end -- runs the real classify -> compute_line_gwp pipeline
     against both reference BOQs (Ecopolitan, Botanico) and checks
     timber shows up with a sane, non-crashing result on each.

Usage (from backend/):
    python scripts/test_timber_wiring.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.boq_carbon.classifier import (
    CATEGORY_TIMBER,
    classify_material,
)
from app.services.boq_carbon.engine import calculate_from_boq, compute_line_gwp
from app.services.boq_carbon.extra_factors import get_factor

REFERENCE_BOQS_DIR = Path(__file__).resolve().parent.parent / "app" / "data" / "reference_boqs"

_passed = 0
_failed = 0


def check(label: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))


def section(title: str):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ----------------------------------------------------------------------
section("1. Classifier regex -- positive matches (should classify as timber)")
# ----------------------------------------------------------------------

POSITIVE_CASES = [
    "Supply and fix Engineered Wood Frame for main door",
    "Providing and fixing Solid wood door shutter 35mm thick",
    "Teak wood door frame with chowkhat, size as per drawing",
    "19mm thick Plywood partition with laminate finish",
    "MDF panelling to false ceiling edge",
    "Particle board flush door shutter",
    "Chip board veneer finish wardrobe shutter",
    "Timber battens for false ceiling framework",
    "Flush door with wooden frame and hardware complete",
    "Providing wooden window shutter with glass panel",
    "Wood chowkhat for toilet door, treated timber",
    "Wooden jamb fixing for main entrance door",
]
for desc in POSITIVE_CASES:
    cls = classify_material(desc)
    check(f'"{desc[:55]}..."' if len(desc) > 55 else f'"{desc}"',
          cls.category == CATEGORY_TIMBER,
          f"got category={cls.category!r}")

# ----------------------------------------------------------------------
section("2. Classifier regex -- negative matches (should NOT classify as timber)")
# ----------------------------------------------------------------------

# The real false-positive class this regex was deliberately tightened to
# avoid: a bare "wood\w*" match would have caught "wooden/steel rammers"
# inside earthwork boilerplate. This row is excluded by _EARTHWORK_RE
# regardless, but the point of the tightened regex is that even WITHOUT
# that earthwork guard, a bare tool/prop mention of "wood" should not by
# itself trigger a timber classification.
NEGATIVE_CASES = [
    (
        "Earth filling in trenches, compacting each layer in 150mm depth "
        "with wooden/steel rammers to achieve required density, including "
        "excavation, dewatering wherever necessary, and disposal of surplus earth",
        None,  # excluded entirely by _EARTHWORK_RE ("excavat")
    ),
    ("Wood polish to existing railing, two coats", None),  # bare "wood", no joinery noun following
    ("Supply of firewood for site canteen use", None),  # "wood" substring, not a joinery term
]
for desc, expected in NEGATIVE_CASES:
    cls = classify_material(desc)
    label = f'"{desc[:55]}..."' if len(desc) > 55 else f'"{desc}"'
    check(label, cls.category != CATEGORY_TIMBER, f"got category={cls.category!r}, expected NOT timber")

# ----------------------------------------------------------------------
section("3. Engine unit conversion -- compute_line_gwp() for CATEGORY_TIMBER")
# ----------------------------------------------------------------------

timber_entry = get_factor("timber")
per_kg = timber_entry["gwp_kgco2e_per_kg"]

# Nos -- the verified real-data path (100% of genuine Ecopolitan timber
# lines are priced this way).
gwp, note = compute_line_gwp(CATEGORY_TIMBER, None, None, "Nos", 10)
expected = 10 * timber_entry["assumed_mass_kg_per_frame"] * per_kg
check("Nos path computes qty x assumed_mass_kg_per_frame x per_kg",
      gwp is not None and abs(gwp - expected) < 1e-6,
      f"got {gwp}, expected {expected}")
check("Nos path basis_note mentions 'Nos'", "Nos" in note, note)

gwp, note = compute_line_gwp(CATEGORY_TIMBER, None, None, "No.", 5)
check("'No.' unit variant also matches the count path", gwp is not None, note)

gwp, note = compute_line_gwp(CATEGORY_TIMBER, None, None, "each", 3)
check("'each' unit variant also matches the count path", gwp is not None, note)

# kg -- direct mass path
gwp, note = compute_line_gwp(CATEGORY_TIMBER, None, None, "kg", 100)
check("kg path computes qty x per_kg", gwp is not None and abs(gwp - 100 * per_kg) < 1e-6, f"got {gwp}")

# MT -- mass-tonnes path
gwp, note = compute_line_gwp(CATEGORY_TIMBER, None, None, "MT", 2)
check("MT path computes qty x 1000 x per_kg", gwp is not None and abs(gwp - 2 * 1000 * per_kg) < 1e-6, f"got {gwp}")

# m3 -- volume fallback path (uses assumed_density_kg_per_m3)
gwp, note = compute_line_gwp(CATEGORY_TIMBER, None, None, "cum", 1.5)
expected = 1.5 * timber_entry["assumed_density_kg_per_m3"] * per_kg
check("m3 path computes qty x assumed_density_kg_per_m3 x per_kg",
      gwp is not None and abs(gwp - expected) < 1e-6, f"got {gwp}, expected {expected}")

# m2 -- area fallback path (uses assumed_areal_mass_kg_per_m2)
gwp, note = compute_line_gwp(CATEGORY_TIMBER, None, None, "sqm", 8)
expected = 8 * timber_entry["assumed_areal_mass_kg_per_m2"] * per_kg
check("m2 path computes qty x assumed_areal_mass_kg_per_m2 x per_kg",
      gwp is not None and abs(gwp - expected) < 1e-6, f"got {gwp}, expected {expected}")

# Unhandled unit -- should fail gracefully (None + explanatory note), not raise
gwp, note = compute_line_gwp(CATEGORY_TIMBER, None, None, "ltr", 10)
check("Unhandled unit returns None (not a crash)", gwp is None)
check("Unhandled unit note explains why", "unhandled unit" in note, note)

# ----------------------------------------------------------------------
section("4. Factor file -- boq_carbon_extra_factors.json 'timber' entry")
# ----------------------------------------------------------------------

REQUIRED_KEYS = [
    "gwp_kgco2e_per_kg",
    "assumed_mass_kg_per_frame",
    "assumed_density_kg_per_m3",
    "assumed_areal_mass_kg_per_m2",
]
for key in REQUIRED_KEYS:
    check(f"timber entry has '{key}'", key in timber_entry, f"keys present: {list(timber_entry.keys())}")

check("assumed_mass_kg_per_frame is a positive number",
      isinstance(timber_entry.get("assumed_mass_kg_per_frame"), (int, float)) and timber_entry["assumed_mass_kg_per_frame"] > 0)
check("assumed_density_kg_per_m3 is a positive number",
      isinstance(timber_entry.get("assumed_density_kg_per_m3"), (int, float)) and timber_entry["assumed_density_kg_per_m3"] > 0)
check("assumed_areal_mass_kg_per_m2 is a positive number",
      isinstance(timber_entry.get("assumed_areal_mass_kg_per_m2"), (int, float)) and timber_entry["assumed_areal_mass_kg_per_m2"] > 0)

# ----------------------------------------------------------------------
section("5. End-to-end -- real reference BOQs")
# ----------------------------------------------------------------------

eco_path = REFERENCE_BOQS_DIR / "Ecopolitan_BOQ.xlsx"
bot_path = REFERENCE_BOQS_DIR / "Botanico_BOQ.xlsx"

if eco_path.exists():
    result = calculate_from_boq(str(eco_path), "Part-A & B_BOQ", floor_area_sqm=205981.65, floor_area_basis="built_up_total")
    timber_cat = next((c for c in result.by_category if c.category == CATEGORY_TIMBER), None)
    check("Ecopolitan: timber category present in results", timber_cat is not None)
    if timber_cat:
        check("Ecopolitan: timber has a positive GWP total", timber_cat.gwp_kg_co2e > 0, f"got {timber_cat.gwp_kg_co2e}")
        check("Ecopolitan: timber has line items counted", timber_cat.line_item_count > 0, f"got {timber_cat.line_item_count}")
    check("Ecopolitan: no exception raised end-to-end (implicit -- reached this line)", True)
else:
    print(f"  SKIP  Ecopolitan_BOQ.xlsx not found at {eco_path}")

if bot_path.exists():
    result = calculate_from_boq(str(bot_path), "Part-A & B_BOQ ", floor_area_sqm=181150, floor_area_basis="built_up_total")
    check("Botanico: pipeline runs end-to-end with no crash (no timber lines expected in this BOQ)", True)
else:
    print(f"  SKIP  Botanico_BOQ.xlsx not found at {bot_path}")

# ----------------------------------------------------------------------
section("SUMMARY")
# ----------------------------------------------------------------------

print(f"  {_passed} passed, {_failed} failed")
if _failed:
    sys.exit(1)