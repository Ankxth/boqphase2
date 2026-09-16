"""Regression tests for app/services/boq_carbon/classifier.py, pinned
directly to real bugs found and fixed against real Ecopolitan/Botanico
BOQs (see classifier.py's module docstring and its inline comments above
_ORDERED_RULES / _is_own_item_formwork for the full write-up of each).

These are deliberately NOT golden-file tests -- they're small, targeted,
human-readable unit cases that pin the exact classification behaviour a
future refactor (e.g. Workstream 01's factor-source unification, which
touches this same module's neighbours) must not silently break. Unlike
the golden-file tests, a failure here should almost never be "resolved"
by just accepting the new output -- these are edge cases that were
specifically hand-verified against a real BOQ row, not just "whatever
the code currently does".

Each case names the real bug it guards against in its test name and
docstring.
"""

from __future__ import annotations

from app.services.boq_carbon.classifier import (
    CATEGORY_ALUMINIUM,
    CATEGORY_BLOCKWORK_AAC,
    CATEGORY_BLOCKWORK_DENSE,
    CATEGORY_NATURAL_STONE,
    CATEGORY_PCC,
    CATEGORY_PLASTER_CEMENT,
    CATEGORY_PLASTER_GYPSUM,
    CATEGORY_RCC,
    CATEGORY_STEEL_SECTION,
    CATEGORY_TILE_CERAMIC,
    CATEGORY_UPVC,
    classify_material,
)


def test_ms_railing_incidental_mention_does_not_steal_plaster():
    """Real bug (Botanico row 1209): a genuine gypsum plaster item whose
    own free-text spec ends with an unrelated bundled painting-work note
    warning installers to protect "MS Railing works" during painting.
    Because the incidental mention comes after the plaster keyword in a
    long scope sentence, and the WEAK steel-section pattern is checked
    LAST (after plaster has already had its chance), the item must
    classify as plaster, not structural_steel.
    """
    text = (
        "INTERNAL FINISHES | PLASTERING | 12mm thick gypsum plaster to internal walls "
        "and ceilings as per specification, including all materials, labour, scaffolding "
        "and curing, and protect adjoining MS Railing works from paint/plaster droppings "
        "during execution"
    )
    result = classify_material(text)
    # Workstream 07: category is now the split, canonical value -- this
    # line's own text says "gypsum", so it must resolve to
    # plaster_gypsum, not the generic plaster bucket that used to exist.
    assert result.category == CATEGORY_PLASTER_GYPSUM


def test_genuine_ms_railing_item_still_classifies_as_steel():
    """The WEAK steel-section tier exists precisely so a genuine railing
    item (nothing else in it would match any other category) is still
    caught, even though it's checked last.
    """
    text = "STEEL WORKS | RAILINGS | Supply and fix MS railing to staircase, painted finish"
    result = classify_material(text)
    assert result.category == CATEGORY_STEEL_SECTION


def test_ms_fabricated_drain_grating_does_not_steal_paint():
    """Real bug (Botanico row 754): a genuine MS-fabricated drain-grating
    steel item ends with a routine finishing clause ("...painting two
    coats of enamel paint over a coat of primer"). The STRONG
    steel-section tier (which now recognizes generic "ms fabricat*/ms
    flats/ms angles/..." language) is checked before paint, so this must
    classify as structural_steel, not paint.
    """
    text = (
        "DRAINAGE WORKS | MS fabricated ramp drain grating using MS pipes, MS flats, "
        "MS angles as per drawing, including painting two coats of enamel paint over "
        "a coat of primer"
    )
    result = classify_material(text)
    assert result.category == CATEGORY_STEEL_SECTION


def test_formwork_as_own_item_header_is_excluded_not_misclassified():
    """A genuine formwork/shuttering LINE ITEM (the row IS formwork,
    plant/temporary works, not permanent material) must be excluded from
    every category (category is None) -- confirmed as a real bug where
    "Aluminium System Formwork" as its own line item, if not excluded,
    would otherwise be wrongly counted as permanent aluminium stock (58%
    of one real project's inflated total, per classifier.py's comment).
    The signal is structural: the formwork keyword sits inside a short
    " | "-delimited header segment, not buried in a long scope sentence.
    """
    text = "STRUCTURE WORKS | FORM WORK | Aluminium System Formwork | 4th floor"
    result = classify_material(text)
    assert result.category is None


def test_formwork_mentioned_incidentally_in_scope_note_does_not_exclude_the_real_item():
    """Real bug (Ecopolitan rows 53/55, 820): genuine PCC and blockwork
    items were being wrongly dropped to unclassified because their own
    long scope-of-work sentences end with routine boilerplate like
    "...including shuttering, necessary scaffolding, staging, form work
    wherever necessary, levelling, compacting, curing...". Since that
    mention sits inside a long free-text paragraph (not a short header
    segment), it must NOT trigger the formwork exclusion -- the item is
    genuinely PCC and must classify as such.
    """
    text = (
        "CONCRETE WORKS | PLAIN CEMENT CONCRETE | Providing and laying PCC M10 grade "
        "below foundation as per drawing and specification, including all materials, "
        "shuttering, necessary scaffolding, staging, form work wherever necessary, "
        "levelling, compacting, curing and all other incidental works complete"
    )
    result = classify_material(text)
    assert result.category == CATEGORY_PCC


