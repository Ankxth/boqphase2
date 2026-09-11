"""Generalized BOQ extraction engine.

v8: restricts quantity extraction to primary tendered-BOQ sheets, skipping
supplementary sheets (e.g. "Derived Items", "NT#0x" / Non-Tendered Items,
grade-rate-calculation backup sheets, summary sheets). Confirmed against
Botanico: summing across ALL sheets inflated RCC by ~17% (98,929.28 vs.
the correct 84,514.58) -- the excess traced exactly to "Derived Items"
re-breaking down quantities already tallied in the main sheet (a backup/
derivation sheet, not additive scope). Restricting to primary sheets only
now reproduces the known-correct RCC total (84,514.58 Cum) to the decimal.

History of fixes that got here, kept for context:
- v4: switched from triangulation-guessing (rate*qty~=amount) to header-
  detection (find the real Item/UOM/Rate/Qty/Amount header row once per
  sheet, then read by fixed column position) -- triangulation was
  fundamentally ambiguous whenever a row had more than 3 numeric columns.
- v5: relaxed column-label matching from exact-match to substring-match,
  since real headers read "Qty (VO#1)" not just "Qty".
- v6: added two-row header detection -- Botanico's main sheet splits its
  header across two rows (UOM/Rate on one, Qty/Amount on the next).
- v7: split "concrete" into separate "rcc" and "pcc" categories, and
  required section headers to be fully uppercase (a mixed-case sentence
  merely mentioning "RCC" in passing was being misread as a new section
  header and silently reactivating the wrong category mid-sheet).
- v8: sheet-level filtering, described above.
- v9 (this version): also sums the Amount column alongside Quantity for
  each category, when the sheet's header includes one (via the same
  column_map already built for quantity extraction -- no new detection
  logic needed, since amount was already being located, just not used).
  This gives real BOQ-sourced cost-per-unit rates (cost_total /
  quantity_total) for cost_estimation.py, rather than a generic
  market-rate assumption. These are HISTORICAL rates from whenever the
  source BOQ was priced -- no inflation adjustment or live market index
  is applied anywhere in this pipeline.

Confidence tiers:
- Deterministic: header row found for a primary sheet, and the row's
  quantity column (by fixed position) holds a plausible positive number.
- LLM-assisted: rows whose unit doesn't match the current category, or
  whose quantity column value isn't plausible, are batched through
  llm_client.chat_json() (routes to whichever provider is configured --
  local Ollama or Groq API).
- Unclassified: rows the LLM also can't resolve are left OUT of totals
  entirely -- for extraction, a silent gap is safer than a fabricated
  number.

Known limitation: the primary-vs-supplementary sheet filter is a
heuristic based on naming patterns seen in one company's BOQs (Botanico/
Ecopolitan). Worth revisiting once BOQs from other companies are
extracted and their sheet-naming conventions are seen -- a different
company's BOQ may not follow the same "Derived Items" / "NT#0x" naming
at all.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Optional

import openpyxl

from app.services.llm_client import LLMUnavailableError, chat_json

# --- Category definitions ---------------------------------------------------

CATEGORY_HEADER_PATTERNS: dict[str, list[str]] = {
    "rcc": [
        r"REINFORCED\s+CEMENT\s+CONCRETE",
        r"\bRCC\b",
        r"IN-?SITU\s+CONCRETE",
    ],
    "pcc": [
        r"PLAIN\s+CEMENT\s+CONCRETE",
        r"\bPCC\b",
        r"BLINDING\s+CONCRETE",
        r"LEVELLING\s+CONCRETE",
    ],
    "reinforcement_steel": [
        r"REINFORCEMENT\s+STEEL",
        r"STEEL\s+REINFORCEMENT",
        r"TMT\s+BAR",
        r"\bREBAR\b",
    ],
    "cement_mortar": [
        r"CEMENT\s+MORTAR",
        r"MASONRY\s+MORTAR",
    ],
    "brickwork": [
        r"BRICK\s*WORK",
        r"BLOCK\s*WORK",
        r"AAC\s+BLOCK",
    ],
    "structural_steel": [
        r"STRUCTURAL\s+STEEL",
        r"STEEL\s+SECTION",
        r"STEEL\s+FABRICATION",
    ],
    "glazing_facade": [
        r"GLAZING",
        r"CURTAIN\s+WALL",
        r"ALUMINIUM\s+FA[CÇ]ADE",
    ],
}

EXPECTED_UNITS: dict[str, set[str]] = {
    "rcc": {"cum", "m3", "cu.m", "cu m"},
    "pcc": {"cum", "m3", "cu.m", "cu m"},
    "reinforcement_steel": {"mt", "kg", "kgs", "ton", "tonne"},
    "cement_mortar": {"cum", "bags", "kg"},
    "brickwork": {"cum", "nos", "sqm"},
    "structural_steel": {"mt", "kg"},
    "glazing_facade": {"sqm", "sq.m"},
}

KNOWN_UOM_STRINGS = {
    "cum", "sqm", "kg", "kgs", "mt", "nos", "rmt", "ls",
    "sqft", "cu.m", "sq.m", "bags", "ton", "tonne", "m", "ltr",
}

HEADER_MAX_LEN = 80
SUBTOTAL_PATTERN = re.compile(r"^\s*(sub[\s-]?total|grand[\s-]?total|total\b)", re.IGNORECASE)

# Sheets matching any of these patterns are treated as supplementary
# (backup/derivation, separate non-tendered scope, rate-calculation
# working sheets, summaries) and are skipped by default -- see the
# module docstring for the evidence behind this.
#
# compound_wall / ext_dev patterns added explicitly: confirmed on
# Ecopolitan that these sheets happened to contribute nothing to
# RCC/PCC/steel totals, but that was incidental (empty overlap), not a
# real reason to trust them by default -- compound walls and external
# site development are genuinely out-of-scope for a per-building GFA
# structural carbon estimate even when they do contain matching
# categories, so they're excluded on purpose now rather than by luck.
SUPPLEMENTARY_SHEET_PATTERNS = [
    r"derived\s*items", r"^nt[\s#_]*\d", r"non[\s-]?tendered",
    r"grade\s+rate\s+calculation", r"grand\s+summary", r"^summary",
    r"working[_\s]", r"^rfa$",
    r"compound\s+wall", r"ext(ernal)?\.?\s+dev(elopment)?\.?\s+works",
]

# --- Header-row column detection --------------------------------------------

COLUMN_LABEL_PATTERNS: dict[str, list[str]] = {
    "item_no": [r"item\s*no", r"^s\.?\s*no\.?", r"^sl\.?\s*no\."],
    "description": [r"description", r"particulars?"],
    "uom": [r"u\.?o\.?m\.?", r"\bunit\b"],
    "rate": [r"\brate\b"],
    "quantity": [r"\bqty\b", r"\bquantity\b"],
    "amount": [r"\bamount\b", r"\bvalue\b"],
}


def _match_column_label(cell_text: str) -> Optional[str]:
    text = cell_text.strip().lower()
    for col_type, patterns in COLUMN_LABEL_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text):
                return col_type
    return None


def _scan_row_for_labels(row: tuple) -> dict[str, int]:
    """Returns {column_type: column_index} for whatever labels this single
    row contains. Leftmost match wins per type."""
    found: dict[str, int] = {}
    for col_idx, cell in enumerate(row):
        if isinstance(cell, str) and cell.strip():
            match = _match_column_label(cell)
            if match and match not in found:
                found[match] = col_idx
    return found


def _merge_two_rows_for_labels(row_a: tuple, row_b: tuple) -> dict[str, int]:
    """Combines two rows column-by-column and scans the merged text per
    column. Handles split headers like Botanico's UOM/Rate-on-one-row,
    Qty/Amount-on-the-next."""
    width = max(len(row_a), len(row_b))
    found: dict[str, int] = {}
    for col_idx in range(width):
        cell_a = row_a[col_idx] if col_idx < len(row_a) else None
        cell_b = row_b[col_idx] if col_idx < len(row_b) else None
        combined = " ".join(
            str(c).strip() for c in (cell_a, cell_b) if isinstance(c, str) and c.strip()
        )
        if combined:
            match = _match_column_label(combined)
            if match and match not in found:
                found[match] = col_idx
    return found


def _is_valid_header(found: dict[str, int]) -> bool:
    return "uom" in found and "quantity" in found and ("rate" in found or "amount" in found)


def _find_header_row(rows: list[tuple], max_scan_rows: int = 60) -> Optional[dict[str, int]]:
    """Scans the first N rows for a header, trying each row alone first,
    then merged with the row directly below it if the row alone doesn't
    yield a valid header. Returns a dict of column_type -> column_index,
    or None if nothing confident is found within the scan window.
    """
    limit = min(max_scan_rows, len(rows))
    for row_idx in range(limit):
        single = _scan_row_for_labels(rows[row_idx])
        if _is_valid_header(single):
            return single

        if row_idx + 1 < limit:
            merged = _merge_two_rows_for_labels(rows[row_idx], rows[row_idx + 1])
            if _is_valid_header(merged):
                return merged

    return None


# --- Row-level helpers -------------------------------------------------------

def _first_text_cell(row: tuple) -> Optional[str]:
    for cell in row:
        if isinstance(cell, str) and cell.strip():
            return cell.strip()
    return None


def _is_subtotal_row(desc: Optional[str]) -> bool:
    if not desc:
        return False
    return bool(SUBTOTAL_PATTERN.match(desc))


def _is_header_row_for_category(desc: Optional[str], uom: Optional[str]) -> Optional[str]:
    """A genuine section header, not just any line mentioning a category
    keyword in passing (e.g. a waterproofing spec note that happens to
    say "...RCC elements..." mid-sentence -- confirmed as a real false
    positive in Botanico's row 700, which was inflating the RCC total
    before this uppercase check was added). Real section headers in this
    BOQ format are consistently uppercase, title-like text -- ordinary
    spec sentences aren't.
    """
    if uom is not None or not desc or len(desc) > HEADER_MAX_LEN:
        return None
    letters_only = "".join(c for c in desc if c.isalpha())
    if not letters_only or not letters_only.isupper():
        return None
    for category, patterns in CATEGORY_HEADER_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, desc, re.IGNORECASE):
                return category
    return None


def _plausible_quantity(value) -> bool:
    return isinstance(value, (int, float)) and value > 0


def _is_primary_sheet(name: str) -> bool:
    for pat in SUPPLEMENTARY_SHEET_PATTERNS:
        if re.search(pat, name, re.IGNORECASE):
            return False
    return True


# --- Sheet walk using detected column map -----------------------------------

def _walk_sheet_with_column_map(
    rows: list[tuple], column_map: dict[str, int]
) -> tuple[dict, list[dict]]:
    results: dict[str, dict] = {
        cat: {"quantity": 0.0, "unit": None, "line_items": 0, "cost_total": 0.0}
        for cat in CATEGORY_HEADER_PATTERNS
    }
    ambiguous_rows: list[dict] = []
    amount_idx = column_map.get("amount")  # may be None if the sheet's header didn't include an amount column

    uom_idx = column_map["uom"]
    qty_idx = column_map["quantity"]

    current_category: Optional[str] = None

    for row in rows:
        if len(row) <= max(uom_idx, qty_idx):
            continue

        desc = _first_text_cell(row)
        uom_val = row[uom_idx] if isinstance(row[uom_idx], str) else None
        uom_val = uom_val.strip() if uom_val else None

        if _is_subtotal_row(desc) and not uom_val:
            current_category = None
            continue

        header_match = _is_header_row_for_category(desc, uom_val)
        if header_match:
            current_category = header_match
            continue

        if current_category is None or not uom_val:
            continue
        if uom_val.lower() not in KNOWN_UOM_STRINGS:
            continue

        expected_units = EXPECTED_UNITS.get(current_category, set())
        if uom_val.lower() not in expected_units:
            ambiguous_rows.append(
                {
                    "category_guess": current_category,
                    "reason": "unit_mismatch",
                    "description": (desc or "")[:120],
                    "uom": uom_val,
                    "row_values": [c for c in row if isinstance(c, (int, float, str))][:8],
                }
            )
            continue

        qty_val = row[qty_idx]
        if not _plausible_quantity(qty_val):
            ambiguous_rows.append(
                {
                    "category_guess": current_category,
                    "reason": "invalid_quantity_at_known_column",
                    "description": (desc or "")[:120],
                    "uom": uom_val,
                    "row_values": [c for c in row if isinstance(c, (int, float, str))][:8],
                }
            )
            continue

        results[current_category]["quantity"] += float(qty_val)
        results[current_category]["unit"] = uom_val
        results[current_category]["line_items"] += 1

        if amount_idx is not None and amount_idx < len(row) and isinstance(row[amount_idx], (int, float)):
            results[current_category]["cost_total"] += float(row[amount_idx])

    results = {k: v for k, v in results.items() if v["line_items"] > 0}
    return results, ambiguous_rows


def _merge_results(a: dict, b: dict) -> dict:
    merged = {k: dict(v) for k, v in a.items()}
    for cat, entry in b.items():
        if cat in merged:
            merged[cat]["quantity"] += entry["quantity"]
            merged[cat]["line_items"] += entry["line_items"]
            merged[cat]["unit"] = merged[cat]["unit"] or entry["unit"]
        else:
            merged[cat] = dict(entry)
    return merged


def _walk_workbook(file_path: str, primary_sheets_only: bool = True) -> tuple[dict, list[dict], dict]:
    """Returns (deterministic_results, ambiguous_rows, sheet_diagnostics).

    primary_sheets_only=True (default) skips supplementary sheets --
    see SUPPLEMENTARY_SHEET_PATTERNS and the module docstring for why.
    Set False only for debugging/comparison purposes.

    Explicitly closes the workbook in a finally block. openpyxl's
    read_only=True mode keeps the file open internally for streaming --
    on Linux/Mac this is harmless even if never explicitly closed (the OS
    allows deleting a file that's still open elsewhere), but Windows
    enforces file locks strictly and will refuse to delete the file
    until the handle is released. Confirmed as a real bug in testing:
    the /refine API endpoint's temp-file cleanup failed with
    PermissionError: [WinError 32] on Windows because this workbook was
    never being closed.
    """
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

    all_results: dict = {}
    all_ambiguous: list[dict] = []
    diagnostics: dict = {}

    try:
        for sheet_name in wb.sheetnames:
            if primary_sheets_only and not _is_primary_sheet(sheet_name):
                diagnostics[sheet_name] = "skipped_supplementary_sheet"
                continue

            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
            column_map = _find_header_row(rows)

            if column_map is None:
                diagnostics[sheet_name] = "no_header_row_found"
                continue

            diagnostics[sheet_name] = f"header_found:{column_map}"
            sheet_results, sheet_ambiguous = _walk_sheet_with_column_map(rows, column_map)
            all_results = _merge_results(all_results, sheet_results)
            all_ambiguous.extend(sheet_ambiguous)
    finally:
        wb.close()

    return all_results, all_ambiguous, diagnostics


# --- LLM-assisted resolution -------------------------------------------------

def _build_ambiguous_prompt(batch: list[dict]) -> str:
    rows_for_prompt = [{k: v for k, v in row.items() if k != "reason"} for row in batch]
    rows_json = json.dumps(rows_for_prompt, indent=2, default=str)
    categories = list(CATEGORY_HEADER_PATTERNS.keys()) + ["unclear"]
    return f"""You are extracting material quantities from ambiguous rows of an Indian
construction Bill of Quantities (BOQ). Each row's raw values are given.

Rows:
{rows_json}

For each row, in the same order given, determine:
- category: one of {categories}
- quantity: the correct quantity value from the row's numeric values
- unit: the row's unit of measure (given as "uom")

If unsure, use category "unclear" and omit quantity/unit.

Respond with ONLY this exact JSON shape, nothing else:
{{"items": [{{"category": "...", "quantity": 0.0, "unit": "..."}}]}}"""


def _plausible_vs_deterministic(qty: float, category: str, deterministic_results: dict) -> bool:
    det = deterministic_results.get(category)
    if not det or det.get("line_items", 0) == 0:
        return True
    avg = det["quantity"] / det["line_items"]
    if avg <= 0:
        return True
    ratio = qty / avg
    return 0.01 <= ratio <= 100


def _resolve_ambiguous_with_llm(ambiguous_rows: list[dict], deterministic_results: dict) -> dict:
    if not ambiguous_rows:
        return {}

    resolved: dict[str, dict] = {}
    batch_size = 6

    for i in range(0, len(ambiguous_rows), batch_size):
        batch = ambiguous_rows[i : i + batch_size]
        prompt = _build_ambiguous_prompt(batch)
        try:
            parsed = chat_json(prompt)
        except (LLMUnavailableError, Exception) as e:
            print(f"[boq_extractor] LLM resolution failed for batch starting at row {i}: {e}")
            continue

        for item in parsed.get("items", []):
            category = item.get("category")
            qty = item.get("quantity")
            unit = item.get("unit")
            if category in (None, "unclear") or not isinstance(qty, (int, float)):
                continue
            if not _plausible_vs_deterministic(qty, category, deterministic_results):
                print(f"[boq_extractor] Rejected implausible LLM quantity {qty} for category '{category}'")
                continue
            entry = resolved.setdefault(category, {"quantity": 0.0, "unit": unit, "line_items": 0})
            entry["quantity"] += qty
            entry["line_items"] += 1

    return resolved


# --- Public entry point -----------------------------------------------------

def extract_boq(
    file_path: str, use_llm_fallback: bool = True, primary_sheets_only: bool = True
) -> dict:
    """Extracts material quantities from a BOQ workbook.

    primary_sheets_only=True (default) restricts extraction to sheets
    that aren't backup/derivation/separate-scope sheets -- see
    SUPPLEMENTARY_SHEET_PATTERNS. Confirmed necessary against Botanico:
    without this filter, RCC total was inflated ~17% by a backup sheet
    re-deriving quantities already in the main sheet.
    """
    deterministic, ambiguous_rows, diagnostics = _walk_workbook(
        file_path, primary_sheets_only=primary_sheets_only
    )
    llm_assisted = _resolve_ambiguous_with_llm(ambiguous_rows, deterministic) if use_llm_fallback else {}

    materials: dict[str, dict] = {}
    all_categories = set(deterministic) | set(llm_assisted)
    for category in all_categories:
        entry = {}
        if category in deterministic:
            entry["deterministic"] = {**deterministic[category], "confidence": "high"}
            # cost_total is in the same currency as the source BOQ's Amount
            # column -- assumed INR (standard for Indian BOQs), not converted
            # or validated against any currency indicator in the file itself.
        if category in llm_assisted:
            entry["llm_assisted"] = {**llm_assisted[category], "confidence": "low"}
        materials[category] = entry

    resolved_row_count = sum(v.get("line_items", 0) for v in llm_assisted.values())
    unclassified_row_count = len(ambiguous_rows) - resolved_row_count

    return {
        "source_file": str(Path(file_path).name),
        "materials": materials,
        "unclassified_row_count": unclassified_row_count,
        "sheet_diagnostics": diagnostics,
    }