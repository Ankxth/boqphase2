"""The cross-company material-category taxonomy -- Workstream 05.

scripts/enhance_master_classification.py hardcoded six category
templates as Python constants (CONCRETE_TEMPLATE,
STEEL_STRUCTURAL_TEMPLATE, STEEL_GI_TEMPLATE, STEEL_STAINLESS_TEMPLATE,
PAINT_TEMPLATE, GYPSUM_TEMPLATE), each one copied field-for-field from an
already-correctly-classified, sourced row in Provident's own master
file. Those six categories are real physical materials with a real,
citable emission factor -- true for every company, not just Provident --
so this module turns them from hardcoded constants into a loadable,
growable, on-disk registry any company's onboarding run reads from and
(when a human reviewer confirms a genuinely new category) can add to.

This is the concrete mechanism behind the roadmap's "confirmed answers
feed forward into a shared cross-company reference set" line: it is the
CATEGORY TAXONOMY that is shared across companies, never a company's raw
item codes or its own item-code -> category mapping (that stays private
per company, in that company's own master_item_codes.json -- see
company_store.master_item_codes_path). A new company benefits from every
prior company's confirmed categories without any of its own item codes,
descriptions, or pricing ever being visible to anyone else.

SEED_CATEGORIES below is the single source of truth for the six
starting categories (also used to write the real, visible
app/data/canonical_material_categories.json file that ships with this
workstream). Reading falls back to SEED_CATEGORIES in memory if that
file is ever missing (e.g. a fresh test tmp_path), so behavior never
depends on a file having been pre-created; but nothing writes
automatically on a read -- only register_category() (an explicit,
human-reviewed action) ever persists a change, so a read-only code path
never has a disk side effect.

Post-delivery correction: the very first version of this file copied
each template's material_category string verbatim from
scripts/enhance_master_classification.py's hardcoded constants --
including "steel_structural", "plaster (gypsum)", and a grade-suffixed
"concrete (RCC, PPC, grade M30 ...)" string for concrete. Those strings
were never actually exercised in production before (the original
script wrote its output to a standalone /home/claude/phase2b/... file,
never merged into a live master_item_codes.json), so the mismatch was
latent. Checked directly against
app/services/wo_carbon/wo_carbon_engine.py's _resolve_ef() (which does
an EXACT string match against "concrete" and "reinforcement_steel", and
otherwise looks the category up verbatim in
app/data/ice_db/emission_factors.json) and against that file's real,
live keys: the correct canonical values are the bare "concrete" (no
grade suffix -- _resolve_ef re-detects the grade from the row's own
`desc` text independently via detect_grade(), so encoding it into
material_category was redundant AND broke the exact-match check),
"structural_steel" (not "steel_structural"), and "plaster_gypsum" (not
"plaster (gypsum)"). Fixed here before any company had been onboarded
through this pipeline, so no live master_item_codes.json ever held the
wrong values.
"""

from __future__ import annotations

import json
from typing import Optional

from app.services import company_store

# ---------------------------------------------------------------------------
# The six categories carried over unchanged from
# scripts/enhance_master_classification.py's hardcoded templates. Every
# field and every ef_source citation is copied verbatim -- nothing here
# is a new number or a new source, only a new home for the same six,
# already-defensible numbers.
# ---------------------------------------------------------------------------

