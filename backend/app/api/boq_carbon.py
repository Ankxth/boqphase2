"""Phase 2 endpoint: upload a raw BOQ file directly and get back a full
embodied-carbon calculation -- no tiered form, no project persistence.

Auto-picks the first non-supplementary sheet (reusing Phase 1's
boq_extractor.SUPPLEMENTARY_SHEET_PATTERNS, so "Derived Items"/"NT#0x"/
summary/backup sheets are skipped the same way here) unless sheet_name is
given explicitly.

floor_area_sqm and floor_area_basis are both optional together, but if
you pass one you must pass the other -- see engine.py's module docstring
for why a bare floor-area number with no stated definition is exactly
the ambiguity that produced an 8.5x mismatch on a real project.

Workstream 06: this endpoint can now also register its own upload as a
future Phase 1 reference project -- the "auto-registration" half of
"Phase 1 learns from Phase 2 history". Opt-in only, via
register_as_reference=True, never automatic: a one-off calculation
(testing, a consulting job for someone else's building) shouldn't
silently become part of a company's own learning data just because the
endpoint was called. When opted in, structural_system_type and typology
are REQUIRED (reference_store.find_candidates needs them to filter by,
and boq_match.py's whole matching logic depends on them being real,
not guessed) -- omitting either while register_as_reference=True is a
400, not a silent skip. On success, this endpoint:
  1. Re-runs app.services.boq_extractor.extract_boq() on the SAME
     uploaded file -- the exact function scripts/run_boq_extraction.py
     already uses to populate a reference project's quantity cache, so
     an auto-registered reference is populated with the identical
     format and confidence tiers as one someone registered by hand.
  2. Caches that extraction via boq_cache.save_extraction().
  3. Upserts GFA/structural_system_type/typology metadata via
     reference_store.upsert_metadata().
A registered reference immediately becomes usable_for_matching (see
reference_store.list_references) for the NEXT Phase 1 estimate against
this company -- there's no separate "activate" step.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services import boq_cache, company_store, reference_store
from app.services.boq_carbon.engine import BoqCarbonResult, FloorAreaBasis, calculate_from_boq
from app.services.boq_carbon.parser import extract_from_first_primary_sheet
from app.services.boq_extractor import SUPPLEMENTARY_SHEET_PATTERNS, extract_boq

router = APIRouter(prefix="/boq-carbon", tags=["boq-carbon"])


@router.post("/calculate", response_model=BoqCarbonResult)
async def calculate_boq_carbon(
    boq_file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    floor_area_sqm: Optional[float] = Form(None),
    floor_area_basis: Optional[FloorAreaBasis] = Form(None),
    register_as_reference: bool = Form(False),
    company_id: str = Form(company_store.DEFAULT_COMPANY_ID),
    structural_system_type: Optional[str] = Form(None),
    typology: Optional[str] = Form(None),
    reference_slug: Optional[str] = Form(None),
    use_llm_extraction_fallback: bool = Form(True),
) -> BoqCarbonResult:
    if not boq_file.filename or not boq_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Expected an .xlsx or .xls file")

    if (floor_area_sqm is None) != (floor_area_basis is None):
        raise HTTPException(
            status_code=400,
            detail="floor_area_sqm and floor_area_basis must be given together, or not at all.",
        )

    if register_as_reference:
        if floor_area_sqm is None:
            raise HTTPException(status_code=400, detail="floor_area_sqm (with floor_area_basis) is required to register this upload as a reference project.")
        if not structural_system_type or not typology:
            raise HTTPException(
                status_code=400,
                detail="structural_system_type and typology are both required when register_as_reference=True -- "
                "Phase 1 matching filters on these, so they can't be left unset or guessed.",
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

        if register_as_reference:
            slug = reference_slug or reference_store.slugify(Path(boq_file.filename).stem)
            extraction = extract_boq(str(tmp_path), use_llm_fallback=use_llm_extraction_fallback)
            boq_cache.save_extraction(slug, extraction, company_id=company_id)
            reference_store.upsert_metadata(
                slug,
                structural_system_type=structural_system_type,
                typology=typology,
                gfa_sqm=floor_area_sqm,
                company_id=company_id,
            )
            result.registered_as_reference = True
            result.reference_slug = slug
            result.registration_note = (
                f"Registered as reference project '{slug}' for company '{company_id}' -- "
                f"available to the next Phase 1 estimate for this company."
            )
        else:
            result.registered_as_reference = False

        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as e:
            print(f"[boq_carbon] Warning: could not delete temp file {tmp_path}: {e}")