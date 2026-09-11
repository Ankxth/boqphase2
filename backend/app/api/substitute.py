"""Substitution suggestion endpoint -- returns individual suggestions
plus their combined effect if all were applied together.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import project_store
from app.services.calculation_engine import calculate_embodied_carbon
from app.services.substitution import (
    CombinedSubstitutionImpact,
    SubstitutionSuggestion,
    compute_combined_impact,
    suggest_substitutions,
)

router = APIRouter()


class SubstituteResponse(BaseModel):
    project_id: str
    suggestions: list[SubstitutionSuggestion]
    combined_impact: CombinedSubstitutionImpact | None


@router.post("/substitute/{project_id}", response_model=SubstituteResponse)
def substitute(project_id: str) -> SubstituteResponse:
    project = project_store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No project found with id '{project_id}'")

    if project.mandatory.gfa_sqm.value is None:
        raise HTTPException(status_code=400, detail="Cannot compute substitutions without a valid GFA")

    actual_result = calculate_embodied_carbon(project)
    suggestions = suggest_substitutions(project, actual_result)
    combined = compute_combined_impact(project, actual_result, suggestions)

    return SubstituteResponse(project_id=project_id, suggestions=suggestions, combined_impact=combined)