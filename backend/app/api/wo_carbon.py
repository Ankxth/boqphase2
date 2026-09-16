"""Workstream 02: Work Order API endpoint.

Phase 2's other half. app/api/boq_carbon.py already exposes the raw-BOQ
-> carbon pipeline over HTTP; wo_carbon_engine.py (the raw-Work-Order ->
carbon pipeline, hardened in Workstream 01 to read from the same
emission-factor source) has never had an HTTP endpoint at all -- every
calculation against it, across this entire project's history, has run
through scripts/test_wo_carbon_engine.py by hand. That gap blocks every
Phase 3/4 flow described in the roadmap that starts from a Work Order
upload, so this is WS02: the first, sharpest prerequisite.

Deliberately mirrors app/api/boq_carbon.py's shape (temp-file handling,
paired floor_area_sqm/floor_area_basis validation, restoring the
original filename onto the result) so the two Phase 2 endpoints stay
consistent for whatever frontend calls them.

Updated for WS03: wo_pdf_parser.py no longer shells out to `pdftotext`
(pdfplumber reads the PDF directly, no subprocess, no PATH/locale
dependency), so the FileNotFoundError/CalledProcessError handling this
endpoint originally needed for that binary is gone. What replaces it: a
scanned/image-only PDF now parses "successfully" to zero line items
(pdfplumber has no text layer to read, same as before, but that's no
longer a crash) -- this endpoint checks n_line_items_parsed == 0 and
reports it as a real 422, not a silent empty-looking success.

Master item-code dataset: Workstream 04 moved this from a single global
file to one per company (app.services.company_store), so this endpoint
now takes company_id and resolves that company's own
master_item_codes.json -- defaulting to company_store.DEFAULT_COMPANY_ID
("provident"), the only company with real data today, so an existing
caller that doesn't pass company_id keeps working exactly as before.
master_json_path is still accepted as an explicit override (for testing
against a specific file, e.g. the pre-Workstream-01 backup) and wins
over company_id when both are given.

Workstream 06: this endpoint can now also register its own upload as a
future Phase 1 reference project, opt-in via register_as_reference=True
-- same shape and same required-fields discipline as
app/api/boq_carbon.py's own auto-registration (see that endpoint's
docstring for the full reasoning). One deliberate, disclosed difference:
this endpoint registers GFA/structural_system_type/typology METADATA
ONLY, via reference_store.upsert_metadata() -- it does NOT populate a
quantity-extraction cache the way boq_carbon.py's registration does.
That's not an oversight: boq_match.py's derived ratios specifically mean
REBAR content (the "reinforcement_steel" category from
app.services.boq_extractor's taxonomy), and this engine's own
by_category breakdown reports "structural_steel" (rolled sections --
angles, ISMB/ISMC channels) as a SEPARATE, semantically different
material -- see canonical_categories.py's module docstring for the full
provenance of that distinction. Silently feeding one into the ratio slot
meant for the other would produce a real, wrong number rather than just
a missing one, which this project's whole discipline has consistently
chosen against (see e.g. llm_classifier.py's cited-word requirement, or
similarity_triage.py staying assistive-only). A WO-registered reference
still contributes fully to ranked GFA matching (reference_store.
find_candidates) and to company_history.py's typology/structural-system/
GFA-range aggregation -- it just doesn't (yet) contribute a steel/
concrete ratio. Building a real WO-side quantity-extraction bridge is
future work, not attempted here.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pdfplumber.utils.exceptions import PdfminerException

from app.services import company_store, reference_store
from app.services.wo_carbon.wo_carbon_engine import (
    FloorAreaBasis,
    WoCarbonResult,
    calculate_from_work_order,
)

router = APIRouter(prefix="/wo-carbon", tags=["wo-carbon"])


@router.post("/calculate", response_model=WoCarbonResult)
async def calculate_wo_carbon(
    wo_file: UploadFile = File(...),
    floor_area_sqm: Optional[float] = Form(None),
    floor_area_basis: Optional[FloorAreaBasis] = Form(None),
    # Workstream 06 fix: this lacked Form(...) since Workstream 02 first
    # added it (and Workstream 04 gave it real meaning). On a multipart
    # request (this endpoint takes an UploadFile, so every request is
    # multipart), a plain-typed parameter with no Form()/Query() wrapper
    # is inferred by FastAPI as a QUERY parameter, not a form field --
    # so a caller sending company_id alongside the file in the form body
    # (the only sane way to send it next to a file upload) was silently
    # ignored, and this endpoint always ran against DEFAULT_COMPANY_ID
    # ("provident") regardless of what was actually sent. Caught by
    # Workstream 06's own registration tests (a WO registered "for"
    # company_id="acme" via form data was actually being written under
    # "provident"), fixed here. Every caller that omitted company_id
    # keeps the exact same default behavior; only a caller that was
    # trying to pass a non-default company_id and having it silently
    # dropped is affected, and that's a bug fix, not a behavior it
    # should keep.
    company_id: str = Form(company_store.DEFAULT_COMPANY_ID),
    master_json_path: Optional[str] = Form(None),
    register_as_reference: bool = Form(False),
    structural_system_type: Optional[str] = Form(None),
    typology: Optional[str] = Form(None),
    reference_slug: Optional[str] = Form(None),
) -> WoCarbonResult:
    if not wo_file.filename or not wo_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Expected a .pdf file")

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

    resolved_master_path = (
        Path(master_json_path) if master_json_path else company_store.master_item_codes_path(company_id)
    )
    if not resolved_master_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Master item-code dataset not found for company '{company_id}' at {resolved_master_path}",
        )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        shutil.copyfileobj(wo_file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        result = calculate_from_work_order(
            str(tmp_path),
            str(resolved_master_path),
            floor_area_sqm=floor_area_sqm,
            floor_area_basis=floor_area_basis,
        )
        if result.n_line_items_parsed == 0:
            # pdfplumber found no text layer to read at all -- most
            # commonly a scanned/image-only PDF, which this parser does
            # not OCR. Report it plainly rather than returning a
            # "successful" all-zero result that looks like a real
            # (empty) Work Order.
            raise HTTPException(
                status_code=422,
                detail="Could not extract any line items from this PDF -- it may be a scanned/image-only document, which isn't supported yet.",
            )
        # Report the ORIGINAL filename, not the temp path, in the result --
        # same reasoning as boq_carbon.py.
        result.source_file = wo_file.filename

        if register_as_reference:
            slug = reference_slug or reference_store.slugify(Path(wo_file.filename).stem)
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
                f"Registered as reference project '{slug}' for company '{company_id}' -- metadata only "
                f"(GFA/structural system/typology), no quantity-extraction cache. See this endpoint's own "
                f"module docstring for why. Contributes to ranked GFA matching and to company_history.py's "
                f"aggregate ranges, not to boq_match.py's per-material ratios."
            )
        else:
            result.registered_as_reference = False

        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PdfminerException as e:
        # pdfplumber/pdfminer couldn't open this file as a PDF at all
        # (corrupt file, or not actually a PDF despite the extension).
        raise HTTPException(status_code=400, detail=f"Could not read this file as a PDF: {e}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as e:
            print(f"[wo_carbon] Warning: could not delete temp file {tmp_path}: {e}")