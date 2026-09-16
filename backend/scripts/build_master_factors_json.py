"""One-time (re-run whenever the master sheet is updated) converter:
Provident_Combined_Master_Item_Codes.xlsx -> a lean JSON keyed by
Activity Number, for fast repeated lookups at request time without
loading a 7,100-row xlsx via openpyxl on every call.

Usage:
    python build_master_factors_json.py <path_to_combined_master.xlsx> <output.json>
"""

import json
import sys

import openpyxl


def build(xlsx_path: str, out_path: str) -> None:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Combined Master"]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    assert header[0] == "Activity number", f"Unexpected header, sheet layout may have changed: {header}"

    out = {}
    for r in rows[1:]:
        code = str(r[0])
        out[code] = {
            "desc": r[1],
            "unit": r[2],
            "contributes": r[6],
            "material_category": r[7],
            "top5": r[8],
            "ef_kgco2e_per_kg": r[9],
            "ef_source": r[10],
            "cea_adjusted": r[11],
            "evidence_tier": r[12],
            "unit_note": r[13],
        }

    with open(out_path, "w") as f:
        json.dump(out, f)

    print(f"Wrote {len(out)} codes to {out_path}")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])