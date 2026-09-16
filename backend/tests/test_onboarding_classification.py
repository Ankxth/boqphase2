"""Workstream 05: unit tests for the generalized classification pipeline
(app/services/onboarding/classification_pipeline.py) and the canonical
category taxonomy it reads from.

Deliberately uses small, synthetic master dicts rather than the real
Ecopolitan dataset -- these are the same regex/keyword decisions the
original scripts/enhance_master_classification.py already made
(verified against 5,301 real need_review rows in an earlier session),
so re-proving them here on tiny fixtures is about locking in the
GENERALIZED plumbing (in-memory dict in, canonical_categories-sourced
templates, no hardcoded paths) rather than re-discovering the domain
logic. Fast, and portable to any machine -- no dependency on the real
reference documents under app/data/.
"""

from __future__ import annotations

import pytest

from app.services import company_store
from app.services.onboarding import canonical_categories
from app.services.onboarding.classification_pipeline import run_classification_pass


@pytest.fixture(autouse=True)
def isolated_canonical_categories(tmp_path, monkeypatch):
    # canonical_categories_path() derives from COMPANIES_DIR.parent (see
    # company_store.py's own docstring on why) -- one monkeypatch
    # isolates both, same pattern as tests/test_company_storage.py.
    monkeypatch.setattr(company_store, "COMPANIES_DIR", tmp_path / "companies")
    yield


def _row(desc: str, unit: str, contributes: str = "need_review") -> dict:
    return {
        "desc": desc, "unit": unit, "contributes": contributes,
        "material_category": None, "top5": "no", "ef_kgco2e_per_kg": None,
        "ef_source": None, "cea_adjusted": None, "evidence_tier": None,
        "unit_note": "pending",
    }


def test_admin_prefix_excludes_row_with_no_material_keyword():
    master = {"A1": _row("Prl-Site cleaning and surveying", "LS")}
    run_classification_pass(master)
    assert master["A1"]["contributes"] == "no"
    assert master["A1"]["material_category"] is None


def test_admin_prefix_override_kept_when_material_keyword_present():
    # Same prefix, but the description also names a real material --
    # must NOT be bulk-excluded (the override scan from the original
    # script), left need_review instead of guessed.
    master = {"A2": _row("Prl-Openable MS Gate supply", "LS")}
    run_classification_pass(master)
    assert master["A2"]["contributes"] == "need_review"


def test_concrete_reclassified_with_grade_noted_but_not_in_material_category():
    # material_category must stay the bare canonical "concrete" --
    # wo_carbon_engine.py's _resolve_ef() does an EXACT match against it
    # and re-detects the grade independently from the row's own `desc`
    # text, so a grade-suffixed material_category would silently break
    # EF resolution (see canonical_categories.py's module docstring for
    # the real bug this test now guards against). The grade is still
    # captured, just in unit_note (documentation only).
    master = {"C1": _row("RCC M30 grade footing", "CUM")}
    run_classification_pass(master)
    row = master["C1"]
    assert row["contributes"] == "yes"
    assert row["top5"] == "yes"
    assert row["material_category"] == "concrete"
    assert "M30" in row["unit_note"]
    assert row["ef_kgco2e_per_kg"] == canonical_categories.SEED_CATEGORIES["concrete"]["ef_kgco2e_per_kg"]


def test_concrete_without_grade_leaves_material_category_bare():
    master = {"C2": _row("PCC 1:3:6 bed concrete", "CUM")}
    run_classification_pass(master)
    assert master["C2"]["material_category"] == "concrete"
    assert "Grade detected" not in master["C2"]["unit_note"]


def test_structural_steel_reclassified():
    master = {"S1": _row("MS Angle/Box section handrail frame", "KGS")}
    run_classification_pass(master)
    row = master["S1"]
    assert row["contributes"] == "yes"
    assert row["material_category"] == "structural_steel"
    assert row["ef_kgco2e_per_kg"] == canonical_categories.SEED_CATEGORIES["structural_steel"]["ef_kgco2e_per_kg"]


def test_gi_reclassified():
    master = {"G1": _row("GI strip 25x3mm", "KG")}
    run_classification_pass(master)
    assert master["G1"]["material_category"] == "steel_gi_galvanized"


def test_stainless_steel_requires_nearby_fixture_word():
    # SS + a qualifying nearby noun -> classified.
    master = {
        "SS1": _row("SS Wall Handrail -Staircase", "KG"),
        # SS present but no qualifying nearby noun in this description --
        # must stay need_review, not guessed.
        "SS2": _row("SS specification cross-check note, general", "KG"),
    }
    run_classification_pass(master)
    assert master["SS1"]["material_category"] == "steel_stainless"
    assert master["SS2"]["contributes"] == "need_review"


def test_paint_and_gypsum_reclassified():
    master = {
        "P1": _row("OBD - Ceiling, two coats", "SQM"),
        "GY1": _row("Gypsum plaster cornice work", "SQM"),
    }
    run_classification_pass(master)
    assert master["P1"]["material_category"] == "paint"
    assert master["GY1"]["material_category"] == "plaster_gypsum"


def test_dimension_mining_assigns_mass_and_steel_ef_for_steel_keyword():
    master = {"D1": _row("MS strip 50x30x6mm bracket", "NOS")}
    run_classification_pass(master)
    row = master["D1"]
    assert row["contributes"] == "yes"
    assert row["kg_per_unit"] is not None
    assert row["material_category"] == "structural_steel"  # bare canonical key, not suffixed -- see module docstring
    assert "Dimension-mined" in row["unit_note"]  # provenance preserved here instead
    assert row["evidence_tier"] == "assumed_dimension_density"


