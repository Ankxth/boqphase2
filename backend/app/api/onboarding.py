"""Workstream 05: item-code & Work-Order onboarding pipeline endpoints.

Exposes app/services/onboarding/pipeline.py over HTTP, following the
same shape every other upload endpoint in this project already uses
(temp-file handling via tempfile.NamedTemporaryFile, company_id resolved
through company_store, real HTTPException status codes instead of a
silently-empty success response) -- see app/api/wo_carbon.py and
app/api/boq_carbon.py for the endpoints this one is modeled on.

Three endpoints, matching the pipeline's two-phase design (produce a
reviewable job, then confirm it):

  POST /onboarding/{company_id}/upload
      Upload a raw item-code workbook (.xlsx/.xlsm/.xls). Runs ingest ->
      dedupe -> the regex classification pass -> (optionally) the LLM
      draft stage -> impact ranking, and returns the resulting job in
      full, including its impact-ranked review queue. Nothing is written
      to the company's master_item_codes.json yet.

  GET /onboarding/{company_id}/jobs/{job_id}
      Re-fetches a previously created job (e.g. so a reviewer can come
      back to it later, or a frontend can reload after a page refresh).

  POST /onboarding/{company_id}/jobs/{job_id}/confirm
      Applies a human reviewer's decisions for some or all of the job's
      review queue, writes the result into the company's own
      master_item_codes.json, and (only when a decision explicitly asks
      for it) registers a genuinely new category into the shared
      cross-company canonical taxonomy.

Deliberate scope decision: impact ranking uses real amounts only when
the caller supplies an `amounts_by_code` JSON mapping (code -> Rs
amount) alongside the upload -- e.g. from a BOQ or Work Order already
parsed elsewhere for the same items. Automatically cross-linking a
freshly uploaded item-code master against a separately uploaded priced
document is real code-matching work of its own (item codes across two
different documents for the same project aren't guaranteed to line up
1:1) and is left for a future workstream; without it, the review queue
falls back to ranking by how many original item codes collapsed into
each unique description -- a real, honest signal, just a frequency-based
one instead of a Rupee-based one. This is stated in the response
(review_queue[].impact_basis is "amount" or "frequency") rather than
left ambiguous.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services import company_store
from app.services.onboarding import pipeline
from app.services.onboarding.ingest import parse_item_code_workbook

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

_ALLOWED_EXTENSIONS = (".xlsx", ".xlsm", ".xls")


@router.post("/{company_id}/upload")
async def upload_item_codes(
    company_id: str,
    item_code_file: UploadFile = File(...),
    use_llm_draft: bool = Form(True),
    amounts_by_code: Optional[str] = Form(None),
):
    if not item_code_file.filename or not item_code_file.filename.lower().endswith(_ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail=f"Expected an Excel file ({', '.join(_ALLOWED_EXTENSIONS)}) of raw item codes.")

    parsed_amounts: Optional[dict[str, float]] = None
    if amounts_by_code:
        try:
            parsed_amounts = {str(k): float(v) for k, v in json.loads(amounts_by_code).items()}
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            raise HTTPException(status_code=400, detail=f"amounts_by_code must be a JSON object of {{code: amount}}: {e}")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        shutil.copyfileobj(item_code_file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        raw_rows = parse_item_code_workbook(str(tmp_path))
        if not raw_rows:
            raise HTTPException(status_code=422, detail="No item-code rows could be read from this file.")
        job = pipeline.run_onboarding_upload(
            company_id,
            raw_rows,
            amounts_by_code=parsed_amounts,
            use_llm_draft=use_llm_draft,
        )
        return job
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as e:
            print(f"[onboarding] Warning: could not delete temp file {tmp_path}: {e}")


@router.get("/{company_id}/jobs/{job_id}")
async def get_onboarding_job(company_id: str, job_id: str):
    job = pipeline.load_job(company_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No onboarding job {job_id!r} found for company {company_id!r}.")
    return job


class ConfirmDecision(BaseModel):
    code: str
    fields: dict = {}
    register_as_new_category: Optional[str] = None


class ConfirmRequest(BaseModel):
    decisions: list[ConfirmDecision]


@router.post("/{company_id}/jobs/{job_id}/confirm")
async def confirm_onboarding_job(company_id: str, job_id: str, body: ConfirmRequest):
    try:
        result = pipeline.confirm_onboarding_job(
            company_id, job_id, [d.model_dump() for d in body.decisions]
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@router.get("/canonical-categories")
async def list_canonical_categories():
    """Deliberately NOT company-scoped -- the canonical taxonomy is
    shared across every company, see
    app/services/onboarding/canonical_categories.py. Useful for a
    reviewer UI to show what categories already exist before deciding
    whether a row is really a new one. Registered as a static path
    ("/onboarding/canonical-categories") rather than under
    "/{company_id}/...", so it can't collide with a company literally
    named "canonical-categories" the way it would if this were nested
    under the company_id path parameter.
    """
    from app.services.onboarding import canonical_categories

    return canonical_categories.load_canonical_categories()