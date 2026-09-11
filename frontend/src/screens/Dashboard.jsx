import { useEffect, useState } from "react";
import { calculateProject, getSubstitutions } from "../api";

function fmt(n, digits = 0) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

// Indian Lakh/Crore notation for the summary cards specifically -- the
// full-precision "Rs.87,03,78,900" style figure is kept in the detailed
// breakdown table, but that string is roughly 3x longer than the other
// summary card values (tonnes, kgCO2e/sqm, points) and was overflowing
// its fixed-width grid card at any real project size. Crore/Lakh
// notation is also just the idiomatic way this audience reads large INR
// figures, not merely a way to make the string shorter.
function fmtINRShort(n) {
  if (n === null || n === undefined) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `Rs.${(n / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `Rs.${(n / 1e5).toFixed(2)} L`;
  return `Rs.${fmt(n)}`;
}

function ComparisonBadge({ label }) {
  const isAbove = label === "above typical";
  const isBelow = label === "below typical";
  return (
    <span
      className="rev-stamp"
      style={
        isAbove
          ? { borderColor: "var(--color-safety)", color: "var(--color-safety)" }
          : isBelow
          ? { borderColor: "var(--color-carbon-down)", color: "var(--color-carbon-down)" }
          : {}
      }
    >
      {label}
    </span>
  );
}

export default function Dashboard({ projectId, onStartOver }) {
  const [data, setData] = useState(null);
  const [subs, setSubs] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);
      try {
        console.log("[dashboard] POST /calculate/" + projectId + " and /substitute/" + projectId);
        const [calc, sub] = await Promise.all([calculateProject(projectId), getSubstitutions(projectId)]);
        if (cancelled) return;
        console.log("[dashboard] calculate response", calc);
        console.log("[dashboard] substitute response", sub);
        setData(calc);
        setSubs(sub);
      } catch (err) {
        console.error("[dashboard] failed", err);
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) return <p className="spec-label">Calculating…</p>;
  if (error) {
    return (
      <div className="ledger p-4" style={{ borderColor: "var(--color-safety)" }}>
        <span className="spec-label !text-safety">Error</span>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }
  if (!data) return null;

  const { carbon, cost, benchmark, griha_criterion_21: griha } = data;

  const cards = [
    { value: fmt(carbon.total_carbon_tonnes, 1), label: "tonnes CO2e total" },
    { value: fmt(carbon.carbon_per_sqm, 1), label: "kgCO2e / sqm" },
    { value: fmtINRShort(cost.total_cost_inr), label: "total cost (rough)" },
    { value: `${fmt(griha.points_estimated)} / ${griha.max_points}`, label: "GRIHA C21 points (est.)" },
  ];

  return (
    <div className="space-y-8">
      <div>
        <p className="spec-label">Step 03</p>
        <h2 className="font-display text-4xl">Results</h2>
        <p className="text-ink/70 mt-1 max-w-2xl">
          Concrete + steel only — see each section's scope note for what isn't included yet
          (finishes, MEP, and more). Every disclaimer below is load-bearing, not boilerplate.
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

      {/* Carbon breakdown */}
      <div>
        <p className="spec-label mb-2">Embodied Carbon Breakdown</p>
        <div className="ledger overflow-hidden overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-ink text-paper spec-label !text-paper text-left">
                <th className="px-3 py-2">Material</th>
                <th className="px-3 py-2 text-right">Quantity</th>
                <th className="px-3 py-2 text-right">Factor</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2 text-right">Carbon (kg)</th>
              </tr>
            </thead>
            <tbody>
              {carbon.breakdown.map((b, i) => (
                <tr key={i} className="border-t border-ink/10">
                  <td className="px-3 py-2">{b.material}</td>
                  <td className="px-3 py-2 data-num text-right">{fmt(b.quantity, 1)} {b.quantity_unit}</td>
                  <td className="px-3 py-2 data-num text-right">{fmt(b.factor_used, 4)} {b.factor_unit}</td>
                  <td className="px-3 py-2">
                    <span className="spec-label px-2 py-1 border border-cyan text-cyan">{b.factor_source}</span>
                  </td>
                  <td className="px-3 py-2 data-num text-right">{fmt(b.carbon_kg)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="spec-label mt-2 text-ink/50">{carbon.scope_note}</p>
      </div>

      {/* Cost breakdown */}
      <div>
        <p className="spec-label mb-2">Cost Estimate</p>
        <div className="ledger-note p-4 mb-3">
          <p className="text-sm">{cost.disclaimer}</p>
        </div>
        <div className="ledger overflow-hidden overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-ink text-paper spec-label !text-paper text-left">
                <th className="px-3 py-2">Material</th>
                <th className="px-3 py-2 text-right">Base Rate</th>
                <th className="px-3 py-2">Provenance</th>
                <th className="px-3 py-2 text-right">Inflation Adj.</th>
                <th className="px-3 py-2 text-right">Cost (INR)</th>
              </tr>
            </thead>
            <tbody>
              {cost.breakdown.map((b, i) => (
                <tr key={i} className="border-t border-ink/10">
                  <td className="px-3 py-2">{b.material}</td>
                  <td className="px-3 py-2 data-num text-right">Rs.{fmt(b.base_rate, 2)} {b.rate_unit}</td>
                  <td className="px-3 py-2">
                    <span className="spec-label px-2 py-1 border border-concrete text-concrete">{b.rate_provenance}</span>
                  </td>
                  <td className="px-3 py-2 data-num text-right">
                    {b.inflation_adjustment.applied ? `x${b.inflation_adjustment.multiplier.toFixed(3)}` : "none"}
                  </td>
                  <td className="px-3 py-2 data-num text-right">Rs.{fmt(b.cost_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cost.breakdown.some((b) => b.inflation_adjustment.applied) && (
          <div className="mt-2 space-y-1">
            {cost.breakdown.filter((b) => b.inflation_adjustment.applied).map((b, i) => (
              <p key={i} className="text-xs text-ink/60">
                <span className="font-medium">{b.material}:</span> {b.inflation_adjustment.reasoning}
              </p>
            ))}
          </div>
        )}
        <p className="data-num text-right mt-2 text-lg">
          Total: Rs.{fmt(cost.total_cost_inr)} · Rs.{fmt(cost.cost_per_sqm_inr, 2)}/sqm
        </p>
      </div>

      {/* Benchmark */}
      <div className="ledger p-6">
        <div className="flex items-center justify-between mb-3">
          <p className="spec-label !text-cyan">Typical-Building Benchmark</p>
          <ComparisonBadge label={benchmark.comparison_label} />
        </div>
        <div className="grid grid-cols-3 gap-4 mb-3">
          <div>
            <p className="data-num text-2xl">{fmt(benchmark.actual_carbon_per_sqm, 1)}</p>
            <p className="spec-label mt-1">actual kgCO2e/sqm</p>
          </div>
          <div>
            <p className="data-num text-2xl">{fmt(benchmark.baseline_carbon_per_sqm, 1)}</p>
            <p className="spec-label mt-1">typical ({benchmark.floor_band_used.replace("_", "-")})</p>
          </div>
          <div>
            <p className="data-num text-2xl">{benchmark.pct_difference_from_baseline > 0 ? "+" : ""}{fmt(benchmark.pct_difference_from_baseline, 2)}%</p>
            <p className="spec-label mt-1">difference</p>
          </div>
        </div>
        <p className="text-xs text-ink/60">{benchmark.disclaimer}</p>
      </div>

      {/* GRIHA */}
      <div className="ledger p-6">
        <p className="spec-label !text-cyan mb-3">GRIHA V6.0 Criterion 21 (GWP Reduction)</p>
        <div className="grid grid-cols-3 gap-4 mb-3">
          <div className="min-w-0">
            <p className="data-num text-xl md:text-2xl break-words">{fmt(griha.baseline_gwp_kg)}</p>
            <p className="spec-label mt-1">baseline GWP (kg)</p>
          </div>
          <div className="min-w-0">
            <p className="data-num text-xl md:text-2xl break-words">{fmt(griha.design_gwp_kg)}</p>
            <p className="spec-label mt-1">design GWP (kg)</p>
          </div>
          <div className="min-w-0">
            <p className="data-num text-xl md:text-2xl break-words">{griha.pct_reduction > 0 ? "+" : ""}{fmt(griha.pct_reduction, 2)}%</p>
            <p className="spec-label mt-1">{griha.points_estimated} / {griha.max_points} points (est.)</p>
          </div>
        </div>
        <p className="text-xs text-ink/60 mb-1">{griha.scope_note}</p>
        <p className="text-xs text-ink/60">{griha.disclaimer}</p>
      </div>

      {/* Substitutions */}
      {subs && (
        <div>
          <p className="spec-label mb-2">Substitution Suggestions</p>
          {subs.suggestions.length === 0 ? (
            <div className="ledger-note p-4">
              <p className="text-sm">No suggestions — this project is already at the lowest-carbon options tracked.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {subs.suggestions.map((s, i) => (
                <div key={i} className="ledger p-5">
                  <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
                    <p className="font-display text-xl">{s.description}</p>
                    {s.requires_engineering_review && (
                      <span className="rev-stamp" style={{ borderColor: "var(--color-safety)", color: "var(--color-safety)" }}>
                        REQUIRES ENGINEERING REVIEW
                      </span>
                    )}
                  </div>
                  <p className="data-num text-sm mb-2">{s.current_value} → {s.suggested_value}</p>
                  <p className="data-num text-lg" style={{ color: "var(--color-carbon-down)" }}>
                    −{fmt(s.savings_kg)} kg ({fmt(s.savings_pct, 2)}%)
                  </p>
                  <p className="text-xs text-ink/60 mt-2">{s.reasoning}</p>
                </div>
              ))}
              {subs.combined_impact && (
                <div className="ledger p-5" style={{ borderColor: "var(--color-cyan)", borderWidth: 2 }}>
                  <p className="spec-label !text-cyan mb-2">If all suggestions applied together</p>
                  <p className="data-num text-2xl" style={{ color: "var(--color-carbon-down)" }}>
                    −{fmt(subs.combined_impact.total_savings_kg)} kg ({fmt(subs.combined_impact.total_savings_pct, 2)}%)
                  </p>
                  {subs.combined_impact.requires_engineering_review && (
                    <p className="spec-label !text-safety mt-2">Includes at least one change requiring engineering review.</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <button
        onClick={onStartOver}
        className="border border-ink px-6 py-3 font-display text-lg tracking-wide hover:bg-ink hover:text-paper transition-colors"
      >
        Start a New Project
      </button>
    </div>
  );
}