def test_pcc_is_not_misclassified_as_rcc():
    """PCC (plain/blinding concrete, no reinforcement) has a much lower
    carbon profile than RCC and must never collapse into the generic RCC
    bucket -- CATEGORY_PCC is checked before CATEGORY_RCC in
    _ORDERED_RULES specifically because it's the more specific match.
    """
    text = "SUBSTRUCTURE | Providing and laying plain cement concrete (PCC) 1:4:8 below footing"
    result = classify_material(text)
    assert result.category == CATEGORY_PCC


def test_plaster_gerund_form_matches():
    """_PLASTER_RE deliberately uses 'plaster\\w*' (not 'plaster\\b') so
    that gerund/inflected forms like "plastering" match too -- confirmed
    against real BOQ section headers that use the -ing form rather than
    the bare noun. No gypsum/POP keyword here, so this must resolve to
    the cement-based default (plaster_cement), not plaster_gypsum.
    """
    text = "FINISHES | Plastering to external walls, sand-faced finish, 15mm thick"
    result = classify_material(text)
    assert result.category == CATEGORY_PLASTER_CEMENT


def test_earthwork_excavation_is_excluded():
    """Excavation/earthwork is temporary/site-prep work, not a permanent
    material incorporated into the structure -- must classify as None,
    the same "not a materials line" treatment formwork gets.
    """
    text = "EARTHWORK | Excavation for foundation in all types of soil up to 3m depth"
    result = classify_material(text)
    assert result.category is None


def test_aluminium_glazing_classifies_correctly():
    """Sanity check for a category with no documented collision history,
    included so the ordered-rule list has at least one passing case per
    category represented here. (Workstream 07: this used to bundle a
    "with UPVC window" clause into the same text to also sanity-check the
    aluminium/uPVC family match -- split into its own dedicated test
    below now that aluminium and uPVC resolve to different final
    categories, since a real BOQ line essentially never describes both
    materials in one row the way that contrived text did.)
    """
    text = "DOORS AND WINDOWS | Supply and fix aluminium powder-coated window frame, 2-track sliding"
    result = classify_material(text)
    assert result.category == CATEGORY_ALUMINIUM


# --- Workstream 07: four deferred classifier splits ---
# Each pins the real factor-gap fix described in classifier.py's own WS07
# section docstring, against real-world phrasing confirmed present in the
# production master item-code dataset (see canonical_categories.py /
# WS06's migration for that verification).


def test_upvc_window_does_not_get_priced_as_aluminium():
    """Real gap (7.4x factor difference, aluminium 28.76 vs
    upvc_window_door_frame 3.86621 kgCO2e/kg): a uPVC window/door line
    must resolve to its own category, not aluminium's."""
    text = "DOORS AND WINDOWS | UPVC Sliding Window, 2-track, white finish"
    result = classify_material(text)
    assert result.category == CATEGORY_UPVC


def test_granite_flooring_does_not_get_priced_as_ceramic_tile():
    """Real gap (2.2x factor difference, tile_ceramic 0.62905 vs
    natural_stone 0.28514 kgCO2e/kg): a granite/marble line must resolve
    to natural_stone, not the generic tile bucket."""
    text = "FLOORING | Granite Stone Flooring 20mm thick, polished, as per specification"
    result = classify_material(text)
    assert result.category == CATEGORY_NATURAL_STONE


def test_vitrified_tile_still_resolves_to_tile_ceramic_default():
    """Confirms the tile/stone split didn't disturb the ordinary tile
    case -- no granite/marble keyword here, so this stays on the
    (unchanged) ceramic/vitrified default."""
    text = "FLOORING | Vitrified tile flooring 600x600mm, matt finish"
    result = classify_material(text)
    assert result.category == CATEGORY_TILE_CERAMIC


def test_solid_concrete_block_does_not_get_priced_as_aac():
    """Real gap (~3x factor difference, blockwork_aac 0.49284 vs
    blockwork_dense 0.15946 kgCO2e/kg): a line explicitly naming solid/
    dense/concrete block must resolve to blockwork_dense, not this
    classifier's AAC default."""
    text = "MASONRY | Solid concrete block masonry, 200mm thick, in CM 1:6"
    result = classify_material(text)
    assert result.category == CATEGORY_BLOCKWORK_DENSE


def test_generic_block_work_still_resolves_to_aac_default():
    """Confirms the blockwork split didn't disturb the ordinary case --
    no solid/dense/concrete-block keyword here, so this stays on the
    (unchanged) AAC default (see emission_factors.json's blockwork_aac
    '_reconciliation' note for why AAC is the sensible unqualified
    default)."""
    text = "MASONRY | AAC block work, 200mm thick, in CM 1:6"
    result = classify_material(text)
    assert result.category == CATEGORY_BLOCKWORK_AAC