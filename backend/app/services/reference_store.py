"""Unified reference-project store.

Wraps the two on-disk pieces of a reference project into one interface:
- metadata (reference_stats.json): whatever the BOQ itself can't tell you
  -- gfa_sqm, structural_system_type, typology.
- extraction (data/reference_boqs/cache/<slug>.json, via boq_cache.py):
  quantities pulled from the actual BOQ file by boq_extractor.py.

This is the growable store Phase A's "cache/reference memory" idea was
building toward. boq_match.py (and any future multi-reference matching
logic) goes through this module rather than touching reference_stats.json
or boq_cache.py directly, so there's one place that knows how to add,
query, and list reference projects -- important once there are more than
the current two.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.services import boq_cache

METADATA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "reference_boqs" / "reference_stats.json"
)


def _load_metadata() -> dict:
    if not METADATA_PATH.exists():
        return {}
    with open(METADATA_PATH, "r") as f:
        return json.load(f)


def _save_metadata(metadata: dict) -> None:
    METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)


def upsert_metadata(
    slug: str,
    structural_system_type: Optional[str] = None,
    typology: Optional[str] = None,
    gfa_sqm: Optional[float] = None,
    priced_year: Optional[int] = None,
) -> dict:
    """Creates or updates a reference project's metadata entry. Only
    overwrites fields explicitly passed (non-None) -- calling this again
    later with just gfa_sqm (e.g. once a project's GFA arrives) won't
    wipe out structural_system_type/typology already on file.

    priced_year: the year the reference BOQ was priced, used by
    cost_adjustment.py to apply an inflation correction. Left null by
    default -- guessing a pricing year would make any cost adjustment
    fabricated from its first input, so this stays unset until someone
    supplies a real value.
    """
    metadata = _load_metadata()
    entry = metadata.get(slug, {})
    if structural_system_type is not None:
        entry["structural_system_type"] = structural_system_type
    if typology is not None:
        entry["typology"] = typology
    if gfa_sqm is not None:
        entry["gfa_sqm"] = gfa_sqm
    if priced_year is not None:
        entry["priced_year"] = priced_year
    entry.setdefault("gfa_sqm", None)
    entry.setdefault("priced_year", None)
    metadata[slug] = entry
    _save_metadata(metadata)
    return entry


def get_metadata(slug: str) -> Optional[dict]:
    return _load_metadata().get(slug)


def clear_gfa(slug: str) -> Optional[dict]:
    """Explicitly sets gfa_sqm back to null for a reference project --
    e.g. to revert a placeholder test value used to validate matching
    logic before a real GFA figure arrives. Separate from upsert_metadata,
    since that function only overwrites fields explicitly passed as
    non-None (so it has no way to force a field back to null).
    Returns None if the slug has no metadata entry to clear.
    """
    metadata = _load_metadata()
    if slug not in metadata:
        return None
    metadata[slug]["gfa_sqm"] = None
    _save_metadata(metadata)
    return metadata[slug]


def get_reference(slug: str) -> Optional[dict]:
    """Returns the combined view of a reference project: metadata +
    extraction, or None if the metadata entry doesn't exist at all.
    """
    metadata = get_metadata(slug)
    if metadata is None:
        return None
    extraction = boq_cache.load_extraction(slug)
    return {"slug": slug, "metadata": metadata, "extraction": extraction}


def list_references() -> list[dict]:
    """Lists every known reference project (from metadata OR cache, even
    if only one side exists yet) with a completeness summary -- useful
    for a status check without opening both files by hand.
    """
    metadata = _load_metadata()
    cached_slugs = set(boq_cache.list_cached_projects())
    all_slugs = set(metadata.keys()) | cached_slugs

    summaries = []
    for slug in sorted(all_slugs):
        meta = metadata.get(slug, {})
        has_extraction = slug in cached_slugs
        summaries.append(
            {
                "slug": slug,
                "has_metadata": slug in metadata,
                "has_gfa": meta.get("gfa_sqm") is not None,
                "has_extraction": has_extraction,
                "structural_system_type": meta.get("structural_system_type"),
                "typology": meta.get("typology"),
                "gfa_sqm": meta.get("gfa_sqm"),
                "usable_for_matching": meta.get("gfa_sqm") is not None and has_extraction,
            }
        )
    return summaries


def find_candidates(
    structural_system_type: Optional[str], typology: Optional[str] = None
) -> list[dict]:
    """Returns reference projects usable for matching (have GFA +
    extraction), optionally filtered by structural system and typology.

    v1: filtering only, no ranking beyond that -- first-match-wins is
    left to the caller (boq_match.py), same limitation as before, now
    just operating over a growable list instead of a hardcoded pair.
    """
    candidates = [r for r in list_references() if r["usable_for_matching"]]
    if structural_system_type is not None:
        candidates = [r for r in candidates if r["structural_system_type"] == structural_system_type]
    if typology is not None:
        candidates = [r for r in candidates if r["typology"] == typology]
    return candidates