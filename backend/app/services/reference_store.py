"""Unified reference-project store.

Wraps the two on-disk pieces of a reference project into one interface:
- metadata (reference_stats.json): whatever the BOQ itself can't tell you
  -- gfa_sqm, structural_system_type, typology.
- extraction (.../reference_projects/cache/<slug>.json, via boq_cache.py):
  quantities pulled from the actual BOQ file by boq_extractor.py.

This is the growable store Phase A's "cache/reference memory" idea was
building toward. boq_match.py (and any future multi-reference matching
logic) goes through this module rather than touching reference_stats.json
or boq_cache.py directly, so there's one place that knows how to add,
query, and list reference projects -- important once there are more than
the current two.

Workstream 04: every function now takes a company_id (defaulting to
company_store.DEFAULT_COMPANY_ID), since which reference projects are
even candidates for matching has to be scoped per company -- a company
B project should never match against company A's Botanico/Ecopolitan
data. See company_store.py's own docstring for the full storage-layout
rationale.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from app.services import boq_cache, company_store


def slugify(name: str) -> str:
    """Turns an arbitrary filename/title into a reference-project slug:
    lowercase, non-alphanumeric runs collapsed to a single underscore,
    leading/trailing underscores stripped. Used by Workstream 06's
    auto-registration (app/api/boq_carbon.py, app/api/wo_carbon.py) to
    derive a default slug from an uploaded file's name when the caller
    doesn't supply one explicitly.
    """
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return s.strip("_") or "reference"


def _metadata_path(company_id: str):
    return company_store.reference_projects_dir(company_id) / "reference_stats.json"


def _load_metadata(company_id: str) -> dict:
    path = _metadata_path(company_id)
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return json.load(f)


def _save_metadata(company_id: str, metadata: dict) -> None:
    path = _metadata_path(company_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(metadata, f, indent=2)


def upsert_metadata(
    slug: str,
    structural_system_type: Optional[str] = None,
    typology: Optional[str] = None,
    gfa_sqm: Optional[float] = None,
    priced_year: Optional[int] = None,
    company_id: str = company_store.DEFAULT_COMPANY_ID,
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
    metadata = _load_metadata(company_id)
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
    _save_metadata(company_id, metadata)
    return entry


def get_metadata(slug: str, company_id: str = company_store.DEFAULT_COMPANY_ID) -> Optional[dict]:
    return _load_metadata(company_id).get(slug)


def clear_gfa(slug: str, company_id: str = company_store.DEFAULT_COMPANY_ID) -> Optional[dict]:
    """Explicitly sets gfa_sqm back to null for a reference project --
    e.g. to revert a placeholder test value used to validate matching
    logic before a real GFA figure arrives. Separate from upsert_metadata,
    since that function only overwrites fields explicitly passed as
    non-None (so it has no way to force a field back to null).
    Returns None if the slug has no metadata entry to clear.
    """
    metadata = _load_metadata(company_id)
    if slug not in metadata:
        return None
    metadata[slug]["gfa_sqm"] = None
    _save_metadata(company_id, metadata)
    return metadata[slug]


def get_reference(slug: str, company_id: str = company_store.DEFAULT_COMPANY_ID) -> Optional[dict]:
    """Returns the combined view of a reference project: metadata +
    extraction, or None if the metadata entry doesn't exist at all.
    """
    metadata = get_metadata(slug, company_id=company_id)
    if metadata is None:
        return None
    extraction = boq_cache.load_extraction(slug, company_id=company_id)
    return {"slug": slug, "metadata": metadata, "extraction": extraction}


def list_references(company_id: str = company_store.DEFAULT_COMPANY_ID) -> list[dict]:
    """Lists every known reference project (from metadata OR cache, even
    if only one side exists yet) with a completeness summary -- useful
    for a status check without opening both files by hand.
    """
    metadata = _load_metadata(company_id)
    cached_slugs = set(boq_cache.list_cached_projects(company_id=company_id))
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
    structural_system_type: Optional[str],
    typology: Optional[str] = None,
    target_gfa_sqm: Optional[float] = None,
    company_id: str = company_store.DEFAULT_COMPANY_ID,
) -> list[dict]:
    """Returns reference projects usable for matching (have GFA +
    extraction), optionally filtered by structural system and typology,
    scoped to one company's own reference projects.

    Workstream 06: when target_gfa_sqm is given, candidates are RANKED
    by closeness of GFA to it (nearest first, ties broken by slug for
    determinism) instead of being left in whatever order list_references
    happens to return them -- this is what makes boq_match.py's
    candidates[0] a genuine "best match", not the old v1 "whichever
    reference happens to be first in the list" behavior (see
    boq_match.py's own docstring for the before/after). When
    target_gfa_sqm is omitted, ranking is skipped and candidates come
    back in list_references' own order, same as before this workstream
    -- every existing caller that doesn't pass it keeps working exactly
    as before.
    """
    candidates = [r for r in list_references(company_id=company_id) if r["usable_for_matching"]]
    if structural_system_type is not None:
        candidates = [r for r in candidates if r["structural_system_type"] == structural_system_type]
    if typology is not None:
        candidates = [r for r in candidates if r["typology"] == typology]
    if target_gfa_sqm is not None:
        candidates = sorted(candidates, key=lambda r: (abs(r["gfa_sqm"] - target_gfa_sqm), r["slug"]))
    return candidates