def test_dimension_mining_leaves_unrecognized_2d_product_as_need_review():
    # A 2D dimension with no recognized product-type marker (no FR-door
    # signal) -- must NOT be guessed, same as the original script's
    # documented behavior for e.g. plain doors.
    master = {"D2": _row("Plain flush door 900x2100mm", "NOS")}
    run_classification_pass(master)
    assert master["D2"]["contributes"] == "need_review"


def test_weight_table_candidate_flagged_not_auto_applied():
    master = {"W1": _row("ISMB200 structural section, ext PHE support", "RMT")}
    run_classification_pass(master)
    row = master["W1"]
    # Flagged, but NOT auto-classified to "yes" -- the whole point of
    # Step D being a flag, not an apply.
    assert row["contributes"] == "need_review"
    assert "IS 808" in row["quantifiability_note"]
    assert "MEP-context marker found" in row["quantifiability_note"]  # "PHE" triggers MEP context


def test_quantifiability_tagging_by_unit():
    master = {
        "Q1": _row("Unrecognized lump sum item", "LS"),
        "Q2": _row("Unrecognized count item", "NOS"),
        "Q3": _row("Unrecognized weird-unit item", "XYZ"),
    }
    run_classification_pass(master)
    assert master["Q1"]["quantifiability"] == "permanently_unquantifiable"
    assert master["Q2"]["quantifiability"] == "solvable_pending"
    assert master["Q3"]["quantifiability"] == "unclassified_material"


def test_already_resolved_rows_are_never_touched():
    master = {
        "Y1": {"desc": "Already yes", "unit": "KG", "contributes": "yes", "material_category": "hand_classified", "ef_kgco2e_per_kg": 1.23},
        "N1": {"desc": "Already no", "unit": "LS", "contributes": "no", "material_category": None},
    }
    before = {k: dict(v) for k, v in master.items()}
    run_classification_pass(master)
    assert master == before


def test_register_category_then_available_to_next_classification_pass(tmp_path):
    # A brand-new category registered via the confirm flow should be
    # visible to canonical_categories on the very next read -- proving
    # the "grows and is shared" half of the design, independent of the
    # regex pass (which doesn't auto-recognize brand-new categories --
    # see classification_pipeline.py's own docstring on that limit).
    canonical_categories.register_category("timber_formwork", {
        "contributes": "yes", "top5": "no", "ef_kgco2e_per_kg": 0.5,
        "ef_source": "Test-only fixture value.", "cea_adjusted": "no",
        "evidence_tier": "test_fixture", "material_category": "timber_formwork",
        "unit_note": "test",
    })
    categories = canonical_categories.load_canonical_categories()
    assert "timber_formwork" in categories
    assert categories["timber_formwork"]["ef_kgco2e_per_kg"] == 0.5


def test_register_category_refuses_silent_overwrite():
    canonical_categories.register_category("custom_x", {"ef_kgco2e_per_kg": 1.0})
    with pytest.raises(ValueError):
        canonical_categories.register_category("custom_x", {"ef_kgco2e_per_kg": 2.0})
    # overwrite=True is an explicit escape hatch.
    canonical_categories.register_category("custom_x", {"ef_kgco2e_per_kg": 2.0}, overwrite=True)
    assert canonical_categories.load_canonical_categories()["custom_x"]["ef_kgco2e_per_kg"] == 2.0


def test_classified_categories_actually_resolve_in_wo_carbon_engine():
    """Regression test for the real bug this workstream shipped and then
    fixed: an earlier version of canonical_categories.py set
    material_category to strings ("steel_structural", "plaster
    (gypsum)", a grade-suffixed "concrete (...)") that LOOK right but
    don't exactly match the live canonical keys
    wo_carbon_engine.py._resolve_ef() actually checks against -- so a
    newly onboarded company's concrete/steel/gypsum rows would silently
    never compute a real number. This test drives every classified
    category through the REAL _resolve_ef() (not a re-implementation of
    its logic) and asserts a real, non-None emission factor comes back
    -- the only test in this suite that would have caught the original
    bug, so it stays even though the fixtures above already check the
    string values directly.
    """
    from app.services.wo_carbon.wo_carbon_engine import _resolve_ef

    master = {
        "T1": _row("RCC M30 grade footing", "CUM"),
        "T2": _row("MS Angle/Box section handrail frame", "KGS"),
        "T3": _row("GI strip 25x3mm", "KG"),
        "T4": _row("SS Wall Handrail -Staircase", "KG"),
        "T5": _row("OBD - Ceiling, two coats", "SQM"),
        "T6": _row("Gypsum plaster cornice work", "SQM"),
        "T7": _row("MS strip 50x30x6mm bracket", "NOS"),  # dimension-mined
    }
    run_classification_pass(master)

    for code, row in master.items():
        assert row["contributes"] == "yes", f"{code} ({row['desc']!r}) did not classify to yes"
        ef, note, evidence_tier = _resolve_ef(row["material_category"], row["desc"])
        assert ef is not None, (
            f"{code}: material_category {row['material_category']!r} did not resolve to a real "
            f"emission factor in the live engine ({note!r}) -- this is exactly the bug this test guards against."
        )