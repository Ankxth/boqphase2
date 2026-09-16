"""Project lifecycle endpoints: create, retrieve, and edit.

POST /form now runs the full auto-fill pipeline immediately on
submission (BOQ matching, then LLM fallback for whatever's still unset)
and PERSISTS the result -- matching the intended whiteboard flow: tiered
form -> auto-fill -> editable review page -> calculation. Previously
this endpoint returned a transient, unfilled ProjectSchema with no way
for a second request to find it again.

GET /form/{project_id} retrieves the current saved state (for the
review page to load).

PATCH /form/{project_id} applies user corrections from the review
step -- any field included is stored as source="user-entered",
confidence=1.0, UNCONDITIONALLY overwriting whatever was there before
(BOQ-matched, LLM-estimated, or otherwise), since a user's explicit
correction always outranks every other source in this pipeline.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas.project_schema import (
    FieldValue,
    FinishSpecLevel,
    FoundationType,
    MandatoryFields,
    MepComplexity,
    ProjectSchema,
    SiteCondition,
    StructuralSystemType,
    Tier2Fields,
    Tier3Fields,
    Typology,
)
from app.services import company_store, project_store
from app.services.boq_match import match_boq_defaults
from app.services.llm_fallback import fill_missing_fields

router = APIRouter()


class FormSubmission(BaseModel):
    """Raw shape the frontend's TieredForm posts. Every field optional --
    the user may submit mandatory fields only, or go all the way to tier 3.
    """

    # Workstream 04: which company this project belongs to. Omitted ->
    # company_store.DEFAULT_COMPANY_ID, so a frontend that doesn't know
    # about companies yet keeps working exactly as before.
    company_id: Optional[str] = None

    # mandatory
    gfa_sqm: Optional[float] = None
    location: Optional[str] = None
    structural_system_type: Optional[StructuralSystemType] = None

    # tier 2
    typology: Optional[Typology] = None
    num_floors: Optional[int] = None
    has_basement: Optional[bool] = None
    basement_count: Optional[int] = None
    foundation_type: Optional[FoundationType] = None
    finish_spec_level: Optional[FinishSpecLevel] = None
    parking_type: Optional[str] = None
    parking_area_sqm: Optional[float] = None

    # tier 3
    concrete_grade_mix: Optional[str] = None
    cement_type: Optional[str] = None
    steel_reinforcement_ratio_kg_per_sqm: Optional[float] = None
    facade_type: Optional[str] = None
    glazing_pct: Optional[float] = None
    mep_complexity: Optional[MepComplexity] = None
    green_cert_target: Optional[str] = None
    site_condition: Optional[SiteCondition] = None


def _user_field(value) -> FieldValue:
    if value is None:
        return FieldValue()
    return FieldValue(value=value, source="user-entered", confidence=1.0)


def build_project_schema(submission: FormSubmission, project_id: Optional[str] = None) -> ProjectSchema:
    return ProjectSchema(
        project_id=project_id or str(uuid.uuid4()),
        company_id=submission.company_id or company_store.DEFAULT_COMPANY_ID,
        mandatory=MandatoryFields(
            gfa_sqm=_user_field(submission.gfa_sqm),
            location=_user_field(submission.location),
            structural_system_type=_user_field(submission.structural_system_type),
        ),
        tier2=Tier2Fields(
            typology=_user_field(submission.typology),
            num_floors=_user_field(submission.num_floors),
            has_basement=_user_field(submission.has_basement),
            basement_count=_user_field(submission.basement_count),
            foundation_type=_user_field(submission.foundation_type),
            finish_spec_level=_user_field(submission.finish_spec_level),
            parking_type=_user_field(submission.parking_type),
            parking_area_sqm=_user_field(submission.parking_area_sqm),
        ),
        tier3=Tier3Fields(
            concrete_grade_mix=_user_field(submission.concrete_grade_mix),
            cement_type=_user_field(submission.cement_type),
            steel_reinforcement_ratio_kg_per_sqm=_user_field(submission.steel_reinforcement_ratio_kg_per_sqm),
            facade_type=_user_field(submission.facade_type),
            glazing_pct=_user_field(submission.glazing_pct),
            mep_complexity=_user_field(submission.mep_complexity),
            green_cert_target=_user_field(submission.green_cert_target),
            site_condition=_user_field(submission.site_condition),
        ),
    )


@router.post("/form", response_model=ProjectSchema)
def submit_form(submission: FormSubmission) -> ProjectSchema:
    """Accepts a (possibly partial) form submission, immediately runs
    BOQ matching + LLM fallback to fill whatever's left unset, persists
    the result, and returns it -- ready for the review/edit step.
    """
    project = build_project_schema(submission)
    project = match_boq_defaults(project)
    project = fill_missing_fields(project)
    project_store.save_project(project)
    return project


@router.get("/form/{project_id}", response_model=ProjectSchema)
def get_project(project_id: str, company_id: str = company_store.DEFAULT_COMPANY_ID) -> ProjectSchema:
    # company_id here is only for LOOKUP -- which company's directory to
    # read from. The loaded project's own company_id field (persisted on
    # every save) is the actual source of truth for every downstream use.
    project = project_store.load_project(project_id, company_id=company_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No project found with id '{project_id}'")
    return project


@router.patch("/form/{project_id}", response_model=ProjectSchema)
def edit_project(
    project_id: str, edits: FormSubmission, company_id: str = company_store.DEFAULT_COMPANY_ID
) -> ProjectSchema:
    """Applies review-step corrections. Any field included in the
    request body OVERWRITES the existing field unconditionally, tagged
    source="user-entered", confidence=1.0 -- a user's explicit correction
    always outranks whatever was there (boq-matched, llm-estimated, or
    even an earlier user-entered value). Fields omitted from the request
    body are left untouched, not cleared.
    """
    project = project_store.load_project(project_id, company_id=company_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No project found with id '{project_id}'")

    edits_dict = edits.model_dump(exclude_unset=True)
    edits_dict.pop("company_id", None)  # routing, not an editable tier field -- see get_project's own note
    for field_name, value in edits_dict.items():
        if value is None:
            continue
        target_block = project.mandatory if hasattr(project.mandatory, field_name) else (
            project.tier2 if hasattr(project.tier2, field_name) else project.tier3
        )
        setattr(target_block, field_name, FieldValue(value=value, source="user-entered", confidence=1.0))

    project_store.save_project(project)
    return project