SEED_CATEGORIES: dict[str, dict] = {
    "concrete": {
        "contributes": "yes", "top5": "yes", "ef_kgco2e_per_kg": 0.08386,
        "ef_source": "IFC India Construction Materials Database (2017), Table 14, by cement type, CEA grid-adjusted.",
        "cea_adjusted": "yes", "evidence_tier": "ifc_primary_source",
        "material_category": "concrete",
        "unit_note": "Convert Cum to kg using concrete density 2400 kg/m3 (IFC default), then apply per-kg factor.",
    },
    "structural_steel": {
        "contributes": "yes", "top5": "yes", "ef_kgco2e_per_kg": 2.34713,
        "ef_source": "IFC India Construction Materials Database (2017), Table 14, p.69 -- 'Steel section', CEA grid-adjusted.",
        "cea_adjusted": "yes", "evidence_tier": "ifc_primary_source",
        "material_category": "structural_steel",
        "unit_note": "Direct mass conversion: qty already in mass units (KG/KGS/MT), apply per-kg factor.",
    },
    "steel_gi_galvanized": {
        "contributes": "yes", "top5": "yes", "ef_kgco2e_per_kg": 2.80449,
        "ef_source": "IFC India Construction Materials Database (2017), Table 14 -- Electrogalvanized steel sheet, CEA grid-adjusted.",
        "cea_adjusted": "yes", "evidence_tier": "ifc_primary_source",
        "material_category": "steel_gi_galvanized",
        "unit_note": "Direct mass conversion: qty already in mass units (KG/KGS/MT), apply per-kg factor.",
    },
    "steel_stainless": {
        "contributes": "yes", "top5": "no", "ef_kgco2e_per_kg": 4.17786,
        "ef_source": "ICE Database v4.1 (Oct 2025), Steel material profile, row 'Steel, Stainless' -- average of 28 datapoints. No IFC India stainless-steel line exists; this is the only project data file with a stainless-steel figure.",
        "cea_adjusted": "no", "evidence_tier": "ice_uk_proxy",
        "material_category": "steel_stainless",
        "unit_note": "Direct mass conversion: qty already in mass units (KG/KGS/MT), apply per-kg factor.",
    },
    "paint": {
        "contributes": "yes", "top5": "no", "ef_kgco2e_per_kg": 2.6,
        "ef_source": "Retained from the uploaded Embodied Carbon Contributor Flags sheet (ICE Database, Circular Ecology/Univ. of Bath) -- no defensible IFC India match found. (ICE paint, general, midpoint of water/solvent-based range).",
        "cea_adjusted": "no", "evidence_tier": "ice_uk_proxy",
        "material_category": "paint",
        "unit_note": "NEEDS AREAL-MASS ASSUMPTION -- an area-priced row needs a kg/m2 conversion figure; only aluminium (12 kg/m2) and glass (15 kg/m2) have a documented assumption so far. Paint's own areal-mass figure is still open.",
    },
    "plaster_gypsum": {
        "contributes": "yes", "top5": "no", "ef_kgco2e_per_kg": 0.099,
        "ef_source": "IFC India Construction Materials Database (2017), Table 14 -- Gypsum plaster. Raw value, NOT CEA-adjusted.",
        "cea_adjusted": "no", "evidence_tier": "ifc_primary_source",
        "material_category": "plaster_gypsum",
        "unit_note": "NEEDS AREAL-MASS ASSUMPTION -- an area-priced row needs a kg/m2 conversion figure; only aluminium and glass have one so far.",
    },
}


def load_canonical_categories() -> dict[str, dict]:
    """Returns key -> template dict. Reads the real on-disk file if it
    exists; otherwise returns SEED_CATEGORIES unchanged (no write, no
    side effect -- see module docstring).
    """
    path = company_store.canonical_categories_path()
    if not path.exists():
        return {k: dict(v) for k, v in SEED_CATEGORIES.items()}
    return json.loads(path.read_text())


def save_canonical_categories(categories: dict[str, dict]) -> None:
    path = company_store.canonical_categories_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(categories, indent=2, sort_keys=True))


def register_category(key: str, template: dict, overwrite: bool = False) -> dict[str, dict]:
    """Adds a brand-new category to the shared taxonomy -- called only
    from pipeline.confirm_onboarding_job(), only when a human reviewer
    explicitly asked for a new category to be registered (never
    automatically from a regex match or an LLM draft; see
    llm_classifier.py's docstring on why an LLM is never trusted to
    invent a category name on its own).

    Refuses to silently overwrite an existing key's template unless
    overwrite=True is passed explicitly -- a second company registering
    the same key with different numbers is a real conflict a human
    needs to resolve, not something to paper over.
    """
    categories = load_canonical_categories()
    if key in categories and not overwrite:
        raise ValueError(
            f"Category {key!r} already exists in the canonical taxonomy with a different "
            f"template. Pass overwrite=True if this is a deliberate correction, or choose "
            f"a different key."
        )
    categories[key] = template
    save_canonical_categories(categories)
    return categories


def get_category(key: str) -> Optional[dict]:
    return load_canonical_categories().get(key)