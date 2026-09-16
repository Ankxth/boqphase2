import { useState } from "react";
import { calculateBoqCarbon } from "../api";

const BASIS_OPTIONS = [
  ["built_up_total", "Built-up Total (basement + podium + tower + terrace, everything the BOQ prices)"],
  ["net_internal_gia", "Net Internal / Gross Internal Area (unit areas only)"],
  ["carpet_saleable", "Carpet / Saleable Area"],
  ["other", "Other"],
];

// 1 sqm = 10.7639 sqft (same constant the backend uses for its own
// kgCO2e/sqft output -- see calculation_engine.py's SQM_TO_SQFT). The
// backend's floor_area_sqm field is always sqm; this toggle just lets
// the PERSON enter the number in whichever unit their project docs
// actually use, and converts once, here, before it ever leaves the
// browser -- rather than making them do that arithmetic by hand, which
// is exactly the kind of silent unit mismatch the note below warns about.
const SQM_TO_SQFT = 10.7639;

export default function BoqCarbonUpload({ onComputed }) {
  const [file, setFile] = useState(null);
  const [sheetName, setSheetName] = useState("");
  const [floorArea, setFloorArea] = useState("");
  const [floorAreaUnit, setFloorAreaUnit] = useState("sqm"); // "sqm" | "sqft"
  const [floorAreaBasis, setFloorAreaBasis] = useState("built_up_total");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const floorAreaSqm =
    floorArea && !Number.isNaN(Number(floorArea))
      ? floorAreaUnit === "sqft"
        ? Number(floorArea) / SQM_TO_SQFT
        : Number(floorArea)
      : undefined;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!file) {
      setError("Choose a BOQ file (.xlsx or .xls) first.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const params = {
        sheetName: sheetName || undefined,
        floorAreaSqm,
        floorAreaBasis: floorAreaSqm !== undefined ? floorAreaBasis : undefined,
      };
      console.log("[boq-carbon] POST /boq-carbon/calculate", {
        fileName: file.name,
        ...params,
        enteredAs: floorArea ? `${floorArea} ${floorAreaUnit}` : null,
      });
      const result = await calculateBoqCarbon(file, params);
      console.log("[boq-carbon] response", result);
      // Pass the original file + the exact inputs used for this
      // calculation up alongside the result -- Phase 2's /substitute
      // endpoint is stateless and re-parses the BOQ from scratch, so the
      // substitution panel needs the same file and params again, not
      // just the computed JSON.
      onComputed(result, { file, ...params });
    } catch (err) {
      console.error("[boq-carbon] failed", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      <div>
        <p className="spec-label">Step 01 · Phase 2</p>
        <h2 className="font-display text-4xl">Upload BOQ</h2>
        <p className="text-ink/70 mt-1 max-w-2xl">
          Upload a raw Bill of Quantities directly -- no tiered form, no reference-project
          matching. Every billable line is parsed, classified by material, and carbon-costed
          from real IFC/ICE/CEA factors. Concrete and reinforcement steel use the same verified
          factors as the conceptual estimator; every other category is a placeholder factor
          until verified (flagged on the results screen).
        </p>
      </div>

      {error && (
        <div className="ledger p-4 flex items-center gap-3" style={{ borderColor: "var(--color-safety)" }}>
          <span className="spec-label !text-safety">Error</span>
          <p className="text-sm">{error}</p>
        </div>
      )}

      <div className="ledger p-6 space-y-4">
        <p className="spec-label !text-cyan">BOQ File</p>
        <div>
          <p className="spec-label mb-1">File (.xlsx / .xls) *</p>
          <input
            type="file"
            accept=".xlsx,.xls"
            className="field-input"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
          />
        </div>
        <div>
          <p className="spec-label mb-1">Sheet Name (optional)</p>
          <input
            type="text"
            className="field-input"
            value={sheetName}
            placeholder="leave blank to auto-pick the first non-supplementary sheet"
            onChange={(e) => setSheetName(e.target.value)}
          />
        </div>
      </div>

      <div className="ledger-note p-4">
        <p className="text-sm">
          A whole-building carbon total divided by the wrong floor-area definition can look like a
          large over- or under-estimate even when the underlying quantities are correct -- a real
          project's declared area was found to be 1/8.5 of its true built-up area. Give both the
          number and its basis, or leave both blank for a totals-only result.
        </p>
      </div>

      <div className="ledger p-6 space-y-4">
        <p className="spec-label">Floor Area (optional -- give both fields together)</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="spec-label mb-1">Floor Area</p>
            <div className="flex">
              <input
                type="number"
                step="any"
                min="0"
                className="field-input"
                value={floorArea}
                placeholder={floorAreaUnit === "sqft" ? "e.g. 1950000" : "e.g. 181150"}
                onChange={(e) => setFloorArea(e.target.value)}
              />
              <div className="flex border border-l-0 border-ink/40 shrink-0">
                {["sqm", "sqft"].map((u) => (
                  <button
                    key={u}
                    type="button"
                    onClick={() => setFloorAreaUnit(u)}
                    className={`spec-label px-3 ${
                      floorAreaUnit === u ? "bg-ink text-paper" : "hover:bg-cyan-dim/40"
                    }`}
                  >
                    {u}
                  </button>
                ))}
              </div>
            </div>
            {floorArea && floorAreaUnit === "sqft" && floorAreaSqm !== undefined && (
              <p className="spec-label mt-1 text-ink/50">
                = {floorAreaSqm.toLocaleString("en-IN", { maximumFractionDigits: 1 })} sqm -- converted before sending,
                the backend always receives sqm
              </p>
            )}
          </div>
          <div>
            <p className="spec-label mb-1">Basis</p>
            <select
              value={floorAreaBasis}
              onChange={(e) => setFloorAreaBasis(e.target.value)}
              className="field-input"
              disabled={!floorArea}
            >
              {BASIS_OPTIONS.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="bg-ink text-paper font-display text-lg tracking-wide px-6 py-3 hover:bg-cyan transition-colors disabled:opacity-40"
      >
        {loading ? "Calculating…" : "Calculate Embodied Carbon →"}
      </button>
    </form>
  );
}
