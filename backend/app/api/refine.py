"""Own-BOQ refinement endpoint -- lets a project be refined with its own
real BOQ once one becomes available later in design (Phase C).

This was deliberately left unwired when project_boq_refinement.py was
first built, since no project persistence existed yet to make a
multi-request "upload a BOQ for an existing project" flow meaningful.
Persistence exists now (project_store.py), so this closes that gap.

Accepts a multipart file upload (the BOQ .xlsx), saves it to a temp
location, runs extraction against it, and persists the refined project.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.schemas.project_schema import ProjectSchema
from app.services import company_store, project_store
from app.services.project_boq_refinement import refine_project_with_boq

router = APIRouter()


class RefineResponse(BaseModel):
    project: ProjectSchema
    message: str


@router.post("/refine/{project_id}", response_model=RefineResponse)
async def refine_with_own_boq(
    project_id: str,
    boq_file: UploadFile = File(...),
    company_id: str = company_store.DEFAULT_COMPANY_ID,
) -> RefineResponse:
    project = project_store.load_project(project_id, company_id=company_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No project found with id '{project_id}'")

    if project.mandatory.gfa_sqm.value is None:
        raise HTTPException(status_code=400, detail="Cannot refine with BOQ data without a valid project GFA")

    if not boq_file.filename or not boq_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Expected an .xlsx or .xls file")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        shutil.copyfileobj(boq_file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        project = refine_project_with_boq(project, str(tmp_path))
    finally:
        # Cleanup is best-effort -- a failure to delete the temp file
        # should never crash a request that otherwise succeeded. The
        # real fix for the Windows file-lock case is boq_extractor.py
        # now explicitly closing its workbook, but this is kept as a
        # safety net for any other reason deletion might fail (e.g. an
        # antivirus scan holding a lock).
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as e:
            print(f"[refine] Warning: could not delete temp file {tmp_path}: {e}")

    project_store.save_project(project)

    return RefineResponse(
        project=project,
        message=(
            "Project refined with its own BOQ data. Fields updated with "
            "source='own-boq-extracted' now outrank any earlier boq-matched "
            "or llm-estimated values for the same fields."
        ),
    )