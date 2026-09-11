"""Phase 2 substitution endpoint: given a raw BOQ file (same inputs as
/boq-carbon/calculate) plus a list of requested material substitutions,
runs the base calculation once and then REAL-recomputes each requested
substitution against the actual affected line items -- see
substitution_engine.py's module docstring for why this isn't an
estimated delta.

Stateless, like the rest of Phase 2: no project_id, no persistence --
the BOQ file is re-uploaded and re-parsed here rather than referencing a
previously-calculated result, since Phase 2 doesn't store anything
between requests.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.boq_carbon.engine import FloorAreaBasis, calculate_from_boq
from app.services.boq_carbon.parser import extract_from_first_primary_sheet
from app.services.boq_carbon.substitution_catalog import load_catalog
from app.services.boq_carbon.substitution_engine import (
    BoqSubstitutionResponse,
    SubstitutionRequest,
    apply_substitutions,
)
from app.services.boq_extractor import SUPPLEMENTARY_SHEET_PATTERNS

router = APIRouter(prefix="/boq-carbon", tags=["boq-carbon"])


@router.get("/substitution-catalog")
async def get_substitution_catalog() -> list[dict]:
    """The full catalog -- what substitutions exist, their
    max_recommended_pct, sourced reasoning, and structural caveats. The
    frontend uses this to render each material's slider (cap, warning
    text) without hardcoding any of it client-side."""
    return load_catalog()


@router.post("/substitute", response_model=BoqSubstitutionResponse)
async def substitute_boq_carbon(
    boq_file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    floor_area_sqm: Optional[float] = Form(None),
    floor_area_basis: Optional[FloorAreaBasis] = Form(None),
    substitutions: str = Form(...),  # JSON-encoded list of {substitution_id, user_pct}
) -> BoqSubstitutionResponse:
    if not boq_file.filename or not boq_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Expected an .xlsx or .xls file")

    if (floor_area_sqm is None) != (floor_area_basis is None):
        raise HTTPException(
            status_code=400,
            detail="floor_area_sqm and floor_area_basis must be given together, or not at all.",
        )

    try:
        requested = [SubstitutionRequest(**r) for r in json.loads(substitutions)]
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid substitutions payload: {e}")

    if not requested:
        raise HTTPException(status_code=400, detail="substitutions must be a non-empty list")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        shutil.copyfileobj(boq_file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        resolved_sheet = sheet_name
        if resolved_sheet is None:
            resolved_sheet, _ = extract_from_first_primary_sheet(str(tmp_path), SUPPLEMENTARY_SHEET_PATTERNS)

        base_result = calculate_from_boq(
            str(tmp_path),
            resolved_sheet,
            floor_area_sqm=floor_area_sqm,
            floor_area_basis=floor_area_basis,
        )
        base_result.source_file = boq_file.filename

        try:
            return apply_substitutions(requested, base_result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as e:
            print(f"[boq_carbon_substitute] Warning: could not delete temp file {tmp_path}: {e}")
