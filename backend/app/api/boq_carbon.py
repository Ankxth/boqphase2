"""Phase 2 endpoint: upload a raw BOQ file directly and get back a full
embodied-carbon calculation -- no tiered form, no project persistence,
no reference-project matching. Standalone from Phase 1's /form ->
/calculate flow.

Auto-picks the first non-supplementary sheet (reusing Phase 1's
boq_extractor.SUPPLEMENTARY_SHEET_PATTERNS, so "Derived Items"/"NT#0x"/
summary/backup sheets are skipped the same way here) unless sheet_name is
given explicitly.

floor_area_sqm and floor_area_basis are both optional together, but if
you pass one you must pass the other -- see engine.py's module docstring
for why a bare floor-area number with no stated definition is exactly
the ambiguity that produced an 8.5x mismatch on a real project.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.boq_carbon.engine import BoqCarbonResult, FloorAreaBasis, calculate_from_boq
from app.services.boq_carbon.parser import extract_from_first_primary_sheet
from app.services.boq_extractor import SUPPLEMENTARY_SHEET_PATTERNS

router = APIRouter(prefix="/boq-carbon", tags=["boq-carbon"])


@router.post("/calculate", response_model=BoqCarbonResult)
async def calculate_boq_carbon(
    boq_file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    floor_area_sqm: Optional[float] = Form(None),
    floor_area_basis: Optional[FloorAreaBasis] = Form(None),
) -> BoqCarbonResult:
    if not boq_file.filename or not boq_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Expected an .xlsx or .xls file")

    if (floor_area_sqm is None) != (floor_area_basis is None):
        raise HTTPException(
            status_code=400,
            detail="floor_area_sqm and floor_area_basis must be given together, or not at all.",
        )

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        shutil.copyfileobj(boq_file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        resolved_sheet = sheet_name
        if resolved_sheet is None:
            resolved_sheet, _ = extract_from_first_primary_sheet(str(tmp_path), SUPPLEMENTARY_SHEET_PATTERNS)

        result = calculate_from_boq(
            str(tmp_path),
            resolved_sheet,
            floor_area_sqm=floor_area_sqm,
            floor_area_basis=floor_area_basis,
        )
        # Report the ORIGINAL filename, not the temp path, in the result.
        result.source_file = boq_file.filename
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as e:
            print(f"[boq_carbon] Warning: could not delete temp file {tmp_path}: {e}")