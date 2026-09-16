"""Workstream 09: read-only endpoints over the versioned factor history
(app/services/factor_history.py) -- lets a frontend (or a support
conversation) show WHY a number is what it is and what it used to be,
without needing direct file access. Nothing here is writable over HTTP
on purpose -- recording a new value is a deliberate, human-run action
(scripts/update_emission_factor.py), not something exposed as an
unauthenticated API call in an app that has no auth layer yet.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.factor_history import FactorHistoryEntry, generate_snapshot, get_history, list_categories

router = APIRouter(prefix="/factors", tags=["factors"])


@router.get("/current")
def get_current_snapshot(as_of: str | None = None) -> dict:
    """The full current (or, with ?as_of=YYYY-MM-DD, historical) factor
    snapshot -- the same shape app/data/ice_db/emission_factors.json
    carries, generated live from factor_history.json rather than read off
    disk, so it can never be stale relative to the source of truth."""
    return generate_snapshot(as_of=as_of)


@router.get("/{category}/history", response_model=list[FactorHistoryEntry])
def get_category_history(category: str) -> list[FactorHistoryEntry]:
    """Every recorded value for `category`, oldest first -- what a report
    used at the time it ran, and why it later changed, if it did."""
    entries = get_history(category)
    if not entries:
        known = list_categories()
        raise HTTPException(
            status_code=404,
            detail=f"No recorded history for category '{category}'. Known categories: {known}",
        )
    return entries