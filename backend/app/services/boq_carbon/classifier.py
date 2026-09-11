"""Keyword/regex material classifier for embodied-carbon calculation.

Deliberately NOT full item-code standardization against a SAP-style
reference sheet -- that was built and measured earlier (a TF-IDF + GloVe
ensemble matcher, then LLM-reranked) and topped out at 58% real accuracy
even after reranking, against a ~7,000-item reference list. Carbon
calculation is a much coarser, easier problem: it only needs material +
grade/cement-type + quantity, not an exact SAP code, so a precision
keyword classifier over about ten categories is both simpler and more
auditable than 7,000-way retrieval.

Category set mirrors and extends app/services/boq_extractor.py's
CATEGORY_HEADER_PATTERNS (which distinguishes 'rcc' from 'pcc' -- plain/
blinding concrete has a real, much lower reinforcement-adjacent carbon
profile than structural reinforced concrete, so keeping them separate
matters), adding the finish/envelope categories boq_extractor.py doesn't
yet cover (brickwork, blockwork, plaster, tile, paint, aluminium/glazing,
glass) since those matter for a full-BOQ per-line calculation the way
they don't for boq_extractor.py's narrower section-total use case.

--- Steel-section tiering (added after two real misclassifications) ---
Diagnosed via scripts/diagnose_coverage_gaps.py against real Botanico/
Ecopolitan BOQs:

  1. A genuine gypsum PLASTER line (row 1209, Botanico) was misclassified
     as structural_steel. Its own long free-text spec happened to end
     with an unrelated bundled painting-work note that, in turn, warned
     installers to protect "MS Railing works" during painting -- an
     incidental safety-note mention, not a description of the item being
     priced. Because the old single-tier steel-section pattern included
     "ms railing"/"ms grill" and was checked before plaster, that
     incidental phrase won and the entire plaster quantity was dropped.

  2. A genuine MS-fabricated drain-grating STEEL item (row 754,
     Botanico) was misclassified as paint. Its own spec is unambiguous
     steel fabrication ("MS fabricated ramp drain grating... MS pipes...
     MS flats... MS angles...") but ends with a routine finishing clause
     ("...painting two coats of enamel paint over a coat of primer").
     The old steel-section pattern didn't recognize generic "MS
     fabricated/flats/pipes/angles" language, so the item fell through
     to the paint check, which matched "enamel" on the finishing clause.

Fix: split steel-section matching into two tiers. STRONG patterns
(structural steel, ms section, i-section, angle iron, steel truss/
column/beam, and now also generic MS-fabrication language like "ms
fabricat*", "ms flat", "ms angle", "ms pipe", "ms plate", "ms channel",
"ms grating", "ms bracket") are checked FIRST, before plaster/tile/paint
-- these terms reliably describe the item itself, not an incidental
mention. WEAK patterns ("ms railing", "ms grill" -- terms that showed up
as incidental protective-note mentions in real BOQs, not as reliable
signals of the item being priced) are checked LAST, after every other
category has had a chance to match on its own more specific keyword --
so a genuine "supply and fix MS railing to staircase" item is still
caught (nothing else would match it), but an incidental "protect the MS
railing" aside inside an unrelated plaster/paint item no longer
steals it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_RCC_RE = re.compile(
    r"\b(rmc|ready\s*mix\s*concrete|rcc|reinforced\s*cement\s*concrete|in-?situ\s+concrete)\b", re.I
)
_PCC_RE = re.compile(
    r"\b(pcc|plain\s*cement\s*concrete|blinding\s*concrete|levelling\s*concrete|leveling\s*concrete)\b", re.I
)
# A bare "M25 grade concrete" with no RCC/PCC keyword nearby defaults to
# RCC (structural), since plain/blinding concrete is almost always
# explicitly labeled PCC/blinding in real BOQs, while structural RCC is
# the far more common unlabeled case.
_GENERIC_CONCRETE_RE = re.compile(r"\bm\d{2}\s*grade\s*concrete\b|\bconcrete\b", re.I)

_STEEL_REBAR_RE = re.compile(
    r"\b(tmt|reinforcement|rebar|fe\d{3}|steel\s*bars?|binding\s*wire)\b", re.I
)
# STRONG steel-section signals -- reliable, checked early (before plaster/
# tile/paint). See module docstring for why generic "ms fabricat/flat/
# angle/pipe/plate/channel/grating/bracket" terms were added here.
_STEEL_SECTION_STRONG_RE = re.compile(
    r"\b(structural\s*steel|ms\s*section|i-?\s*section|angle\s*iron|"
    r"steel\s*truss|steel\s*column|steel\s*beam|"
    r"ms\s*fabricat\w*|ms\s*flats?|ms\s*angles?|ms\s*pipes?|ms\s*plates?|"
    r"ms\s*channels?|ms\s*grating|ms\s*bracket\w*)\b", re.I
)
# WEAK steel-section signals -- real steel terms, but seen colliding with
# incidental protective/safety-note mentions in other trades' boilerplate
# in both real BOQs checked so far. Checked LAST (see module docstring).
_STEEL_SECTION_WEAK_RE = re.compile(r"\b(ms\s*railing|ms\s*grill)\b", re.I)
_BRICK_RE = re.compile(r"\b(brick\s*work|burnt\s*clay\s*brick|clay\s*brick)\b", re.I)
_BLOCK_RE = re.compile(r"\b(aac\s*block|block\s*work|solid\s*block|concrete\s*block|fly\s*ash\s*brick)\b", re.I)
# "plaster\w*" (not "plaster\b") deliberately -- confirmed via
# diagnose_coverage_gaps.py against real Botanico/Ecopolitan BOQs that
# the word-bounded "\bplaster\b" silently fails to match the extremely
# common gerund form "Plastering" ("Internal Plastering works", "cement
# plastering 12mm thick"): there's a word boundary before "plaster" but
# NOT between "plaster" and the following "ing", so \b right after the
# literal "plaster" never matches inside "Plastering". Real cost on
# Botanico alone: 34 lines / ~16,185 sqm of genuine plaster work
# silently dropped to unclassified. "rendering"/"screed" don't have the
# same gerund-collision problem in either real BOQ checked so far, so
# they keep the tighter \b on both sides.
_PLASTER_RE = re.compile(r"\b(plaster\w*|rendering|screed)\b", re.I)
_TILE_RE = re.compile(r"\b(tile|tiling|granite|marble|vitrified|ceramic)\b", re.I)
_PAINT_RE = re.compile(r"\b(paint|distemper|primer|enamel|emulsion|putty|white\s*wash)\b", re.I)
_ALU_RE = re.compile(r"\b(aluminium|aluminum|alucobond|upvc\s*window)\b", re.I)
_GLASS_RE = re.compile(r"\bglass|glazing\b", re.I)
# Timber -- deliberately NOT a bare "wood\w*" match. Checked against both
# real BOQs (Ecopolitan: 75 genuine hits, all door/window-frame joinery
# items; Botanico: 0) before choosing this pattern: a bare "wood\w*" also
# matches "wooden/steel rammers" inside an EARTHWORK backfilling item's
# boilerplate ("...compacting each layer... with wooden/steel rammers...")
# -- an incidental tool mention, not the item's material. That specific
# row is already caught by _EARTHWORK_RE regardless, but requiring
# "wood(en)?" to be followed by a joinery-product noun (frame/door/
# window/shutter/panel/jamb/chowkhat) avoids the same class of false
# positive on any future BOQ that mentions a wooden tool/prop without an
# earthwork context to save it. Product-form terms (plywood, particle
# board, mdf, veneer, etc.) are matched bare since they're already
# specific enough not to need the same guard.
_TIMBER_RE = re.compile(
    r"\b(timber|plywood|particle\s*board|chip\s*board|mdf|block\s*board|veneer|"
    r"flush\s*door|teak\s*wood|"
    r"(?:solid|engineered)\s*wood\s*(?:frame|door|window|shutter|panel)|"
    r"wood(?:en)?\s*(?:frame|door|window|shutter|panel|chowkhat|jamb))\b", re.I
)

_CEMENT_TYPE_PSC_RE = re.compile(r"\b(ggbs|slag\s*cement|psc)\b", re.I)
_CEMENT_TYPE_PPC_RE = re.compile(r"\b(fly\s*ash|flyash|ppc|pozzolana)\b", re.I)
_CEMENT_TYPE_OPC_RE = re.compile(r"\b(opc|ordinary\s*portland)\b", re.I)

_GRADE_RE = re.compile(r"\bm\s?(\d{2})\b", re.I)

# Earthwork/excavation -- excluded the same way formwork is, checked
# BEFORE concrete matching. Confirmed as a real bug on a real BOQ: an
# excavation line's OWN description included a measurement note ("PCC
# area shall be considered for measurement...") referencing PCC only to
# explain how the EXCAVATION quantity should be measured, not because
# the line itself delivers any concrete -- that one incidental word match
# was enough to misclassify a large excavation volume as PCC concrete
# and price it as such. Excavation/earthwork isn't a category this engine
# models at all yet, so any line whose own text is dominated by an
# excavation signal is excluded rather than risk this same false-positive
# collision again.
#
# Deliberately narrow to "excavat" ONLY -- a first version also matched
# "dewatering" and "earth work", and that broke something real: a huge
# fraction of ordinary BOQ line items (including the actual main
# reinforcement-steel line item) carry generic catch-all boilerplate like
# "...including dewatering wherever necessary..." regardless of what
# work they actually describe, and "EARTH WORKS" is also just this
# file's section-header text sitting in the context of every row under
# it, not a signal about the row itself. "excavat" alone doesn't have
# that boilerplate-collision problem in either real BOQ checked so far.
_EARTHWORK_RE = re.compile(r"\bexcavat", re.I)

# Formwork/shuttering/centering -- reusable temporary construction plant,
# not material incorporated into the permanent structure. MUST be checked
# before every other category: a real line like "Aluminium System
# Formwork" would otherwise be tagged 'aluminium' and its (large,
# per-floor-repeated) shuttering CONTACT area priced as if it were
# permanent aluminium building stock. Confirmed as a real bug on a real
# BOQ: this single mis-tag accounted for 58% of that project's entire
# (badly inflated) calculated total before this exclusion was added.
#
# --- "Own item vs. incidental mention" tiering (added after a second
# real collision, same species as the MS-railing/plaster one documented
# in the module docstring) ---
#
# Diagnosed via a direct check against real Ecopolitan/Botanico BOQs: a
# genuine 100mm block-masonry-wall item (row 820, Ecopolitan) and two
# genuine PCC pour items (rows 53/55, Ecopolitan) were all being dropped
# to unclassified because their own long scope-of-work sentences end with
# routine boilerplate like "...including shuttering, necessary
# scaffolding, staging..." or "...form work wherever necessary,
# levelling, compacting, curing...". That's the item describing HOW it
# gets built, not what it delivers -- the same incidental-mention problem
# already solved for steel sections, now showing up for formwork against
# concrete/block/plaster items instead.
#
# Checked directly against both real BOQs before choosing a fix: every
# genuine formwork/shuttering LINE ITEM (the row IS formwork, e.g.
# "STRUCTURE WORKS | FORM WORK | CONVENTIONAL SHUTTERING | 4th floor")
# carries the formwork word inside a short hierarchy/header segment (9-23
# characters in every real example seen -- "FORM WORK", "CONVENTIONAL
# SHUTTERING"). Every incidental collision seen carries it deep inside a
# long free-text scope sentence (384-873+ characters in the real examples
# seen). That length gap is wide and consistent across both files, so
# instead of a keyword-level STRONG/WEAK split (that already worked for
# steel, but formwork has no equivalent narrower phrase to key on -- both
# the genuine and incidental uses are the same bare words "shuttering"/
# "form work"), the split here is structural: does the match fall inside
# a short, header-like " | "-delimited segment of enriched_description
# (a real formwork item's own section/category/leaf label), or only
# inside a long descriptive paragraph (another item's boilerplate
# scope-of-work note)? 60 characters sits comfortably between the two
# real clusters seen (<=23 vs >=384) with no examples anywhere near that
# boundary in either file, so it's not a tight/fragile cutoff.
_FORMWORK_RE = re.compile(r"\b(form\s*work|formwork|shuttering|centering|centring)\b", re.I)
_FORMWORK_HEADER_SEGMENT_MAX_LEN = 60


def _is_own_item_formwork(text: str) -> bool:
    """True only when the formwork/shuttering/centering signal falls
    inside a short, header-like segment of the row's own hierarchy path
    -- i.e. the row IS a formwork item -- not merely mentioned somewhere
    inside a long scope-of-work sentence belonging to a different
    (concrete/block/plaster/etc.) item. See the comment above for the
    real-BOQ evidence behind the 60-character threshold.
    """
    return any(
        len(segment) <= _FORMWORK_HEADER_SEGMENT_MAX_LEN and _FORMWORK_RE.search(segment)
        for segment in text.split(" | ")
    )

# Maps to ice_db_factors.json's ifc_india.concrete.by_cement_type keys.
CEMENT_TYPE_OPC = "OPC"
CEMENT_TYPE_PSC = "PSC"
CEMENT_TYPE_PPC = "PPC"

CATEGORY_RCC = "rcc"
CATEGORY_PCC = "pcc"
CATEGORY_STEEL_REBAR = "reinforcement_steel"
CATEGORY_STEEL_SECTION = "structural_steel"
CATEGORY_BRICK = "brickwork"
CATEGORY_BLOCK = "blockwork"
CATEGORY_PLASTER = "plaster"
CATEGORY_TILE = "tile"
CATEGORY_PAINT = "paint"
CATEGORY_ALUMINIUM = "aluminium_glazing"
CATEGORY_GLASS = "glass"
CATEGORY_TIMBER = "timber"

# Order matters: steel checked before concrete, since a rebar line's
# hierarchy context frequently mentions "RCC"/"Reinforced Cement
# Concrete" (the section it lives under) even though the LINE ITSELF is
# steel -- without this ordering the generic concrete match would win
# and steel tonnage would get silently double-counted as concrete volume.
#
# STEEL_SECTION_WEAK sits at the END of this list, not alongside
# STEEL_SECTION_STRONG near the top -- see module docstring's "Steel-
# section tiering" section for why.
_ORDERED_RULES: list[tuple[str, re.Pattern]] = [
    (CATEGORY_STEEL_REBAR, _STEEL_REBAR_RE),
    (CATEGORY_STEEL_SECTION, _STEEL_SECTION_STRONG_RE),
    (CATEGORY_PCC, _PCC_RE),  # PCC checked before RCC/generic: more specific
    (CATEGORY_RCC, _RCC_RE),
    (CATEGORY_BRICK, _BRICK_RE),
    (CATEGORY_BLOCK, _BLOCK_RE),
    (CATEGORY_TIMBER, _TIMBER_RE),
    (CATEGORY_PLASTER, _PLASTER_RE),
    (CATEGORY_TILE, _TILE_RE),
    (CATEGORY_PAINT, _PAINT_RE),
    (CATEGORY_ALUMINIUM, _ALU_RE),
    (CATEGORY_GLASS, _GLASS_RE),
    (CATEGORY_STEEL_SECTION, _STEEL_SECTION_WEAK_RE),
]


@dataclass
class MaterialClassification:
    category: Optional[str]
    cement_type: Optional[str] = None  # concrete (rcc/pcc) only
    grade: Optional[str] = None  # concrete (rcc/pcc) only, e.g. "M25"


def classify_material(enriched_description: str) -> MaterialClassification:
    text = str(enriched_description)

    if _is_own_item_formwork(text) or _EARTHWORK_RE.search(text):
        return MaterialClassification(category=None)

    category: Optional[str] = None
    for cat, pattern in _ORDERED_RULES:
        if pattern.search(text):
            category = cat
            break

    if category is None and _GENERIC_CONCRETE_RE.search(text):
        category = CATEGORY_RCC  # unlabeled concrete defaults to structural RCC, see module docstring

    cement_type = None
    grade = None
    if category in (CATEGORY_RCC, CATEGORY_PCC):
        if _CEMENT_TYPE_PSC_RE.search(text):
            cement_type = CEMENT_TYPE_PSC
        elif _CEMENT_TYPE_PPC_RE.search(text):
            cement_type = CEMENT_TYPE_PPC
        elif _CEMENT_TYPE_OPC_RE.search(text):
            cement_type = CEMENT_TYPE_OPC
        else:
            # Most common unstated default in current Indian RMC practice
            # -- same placeholder choice app/services/llm_fallback.py
            # already makes for the tiered estimator, kept consistent
            # rather than picking a different default here.
            cement_type = CEMENT_TYPE_PPC

        m = _GRADE_RE.search(text)
        grade = f"M{m.group(1)}" if m else ("M10" if category == CATEGORY_PCC else "M30")

    return MaterialClassification(category=category, cement_type=cement_type, grade=grade)