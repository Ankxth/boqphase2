"""Workstream 08: tests for the new shared app/services/supplier_catalog.py
module -- the "one shared data layer" both Phase 1 (substitution.py) and
Phase 2 (boq_carbon/substitution_engine.py) now read through. Also covers
the backward-compatible delegator left behind at
app/services/boq_carbon/substitution_catalog.py, since nothing that
already imported from that path should have broken.

Not a golden-value test file -- no carbon numbers are asserted here (see
test_substitution.py and the existing boq_carbon golden tests for that).
This file is about the catalog's own shape and the pre-existing sourced
data surviving the Workstream 08 restructure unchanged.
"""

from __future__ import annotations

from app.services import supplier_catalog


def test_load_catalog_still_has_all_four_pre_existing_entries():
    ids = {e["id"] for e in supplier_catalog.load_catalog()}
    assert ids == {
        "opc_to_psc",
        "opc_to_ppc",
        "brick_to_aac_block",
        "steel_ifc_to_ars_eaf_recycled",
    }


def test_get_entry_known_and_unknown_id():
    assert supplier_catalog.get_entry("brick_to_aac_block") is not None
    assert supplier_catalog.get_entry("not_a_real_id") is None


def test_list_categories_includes_all_three_base_categories():
    assert set(supplier_catalog.list_categories()) == {"rcc", "brickwork", "reinforcement_steel"}


def test_rcc_alternatives_are_recompute_via_engine_with_no_named_supplier():
    alts = supplier_catalog.list_alternatives_for_category("rcc")
    ids = {a.id for a in alts}
    assert ids == {"opc_to_psc", "opc_to_ppc"}
    for a in alts:
        assert a.basis == "recompute_via_engine"
        assert a.fixed_gwp_kgco2e_per_kg is None
        # Generic IS-code cement blends -- not tied to one named producer.
        assert a.supplier is None
        assert a.region is not None and "India" in a.region


def test_reinforcement_steel_alternative_has_named_supplier_and_fixed_factor():
    alts = supplier_catalog.list_alternatives_for_category("reinforcement_steel")
    assert len(alts) == 1
    alt = alts[0]
    assert alt.id == "steel_ifc_to_ars_eaf_recycled"
    assert alt.basis == "fixed_factor_per_kg"
    assert alt.fixed_gwp_kgco2e_per_kg == 0.592
    assert alt.supplier == "ARS Steels and Alloy International Pvt Ltd"
    assert "Tamil Nadu" in alt.region
    assert alt.evidence_tier == "supplier_epd_verified"
    assert alt.always_requires_review_if_load_bearing is True


def test_list_fixed_factor_alternatives_excludes_recompute_via_engine_entries():
    # rcc's two alternatives are both recompute_via_engine -- none should
    # come back from the fixed-factor-only view.
    assert supplier_catalog.list_fixed_factor_alternatives_for_category("rcc") == []
    fixed = supplier_catalog.list_fixed_factor_alternatives_for_category("reinforcement_steel")
    assert len(fixed) == 1
    assert fixed[0].id == "steel_ifc_to_ars_eaf_recycled"


def test_unknown_category_returns_empty_list_not_an_error():
    assert supplier_catalog.list_alternatives_for_category("not_a_real_category") == []
    assert supplier_catalog.list_entries_for_category("not_a_real_category") == []


def test_backward_compatible_delegator_reexports_same_data():
    from app.services.boq_carbon import substitution_catalog as old_module

    assert old_module.CATALOG_PATH == supplier_catalog.CATALOG_PATH
    assert old_module.load_catalog() == supplier_catalog.load_catalog()
    assert old_module.get_substitution("brick_to_aac_block") == supplier_catalog.get_entry("brick_to_aac_block")
    assert old_module.list_substitutions_for_category("rcc") == supplier_catalog.list_entries_for_category("rcc")