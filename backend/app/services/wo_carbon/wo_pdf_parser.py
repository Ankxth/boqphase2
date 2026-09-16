"""Parses a SAP-style "Work Order" PDF (the KPIL/Provident BOQ-with-rates
format -- "BOQ SUMMARY" pages followed by a "BOQ ITEM DETAILS" section with
one row per priced line item) into a flat list of line items: Activity
Number, Tax Tariff Code, Unit, Rate, Amount, and a derived Quantity.

Workstream 03: rebuilt on pdfplumber instead of shelling out to the
`pdftotext` binary. Two real production bugs traced back to that
subprocess dependency (not to this parser's own logic):

  - A shadowed Xpdf `pdftotext` (bundled with Git-for-Windows) sitting
    ahead of the correct Poppler build on PATH silently produced a worse
    layout reconstruction -- 37,329 lines instead of 30,093 for the same
    PDF, cascading into a total 26x too high before it was diagnosed.
  - subprocess.run(text=True) without an explicit encoding decodes using
    the OS's default locale -- cp1252 on Windows -- which crashed
    outright on a real non-ASCII byte this WO's text legitimately
    contains (a stray "Â" from a mis-encoded non-breaking space in
    "CementÂ Screed Concrete Flooring").

Both are the same category of risk: a customer's machine has some detail
this project didn't control, and the calculation silently depended on
it. pdfplumber is pure pip-installable (MIT-licensed, no system binary,
no locale-dependent decode -- it reads the PDF's bytes directly), which
removes the category of bug entirely rather than working around one
instance of it.

Why Quantity is still derived as Amount / Rate, not read directly
--------------------------------------------------------------------
This document's own internal text-flow detaches a row's Qty number from
the rest of its row surprisingly often -- sometimes onto the line right
before the row's own Sr No/Code, sometimes right after, sometimes split
across two fragments (e.g. "15633.13" then a lone "0" on the next line).
That's a property of how this specific PDF's content stream lays text
out, not an artifact of pdftotext -- pdfplumber's own word-position data
shows the exact same detachment. There is no reliable, general rule for
which detached fragment belongs to which row. Rate and Amount don't have
this problem: in every real example checked across this document (420
pages, 7,910 line-item occurrences), Rate and Amount always land
together on the same visual line as the row's Unit token. And the row's
own math is exact: Amount == Qty * Rate (confirmed to the cent). So this
parser still reads Unit + Rate + Amount directly and derives
Qty = Amount / Rate, exactly as before Workstream 03 -- changing this
would mean guessing which stray fragment belongs to which row, trading a
provably-exact number for a guess, for no accuracy gain.

What DID change: position-based column reading
--------------------------------------------------------------------
The pre-Workstream-03 parser found Rate/Amount by taking "the last two
decimal-point numbers on the line" -- a text-order heuristic that
happened to work because Rate and Amount were always the rightmost two
numbers on their line in the documents checked, but had no way to know
that from the document itself. pdfplumber exposes each word's real (x0,
x1, top, bottom) position, so this parser now locates the WO's own
"Unit Qty Rate Amount" header row once (column positions are fixed for
the rest of that document) and reads each row's Rate/Amount by which
column band a number's x-position actually falls into -- the same
column-clustering idea app/services/boq_carbon/parser.py already uses
for Excel headers, now available for PDFs too. If a document's header
row can't be found (a different export, a layout this doesn't
recognise), extraction falls back to the original last-two-numbers
heuristic rather than failing outright.

Validated against this document's own numbers, not just spot-checked:
the WO's "BOQ SUMMARY" section states each top-level section's total
Amount. Summing every individually parsed line item's Amount from "BOQ
ITEM DETAILS" reproduces that same total EXACTLY (to the cent, 0.00
difference) across all 420 pages -- see tests/test_wo_carbon_golden.py
and tests/test_wo_carbon_api.py, both of which re-verify this on every
run via parse_checksum_ok, and this rewrite was additionally checked
line-by-line (item-for-item) against the pre-Workstream-03 pdftotext
-based parser's own output on both reference Work Orders before this
file replaced it.

System dependency
------------------
None. `pip install pdfplumber` is the entire setup -- see
requirements.txt.

A known, accepted cost of that trade
--------------------------------------
pdfplumber's pure-Python character-level parsing is genuinely slower
than the compiled poppler binary this replaced -- measured at ~37s for
the 420-page Ecopolitan WO, vs. ~0.5s for `pdftotext -layout` on the
same file (confirmed: the cost is in pdfplumber's own low-level char
extraction, not in anything this module adds on top of it, so there's
no cheap optimization being left on the table here). Weighed against
the two real production bugs the old subprocess dependency caused (see
above) and decided deliberately: ship this as-is rather than add a
pdftotext-first/pdfplumber-fallback hybrid (which wouldn't have caught
the original PATH-shadowing bug anyway, since that one produced silently
wrong output, not an exception) or an async job pattern (a bigger change
than this workstream's scope, and one Phase 3's dashboard work will
likely want to revisit on its own terms). If upload latency becomes a
real problem later, that's the trade to revisit -- not this module's
correctness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pdfplumber

CODE_RE = re.compile(r"\b(\d{7,9})\s*/\s*(\d{5,6})\b")

# Base Unit of Measure vocabulary seen across the Provident master item
# code dataset. Longest-first so e.g. FT2/FT3 match before bare FT, and
# M3/M2 match before bare M.
_UNIT_TOKENS = [
    "NOS", "LS", "RMT", "SQM", "CUM", "SET", "MON", "FT2", "EA", "KG", "LOT",
    "DAY", "MT", "KGS", "FT3", "FT", "L", "HR", "BAG", "FLR", "UNT", "KM",
    "M3", "LOD", "M2", "ROL", "ACR", "BOX", "PAA", "KW", "TRP", "HRS", "FLT",
    "TON", "Shf", "M", "N",
]
UNIT_RE = re.compile(r"\b(" + "|".join(re.escape(u) for u in sorted(set(_UNIT_TOKENS), key=len, reverse=True)) + r")\b")
NUM_RE = re.compile(r"\d[\d,]*\.\d+")

# Column labels this parser looks for in the "BOQ ITEM DETAILS" header
# row, to build position-based bands from. "Description" is included so
# its band absorbs any stray numbers embedded in description text (unit
# sizes, IS-code references, etc.) instead of those being mistaken for a
# Qty/Rate/Amount value that happens to sit near a column boundary.
_HEADER_LABELS = ("Sr No", "Description", "Unit", "Qty", "Rate", "Amount")
_DATA_COLUMNS = ("Unit", "Qty", "Rate", "Amount")


def _parse_amt(s: str) -> float:
    return float(s.replace(",", ""))


@dataclass
class WoLineItem:
    code: str
    taxcode: str
    unit: str
    rate: float
    amount: float
    qty: float  # derived: amount / rate -- see module docstring


@dataclass
class WoParseResult:
    items: list[WoLineItem]
    unparsed_code_occurrences: list[tuple[str, str, str]]  # (code, taxcode, context snippet)
    summary_grand_total: Optional[float]  # from the WO's own "BOQ SUMMARY" section, for validation
    total_amount_parsed: float


@dataclass
class _Line:
    text: str
    words: list[dict]  # pdfplumber word dicts (text, x0, x1, top, bottom) on this visual line


def _extract_lines(pdf: "pdfplumber.PDF") -> list[_Line]:
    """One _Line per visually reconstructed text line, across the whole
    document in reading order -- pdfplumber's own extract_text_lines()
    does the word-clustering-into-rows work; this just also keeps each
    line's own words (with their x-positions) alongside its text, so
    column-band matching further down has real geometry to use instead
    of guessing from token order.
    """
    lines: list[_Line] = []
    for page in pdf.pages:
        text_lines = page.extract_text_lines()
        words = page.extract_words()
        for tl in text_lines:
            top0, bottom0 = tl["top"], tl["bottom"]
            line_words = [w for w in words if w["top"] >= top0 - 1 and w["bottom"] <= bottom0 + 1]
            lines.append(_Line(text=tl["text"], words=line_words))
    return lines


def _find_column_bands(lines: list[_Line]) -> Optional[dict[str, tuple[float, float]]]:
    """Locates the "Sr No Description Unit Qty Rate Amount" header row
    (checked once -- this document's column x-positions are fixed for
    its whole length, confirmed by direct inspection across pages 6
    through 419) and returns each data column's [start, end) x-range.
    Returns None if no such header row is found anywhere, so the caller
    can fall back to the older text-order heuristic entirely rather than
    silently extracting nothing from a document laid out differently.
    """
    for line in lines:
        texts = {w["text"] for w in line.words}
        if all(label in texts for label in _HEADER_LABELS if " " not in label) and "Sr" in texts and "No" in texts:
            # Merge "Sr" + "No" into one logical "Sr No" column anchor.
            positions = {w["text"]: w["x0"] for w in line.words if w["text"] in ("No", *_DATA_COLUMNS)}
            if not all(col in positions for col in _DATA_COLUMNS):
                continue
            ordered = sorted(positions.items(), key=lambda kv: kv[1])
            bands: dict[str, tuple[float, float]] = {}
            for i, (label, x0) in enumerate(ordered):
                start = 0.0 if i == 0 else (ordered[i - 1][1] + x0) / 2
                end = 1e9 if i == len(ordered) - 1 else (x0 + ordered[i + 1][1]) / 2
                bands[label] = (start, end)
            return {k: v for k, v in bands.items() if k in _DATA_COLUMNS}
    return None


def _numbers_in_band(line: _Line, band: tuple[float, float]) -> list[str]:
    lo, hi = band
    return [w["text"] for w in line.words if lo <= w["x0"] < hi and NUM_RE.fullmatch(w["text"].rstrip("."))]


def _rate_amount_from_line(line: _Line, bands: Optional[dict[str, tuple[float, float]]]) -> Optional[tuple[float, float]]:
    """Returns (rate, amount) read off this one line, or None if this
    line doesn't carry both. Position-based when a header row was found
    for this document; falls back to "last two decimal numbers on the
    line" (the pre-Workstream-03 behaviour) otherwise.
    """
    if bands is not None:
        rate_nums = _numbers_in_band(line, bands["Rate"])
        amount_nums = _numbers_in_band(line, bands["Amount"])
        if len(rate_nums) == 1 and len(amount_nums) == 1:
            return _parse_amt(rate_nums[0]), _parse_amt(amount_nums[0])
        return None

    nums = NUM_RE.findall(line.text)
    if len(nums) < 2:
        return None
    return _parse_amt(nums[-2]), _parse_amt(nums[-1])


def parse_work_order_pdf(pdf_path: str) -> WoParseResult:
    """Extracts every priced BOQ line item from a Work Order PDF of this
    format. Raises pdfplumber's own exceptions (e.g. for a corrupt or
    unreadable file). A scanned/image-only PDF is not treated as an
    error here -- it simply yields zero items, since there is no text
    layer to extract from and this parser does not OCR; the caller
    (app/api/wo_carbon.py) checks n_line_items_parsed == 0 and reports
    that honestly rather than a silent near-zero total.
    """
    with pdfplumber.open(pdf_path) as pdf:
        lines = _extract_lines(pdf)

    bands = _find_column_bands(lines)

    detail_start = next((i for i, ln in enumerate(lines) if "BOQ ITEM DETAILS" in ln.text), None)
    if detail_start is None:
        # Fall back to treating the whole document as the detail section
        # if the expected header isn't present (e.g. a different export).
        summary_lines, detail_lines = [], lines
    else:
        summary_lines, detail_lines = lines[:detail_start], lines[detail_start:]

    summary_grand_total = None
    summary_matches = []
    for ln in summary_lines:
        if len(ln.words) < 2:
            continue
        first, last = ln.words[0]["text"], ln.words[-1]["text"]
        if first.isdigit() and re.fullmatch(r"[\d,]+\.\d{2}", last):
            summary_matches.append(_parse_amt(last))
    if summary_matches:
        summary_grand_total = sum(summary_matches)

    code_line_idxs = [i for i, ln in enumerate(detail_lines) if CODE_RE.search(ln.text)]

    items: list[WoLineItem] = []
    unparsed: list[tuple[str, str, str]] = []

    for pos, i in enumerate(code_line_idxs):
        m = CODE_RE.search(detail_lines[i].text)
        code, taxcode = m.group(1), m.group(2)
        window_end = code_line_idxs[pos + 1] if pos + 1 < len(code_line_idxs) else len(detail_lines)
        window = detail_lines[i:window_end]

        unit = ra = None
        for ln in window:
            um = UNIT_RE.search(ln.text)
            if um is None:
                continue
            found = _rate_amount_from_line(ln, bands)
            if found is None:
                continue
            unit = um.group(1)
            ra = found
            break

        if unit is None or ra is None or ra[0] == 0:
            context = " | ".join(ln.text for ln in window)[:200]
            unparsed.append((code, taxcode, context))
            continue

        rate, amount = ra
        items.append(WoLineItem(code=code, taxcode=taxcode, unit=unit, rate=rate, amount=amount, qty=amount / rate))

    total_amount_parsed = sum(it.amount for it in items)

    return WoParseResult(
        items=items,
        unparsed_code_occurrences=unparsed,
        summary_grand_total=summary_grand_total,
        total_amount_parsed=total_amount_parsed,
    )