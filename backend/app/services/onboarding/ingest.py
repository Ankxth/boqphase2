"""Workstream 05: parses a company's raw item-code dataset upload into
the master-item-code schema shape classification_pipeline.py and
wo_carbon_engine.py already expect (desc / unit / contributes /
material_category / ...), and deduplicates it down to one row per
unique (description, unit) pair before any classification work runs --
the "ingest & extract" + "deduplicate to unique descriptions" stages of
the onboarding design.

A raw item-code export commonly repeats the same material description
under many different item codes (one per project phase/block/floor/
tower). Classifying each of those individually would multiply both
human review effort and LLM call volume for zero new information, since
the classification decision depends only on the text, not the code.
dedupe_by_description groups them so classification work happens exactly
once per unique (description, unit) pair; confirm-time write-back (see
pipeline.confirm_onboarding_job) fans the human's decision back out to
every original code in the group.

Header detection is intentionally flexible (alias lists, substring
match, case-insensitive) rather than requiring exact column names --
this mirrors boq_extractor.py's own header-detection discipline (never
assume a fixed column layout; different companies' exports won't share
Provident's exact spreadsheet conventions) but is simpler, since an
item-code master list has no multi-sheet / multi-header-row structure to
navigate the way a priced BOQ does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import openpyxl

CODE_HEADER_ALIASES = ["item code", "code", "item no", "item number", "sr no", "s.no", "sl no"]
DESC_HEADER_ALIASES = ["description", "short text", "item description", "particulars", "material description"]
UNIT_HEADER_ALIASES = ["unit", "uom", "unit of measure"]

MAX_HEADER_SCAN_ROWS = 15


def _find_header_row(ws) -> tuple[int | None, list[str] | None]:
    max_row = min(MAX_HEADER_SCAN_ROWS, ws.max_row or 0)
    for row_idx in range(1, max_row + 1):
        cells = [str(c.value).strip().lower() if c.value is not None else "" for c in ws[row_idx]]
        has_desc = any(any(alias in c for alias in DESC_HEADER_ALIASES) for c in cells)
        has_unit = any(any(alias in c for alias in UNIT_HEADER_ALIASES) for c in cells)
        if has_desc and has_unit:
            return row_idx, cells
    return None, None


def parse_item_code_workbook(path: str) -> dict[str, dict]:
    """Reads the first sheet of an uploaded .xlsx/.xlsm/.xls file. Raises
    ValueError (not a silent empty result) if no header row with both a
    description and a unit column can be found within the first
    MAX_HEADER_SCAN_ROWS rows -- an onboarding upload with the wrong
    file, or a layout this parser can't recognize, should fail loudly at
    the API boundary rather than silently produce zero rows.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    header_row_idx, headers = _find_header_row(ws)
    if header_row_idx is None:
        raise ValueError(
            "Could not find a header row with both a recognizable description column "
            f"(e.g. {DESC_HEADER_ALIASES}) and a unit column (e.g. {UNIT_HEADER_ALIASES}) "
            f"in the first {MAX_HEADER_SCAN_ROWS} rows of the first sheet."
        )

    col: dict[str, int] = {}
    for i, h in enumerate(headers):
        if "code" not in col and any(alias in h for alias in CODE_HEADER_ALIASES):
            col["code"] = i
        if "desc" not in col and any(alias in h for alias in DESC_HEADER_ALIASES):
            col["desc"] = i
        if "unit" not in col and any(alias in h for alias in UNIT_HEADER_ALIASES):
            col["unit"] = i

    if "desc" not in col or "unit" not in col:
        raise ValueError("Header row found but could not identify both a description and a unit column in it.")

    rows: dict[str, dict] = {}
    auto_code_n = 0
    for r in ws.iter_rows(min_row=header_row_idx + 1):
        values = [c.value for c in r]
        if col["desc"] >= len(values):
            continue
        desc = values[col["desc"]]
        if desc is None or not str(desc).strip():
            continue
        unit = values[col["unit"]] if col["unit"] < len(values) else None

        code = None
        if "code" in col and col["code"] < len(values) and values[col["code"]] is not None:
            code = str(values[col["code"]]).strip()
        if not code:
            auto_code_n += 1
            code = f"AUTO-{auto_code_n:06d}"

        rows[code] = {
            "desc": str(desc).strip(),
            "unit": str(unit).strip().upper() if unit else "",
            "contributes": "need_review",
            "material_category": None,
            "top5": "no",
            "ef_kgco2e_per_kg": None,
            "ef_source": None,
            "cea_adjusted": None,
            "evidence_tier": None,
            "unit_note": "Newly ingested -- pending classification (Workstream 05 onboarding pipeline).",
        }

    return rows


def _normalize_key(desc: str | None, unit: str | None) -> tuple[str, str]:
    norm_desc = re.sub(r"\s+", " ", (desc or "").strip().lower())
    return norm_desc, (unit or "").strip().upper()


@dataclass
class DedupeResult:
    deduped: dict[str, dict]                 # representative_code -> row
    code_groups: dict[str, list[str]]        # representative_code -> [every original code sharing this (desc, unit)]


def dedupe_by_description(rows: dict[str, dict]) -> DedupeResult:
    """Groups rows sharing an identical normalized (description, unit)
    pair under one representative code (the first one encountered, in
    dict-iteration order). Every original code is preserved in
    code_groups so a later confirm can fan a single classification
    decision back out to all of them.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for code, row in rows.items():
        key = _normalize_key(row.get("desc"), row.get("unit"))
        groups.setdefault(key, []).append(code)

    deduped: dict[str, dict] = {}
    code_groups: dict[str, list[str]] = {}
    for codes in groups.values():
        rep = codes[0]
        deduped[rep] = dict(rows[rep])
        code_groups[rep] = codes

    return DedupeResult(deduped=deduped, code_groups=code_groups)