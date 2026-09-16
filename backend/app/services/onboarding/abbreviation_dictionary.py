"""Workstream 05: production copy, relocated from scripts/abbreviation_dictionary.py
verbatim (no logic changed) into app/services/onboarding/ so the live
onboarding pipeline can import it as a normal package module instead of
relying on scripts/ being on sys.path. The original scripts/ copy stays
in place unchanged, as the one-off script this was generalized from.

Reviewed abbreviation-expansion layer for the master item-code dataset's
Service Short Text descriptions, run BEFORE any classification/matching
step -- per the project's point-3 instruction: build this as its own
dedicated, reviewed layer instead of continuing to find abbreviations by
accident during cross-checks (as happened with "Conc", "brick masonry",
and "CU" in earlier passes).

Every entry below was verified against real sample rows pulled from the
Ecopolitan master dataset (5,301 `need_review` descriptions, mined with a
frequency-ranked `\\b[A-Z]{2,5}\\b` regex -- see the abbreviation-mining
step this module was built from) before being added here. Entries are
grouped by what they're used for:

  MATERIAL_ABBREVIATIONS   -- expands a material shorthand to its full
                               name so the existing category regexes (in
                               enhance_master_classification.py) can match
                               it. Conservative: only added where sample
                               rows showed it consistently meant the
                               stated material, and where a false-positive
                               would be structurally hard (word-boundary
                               matched, and several are gated on requiring
                               a companion noun -- see NOTES below).

  ADMIN_PREFIXES            -- description prefixes that mark a row as a
                               soft-cost / administrative / preliminaries
                               line with no physical material entering the
                               building (legal fees, security services,
                               IT licenses, event management, etc.) --
                               NOT a material abbreviation, but the same
                               "recognize the shorthand" idea applied to
                               scope exclusion. Every prefix here was
                               checked against ALL of its own rows (not a
                               sample) for an embedded material keyword
                               before being trusted as a bulk signal -- see
                               enhance_master_classification.py's
                               ADMIN_PREFIX_MATERIAL_OVERRIDE_KEYWORDS
                               safety net, which still applies on top of
                               this list.

  PUNCTUATED_ABBREVIATIONS  -- the same short codes written with periods
                               (P.C.C., R.C.C., M.S., G.I., S.S.) which the
                               original classifier's \\b...\\b word-boundary
                               regexes never matched because a period isn't
                               a word character. This alone explains why
                               "P.C.C. 1:3:6" (Rs 11.38M in the Ecopolitan
                               WO) was still sitting in need_review despite
                               the word "PCC" already being a recognized
                               concrete keyword elsewhere in the dataset.

  KNOWN_TYPOS                -- a small, explicit, one-off list of
                               confirmed misspellings found during manual
                               review (e.g. "Gyspum" for "Gypsum"). This is
                               NOT a fuzzy matcher -- deliberately so, per
                               the project's own prior finding that a
                               TF-IDF/GloVe/LLM matcher topped out at 58%
                               accuracy and isn't trustworthy for anything
                               authoritative. Only exact, human-confirmed
                               typos go in this dict.

NOTES on abbreviations considered and deliberately NOT expanded:
  - CU (copper): the project's own Combined-Master README already flags
    this as a known ~148-row gap, deliberately not fixed due to
    false-positive risk (CU collides with other short tokens in this
    dataset). Sample-checked again this pass: every CU hit in the
    Ecopolitan need_review rows is an electrical cable/terminal item
    ("95/185 sqmm Heavy duty CU terminal") -- i.e. MEP, out of scope
    regardless of whether CU is resolved to "copper". Left unexpanded;
    documented here so it isn't rediscovered as a surprise again.
  - SC, CRE, GA, SM, FI, SMC, IT, PHE, STP, LT, HT, KV, DG, DB, SITC:
    verified to be work-category / discipline / equipment-name prefixes,
    not material shorthand -- SC/CRE in particular were confirmed to
    appear on BOTH already-correctly-classified material rows and
    non-material rows, so they carry no classification signal by
    themselves (CRE- is a generic "works" tag used project-wide, not a
    material flag). GA/SM/FI/SMC/IT are handled separately as
    ADMIN_PREFIXES below since (unlike CRE/SC) sampling *all* of their
    rows found zero material content.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Material abbreviations: token -> expansion, plus an optional list of
# "companion words" that must ALSO appear nearby for high-risk short tokens
# (2-letter tokens are the highest false-positive risk -- a bare "AL" or
# "SS" can appear inside unrelated words or acronyms).
# ---------------------------------------------------------------------------

MATERIAL_ABBREVIATIONS: dict[str, dict] = {
    "MS": {
        "expansion": "mild steel",
        "confidence": "high",
        "evidence": "115 need_review hits; consistently 'MS <noun>' (MS Staircase Wall Railing Rs 20.09M KG unit, MS Angle/Box sections KGS, MS strip, MS casing pipe, MS walkway jalli). Word-boundary only -- excludes 'MSC', 'MSME' etc.",
    },
    "M.S": {  # punctuated form handled again here for the docstring's sake; actual normalization is in PUNCTUATED_ABBREVIATIONS
        "expansion": "mild steel",
        "confidence": "high",
        "evidence": "Same as MS, punctuated form (e.g. 'M.S Angle/Box sections', 'Civil work - M.S. angle Iorn frame').",
    },
    "GI": {
        "expansion": "galvanized iron",
        "confidence": "high",
        "evidence": "77 need_review hits; 'GI strip 25x3mm', 'GI Puddle Flanges', 'Galvanized (GI) ... Pipe'. Matches the project's already-established steel_gi_galvanized category.",
    },
    "SS": {
        "expansion": "stainless steel",
        "confidence": "high",
        "evidence": "70 need_review hits; 'SS Wall Handrail -Staircase', 'SS Handicaped Handrail - Ramp'. Consistently precedes Handrail/Railing/Sink/Fixture nouns in this dataset.",
        "requires_nearby": ["handrail", "railing", "rail", "sink", "fixture", "grill", "grille", "door", "frame"],
    },
    "AL": {
        "expansion": "aluminium",
        "confidence": "medium",
        "evidence": "Lower-frequency token, higher collision risk (AL is also used as a unit-like fragment in some rows). Gated on a nearby aluminium-typical noun to avoid false positives.",
        "requires_nearby": ["window", "door", "frame", "cladding", "louver", "louvre", "section", "profile", "partition"],
    },
    "GYP": {
        "expansion": "gypsum",
        "confidence": "high",
        "evidence": "Standard Indian BOQ shorthand for gypsum plaster/board items.",
    },
    "OBD": {
        "expansion": "oil bound distemper paint",
        "confidence": "high",
        "evidence": "Standard Indian BOQ abbreviation. 'OBD - Ceiling' (Rs 7.72M), 'OBD - Basement columns' both in the Ecopolitan need_review top-50 by impact -- OBD is a distemper PAINT product, was simply missing from the paint-keyword vocabulary entirely (not a punctuation issue like PCC).",
    },
    "WP": {
        "expansion": "waterproofing",
        "confidence": "high",
        "evidence": "71 need_review hits, all 'WP <location/part>' (WP Part 1 -Swimming pool int. walls, WP on water side). Matches the existing waterproofing category.",
    },
    "FF": {
        "expansion": "fire fighting",
        "confidence": "medium",
        "note": "This is an MEP/service-scope tag (Fire Fighting systems), NOT a material -- included here only so downstream MEP-scope logic can recognize it; it must never be treated as a material-category signal.",
    },
    "POP": {
        "expansion": "plaster of paris gypsum",
        "confidence": "high",
        "evidence": "Standard Indian BOQ shorthand, already referenced in the master file's own existing plaster (gypsum) category note ('no gypsum/POP/plasterboard keyword found').",
    },
    "PCC": {
        "expansion": "plain cement concrete",
        "confidence": "high",
        "evidence": "Already a recognized concrete keyword in most of the dataset; listed here mainly to document the punctuated-form gap (see PUNCTUATED_ABBREVIATIONS) that was hiding 'P.C.C. 1:3:6' from it.",
    },
    "RCC": {
        "expansion": "reinforced cement concrete",
        "confidence": "high",
        "evidence": "Standard, already recognized unpunctuated; punctuated form ('R.C.C.') covered separately.",
    },
}

# ---------------------------------------------------------------------------
# Administrative / soft-cost prefixes: description starts with this ->
# no physical material, safe to classify contributes="no" UNLESS the
# description also contains a material keyword (checked separately, see
# enhance_master_classification.py's override scan -- this list alone is
# NOT applied blindly).
# ---------------------------------------------------------------------------

ADMIN_PREFIXES: dict[str, str] = {
    "Prl-": "Preliminaries (site cleaning, surveying, temporary road/power/water, mobilization, site office) -- site-overhead cost, not a building material quantity. 24 rows sampled in full; only 2 contained a material keyword (Openable MS Gate, Steel supply LS) and those 2 are excluded from the bulk 'no' by the override scan, left in need_review instead.",
    "SMC-": "Site/Sales Management Cost (housekeeping, photography, event management, business promotion, possession kits, key chains) -- marketing/handover soft costs. All 57 rows sampled; zero material keywords found.",
    "GA-": "General Administration (security service cost by city, admin overhead) -- pure service cost. All 127 rows sampled; zero material keywords found.",
    "FI-": "Finance (out-of-pocket expenses, audit fees, certifications) -- pure service cost. All 44 rows sampled; zero material keywords found.",
    "IT-": "Information Technology (software licenses, domain registration, CAD/analysis tool subscriptions) -- non-material. All 38 rows sampled; zero material keywords found.",
    "SM-": "Site Management (documentation, O&M, auditing, septic cleaning, photography) -- mostly services. All 62 rows sampled; zero material keywords found EXCEPT the prefix match itself doesn't catch 'SM-Fencing Works', which was manually reviewed and left in need_review (fencing material/quantity genuinely ambiguous from text alone, not excluded and not guessed).",
}

# ---------------------------------------------------------------------------
# Punctuated forms: normalize dotted abbreviations to their plain-letter
# equivalent BEFORE running any keyword regex, so "P.C.C." matches the same
# keyword path as "PCC". Applied with re.sub, longest-pattern-first.
# ---------------------------------------------------------------------------

PUNCTUATED_ABBREVIATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bP\.\s?C\.\s?C\.?\b", re.I), "PCC"),
    (re.compile(r"\bR\.\s?C\.\s?C\.?\b", re.I), "RCC"),
    (re.compile(r"\bM\.\s?S\.?\b", re.I), "MS"),
    (re.compile(r"\bG\.\s?I\.?\b", re.I), "GI"),
    (re.compile(r"\bS\.\s?S\.?\b", re.I), "SS"),
]

# ---------------------------------------------------------------------------
# Confirmed one-off typos found during manual review of the Ecopolitan WO's
# impact-ranked need_review top-50. NOT a fuzzy matcher -- exact strings
# only, each one human-verified against its row's actual context.
# ---------------------------------------------------------------------------

KNOWN_TYPOS: dict[str, str] = {
    "Gyspum": "Gypsum",  # 'Gyspum cornice' -- confirmed gypsum plaster/cornice item
}


def normalize_description(desc: str) -> str:
    """Applies typo fixes + punctuated-abbreviation normalization. Does
    NOT expand plain (unpunctuated) abbreviations -- that's a separate,
    lower-confidence step (see expand_material_abbreviations) kept apart
    so callers can choose how aggressively to match.
    """
    text = desc or ""
    for typo, fix in KNOWN_TYPOS.items():
        text = text.replace(typo, fix)
    for pattern, replacement in PUNCTUATED_ABBREVIATIONS:
        text = pattern.sub(replacement, text)
    return text


def has_admin_prefix(desc: str) -> Optional[str]:
    """Returns the matched ADMIN_PREFIXES key if desc starts with one
    (case-insensitive, allowing a leading space), else None.
    """
    stripped = (desc or "").strip()
    for prefix in ADMIN_PREFIXES:
        if stripped.upper().startswith(prefix.upper()):
            return prefix
    return None


def matches_material_abbreviation(desc: str, token: str) -> bool:
    """Word-boundary match for a MATERIAL_ABBREVIATIONS token, honoring
    requires_nearby gating for high-false-positive-risk tokens.
    """
    entry = MATERIAL_ABBREVIATIONS.get(token)
    if entry is None:
        return False
    if not re.search(rf"\b{re.escape(token)}\b", desc, re.I):
        return False
    nearby = entry.get("requires_nearby")
    if nearby:
        return any(re.search(rf"\b{re.escape(w)}", desc, re.I) for w in nearby)
    return True