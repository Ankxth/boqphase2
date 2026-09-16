import { useState } from "react";
import SubstitutionPanel from "../components/SubstitutionPanel";

export function fmt(n, digits = 0) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export const CATEGORY_LABELS = {
  rcc: "RCC (Structural Concrete)",
  pcc: "PCC (Plain/Blinding Concrete)",
  reinforcement_steel: "Reinforcement Steel",
  structural_steel: "Structural Steel Sections",
  brickwork: "Brickwork",
  blockwork: "Blockwork (AAC/Fly Ash)",
  plaster: "Plaster",
  tile: "Tile / Flooring",
  paint: "Paint",
  aluminium_glazing: "Aluminium / Glazing",
  glass: "Glass",
};

const VERIFIED_CATEGORIES = new Set(["rcc", "pcc", "reinforcement_steel"]);

function CategoryRow({ c }) {
  const verified = VERIFIED_CATEGORIES.has(c.category);
  return (
    <tr className="border-t border-ink/10">
      <td className="px-3 py-2">{CATEGORY_LABELS[c.category] ?? c.category}</td>
      <td className="px-3 py-2">
        <span
          className={`spec-label px-2 py-1 border ${verified ? "border-cyan text-cyan" : "border-safety text-safety"}`}
        >
          {verified ? "verified factor" : "placeholder factor"}
        </span>
      </td>
      <td className="px-3 py-2 data-num text-right">{c.line_item_count}</td>
      <td className="px-3 py-2 data-num text-right">{fmt(c.gwp_kg_co2e)}</td>
      <td className="px-3 py-2 data-num text-right">{fmt(c.pct_of_total, 1)}%</td>
    </tr>
  );
}

export default function BoqCarbonResults({ result, boqParams, onStartOver }) {
  const [showLines, setShowLines] = useState(0);

  if (!result) return null;

  const coveragePct = result.n_lines_total ? (result.n_lines_computed / result.n_lines_total) * 100 : 0;
  const hasArea = !!result.floor_area_sqm;

  const cards = [
    { value: fmt(result.total_gwp_tonnes_co2e, 1), label: "tonnes CO2e total" },
    { value: hasArea ? fmt(result.gwp_per_sqm, 1) : "—", label: "kgCO2e / sqm" },
    { value: hasArea ? fmt(result.gwp_per_sqft, 2) : "—", label: "kgCO2e / sqft" },
    { value: `${fmt(coveragePct, 1)}%`, label: "lines covered in total" },
  ];

  const computedLines = result.line_items
    .filter((li) => li.gwp_kg_co2e !== null && li.gwp_kg_co2e !== undefined)
    .slice()
    .sort((a, b) => b.gwp_kg_co2e - a.gwp_kg_co2e);

  return (
    <div className="space-y-8">
      <div>
        <p className="spec-label">Step 02 · Phase 2</p>
        <h2 className="font-display text-4xl">BOQ Carbon Results</h2>
        <p className="text-ink/70 mt-1 max-w-2xl">
          {result.source_file} (sheet: {result.sheet_name}) — {result.n_lines_total} billable lines
          parsed, {result.n_lines_classified} classified, {result.n_lines_computed} contributed to
          the total below.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {cards.map((c) => (
          <div key={c.label} className="ledger p-4 min-w-0">
            <p className="data-num text-2xl md:text-3xl break-words">{c.value}</p>
            <p className="spec-label mt-1">{c.label}</p>
          </div>
        ))}
      </div>

      {hasArea ? (
        <div className="ledger-note p-4">
          <p className="spec-label mb-1">
            Floor area: {fmt(result.floor_area_sqm, 1)} sqm ({result.floor_area_basis})
          </p>
          <p className="text-sm">{result.floor_area_basis_note}</p>
        </div>
      ) : (
        <div className="ledger-note p-4">
          <p className="text-sm">
            No floor area given -- totals only. Go back and supply a floor area + basis for a
            kgCO2e/sqm figure.
          </p>
        </div>
      )}

      {/* Category breakdown */}
      <div>
        <p className="spec-label mb-2">Embodied Carbon by Category</p>
        <div className="ledger overflow-hidden overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-ink text-paper spec-label !text-paper text-left">
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2">Factor Source</th>
                <th className="px-3 py-2 text-right">Line Items</th>
                <th className="px-3 py-2 text-right">Carbon (kg CO2e)</th>
                <th className="px-3 py-2 text-right">% of Total</th>
              </tr>
            </thead>
            <tbody>
              {result.by_category.map((c) => (
                <CategoryRow key={c.category} c={c} />
              ))}
            </tbody>
          </table>
        </div>
        <p className="spec-label mt-2 text-ink/50">{result.scope_note}</p>
      </div>

      <div className="ledger-note p-4">
        <p className="text-sm">{result.factor_disclaimer}</p>
      </div>

      {/* Line item drill-down */}
      <div>
        <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
          <p className="spec-label">Line Item Detail</p>
          <div className="flex gap-2">
            {[10, 25, 100].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setShowLines(showLines === n ? 0 : n)}
                className={`spec-label px-3 py-1 border border-ink ${
                  showLines === n ? "bg-ink text-paper" : "hover:bg-cyan-dim/40"
                }`}
              >
                top {n}
              </button>
            ))}
          </div>
        </div>
        {showLines === 0 ? (
          <p className="text-sm text-ink/60">Pick a range above to inspect individual line items, highest carbon first.</p>
        ) : (
          <div className="space-y-2">
            {computedLines.slice(0, showLines).map((li) => (
              <div key={li.row} className="ledger p-4">
                <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
                  <span className="spec-label px-2 py-1 border border-cyan text-cyan">
                    {CATEGORY_LABELS[li.category] ?? li.category}
                  </span>
                  <span className="data-num text-lg">{fmt(li.gwp_kg_co2e)} kg CO2e</span>
                </div>
                <p className="text-sm text-ink/80">{li.enriched_description.slice(0, 220)}</p>
                <p className="spec-label mt-1 text-ink/50">row {li.row} · {li.basis_note}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <SubstitutionPanel
        file={boqParams?.file}
        sheetName={boqParams?.sheetName}
        floorAreaSqm={boqParams?.floorAreaSqm}
        floorAreaBasis={boqParams?.floorAreaBasis}
      />

      <button
        onClick={onStartOver}
        className="border border-ink px-6 py-3 font-display text-lg tracking-wide hover:bg-ink hover:text-paper transition-colors"
      >
        Upload Another BOQ
      </button>
    </div>
  );
}
