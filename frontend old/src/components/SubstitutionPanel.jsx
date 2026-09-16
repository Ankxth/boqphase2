import { useEffect, useState } from "react";
import { applyBoqSubstitutions, getSubstitutionCatalog } from "../api";
import { CATEGORY_LABELS, fmt } from "../screens/BoqCarbonResults";

// Mirrors the "verified factor" / "placeholder factor" convention already
// established on the results table (BoqCarbonResults.jsx) -- cyan is the
// strongest trust tier, concrete-grey a middle tier, safety-orange the
// weakest. Nothing about a tier's meaning is invented here; it just maps
// the catalog's own evidence_tier string onto the app's existing visual
// vocabulary for "how much should you trust this number."
const EVIDENCE_TIER = {
  supplier_epd_verified: { cls: "border-cyan text-cyan", label: "supplier EPD verified" },
  ifc_primary_source: { cls: "border-concrete text-concrete", label: "IFC primary source" },
  placeholder_source: { cls: "border-safety text-safety", label: "placeholder source" },
};

function EvidenceTierBadge({ tier }) {
  const t = EVIDENCE_TIER[tier] ?? { cls: "border-ink/30 text-ink/50", label: tier ?? "unspecified" };
  return <span className={`spec-label px-2 py-1 border ${t.cls}`}>{t.label}</span>;
}

function ReviewStamp({ children }) {
  return (
    <span className="rev-stamp" style={{ borderColor: "var(--color-safety)", color: "var(--color-safety)" }}>
      {children}
    </span>
  );
}

function CatalogCard({ entry, selected, pct, onToggle, onPctChange }) {
  const exceeds = selected && pct > entry.max_recommended_pct;
  return (
    <div className={`ledger p-5 ${selected ? "" : "opacity-70"}`}>
      <div className="flex items-start gap-4 flex-wrap">
        <label className="flex items-center gap-2 mt-1 cursor-pointer shrink-0">
          <input
            type="checkbox"
            checked={selected}
            onChange={(e) => onToggle(e.target.checked)}
            className="w-4 h-4 accent-[var(--color-cyan)]"
          />
        </label>
        <div className="flex-1 min-w-64">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
            <p className="font-display text-xl">{entry.substitute_label ?? entry.id}</p>
            <EvidenceTierBadge tier={entry.evidence_tier} />
          </div>
          <p className="spec-label text-ink/50 mb-3">
            applies to: {CATEGORY_LABELS[entry.base_category] ?? entry.base_category}
            {entry.base_cement_type ? ` (${entry.base_cement_type} lines only)` : ""}
          </p>

          {entry.requires_supplier_match && (
            <div className="ledger-note p-3 mb-3">
              <p className="spec-label !text-cyan mb-1">Supplier-specific</p>
              <p className="text-xs text-ink/70">{entry.requires_supplier_match}</p>
            </div>
          )}

          <div className="flex items-center gap-3 mb-3">
            <p className="spec-label shrink-0">% of affected lines</p>
            <input
              type="range"
              min="0"
              max={Math.max(100, entry.max_recommended_pct)}
              step="1"
              value={pct}
              disabled={!selected}
              onChange={(e) => onPctChange(Number(e.target.value))}
              className="flex-1 accent-[var(--color-cyan)] disabled:opacity-40"
            />
            <input
              type="number"
              min="0"
              max={Math.max(100, entry.max_recommended_pct)}
              value={pct}
              disabled={!selected}
              onChange={(e) => onPctChange(Number(e.target.value))}
              className="field-input w-20 text-right disabled:opacity-40"
            />
            <span className="spec-label shrink-0">%</span>
          </div>
          <p className="spec-label text-ink/50 mb-3">
            max recommended: {fmt(entry.max_recommended_pct)}%
            {exceeds && <span className="!text-safety"> -- selected value exceeds this</span>}
          </p>

          <p className="text-sm text-ink/80 mb-2">{entry.reasoning}</p>
          <p className="text-xs text-ink/60 mb-2">
            <span className="font-medium">Structural note: </span>
            {entry.structural_caveat}
          </p>
          <p className="text-xs text-ink/50">
            <span className="font-medium">Source: </span>
            {entry.source}
          </p>
        </div>
      </div>
    </div>
  );
}

function ResultCard({ r }) {
  return (
    <div className="ledger p-5">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
        <p className="font-display text-xl">{r.label}</p>
        <div className="flex items-center gap-2 flex-wrap">
          <EvidenceTierBadge tier={r.evidence_tier} />
          {r.requires_engineering_review && <ReviewStamp>REQUIRES ENGINEERING REVIEW</ReviewStamp>}
        </div>
      </div>
      {r.requires_supplier_match && (
        <p className="text-xs text-ink/60 mb-2">
          <span className="font-medium">Supplier-specific: </span>
          {r.requires_supplier_match}
        </p>
      )}
      <p className="spec-label text-ink/50 mb-2">
        {r.affected_line_item_count} line item{r.affected_line_item_count === 1 ? "" : "s"} affected at{" "}
        {fmt(r.user_pct)}% (cap {fmt(r.max_recommended_pct)}%)
        {r.exceeds_recommended && <span className="!text-safety"> -- exceeds recommended ceiling</span>}
      </p>
      {r.affected_line_item_count === 0 ? (
        <p className="text-sm text-ink/60">
          No BOQ lines matched this substitution's category (and cement type, if applicable) -- not
          an error, this project simply doesn't have that material as classified.
        </p>
      ) : (
        <>
          <p className="data-num text-sm mb-1">
            {fmt(r.original_gwp_kg_co2e)} kg → {fmt(r.new_gwp_kg_co2e)} kg CO2e
          </p>
          <p className="data-num text-lg mb-2" style={{ color: "var(--color-carbon-down)" }}>
            −{fmt(r.savings_kg_co2e)} kg ({fmt(r.savings_pct_of_affected_lines, 1)}% of affected lines,{" "}
            {fmt(r.savings_pct_of_total_boq, 2)}% of total BOQ)
          </p>
        </>
      )}
      {r.requires_engineering_review && <p className="text-xs text-ink/60 mt-2">{r.structural_caveat}</p>}
    </div>
  );
}

export default function SubstitutionPanel({ file, sheetName, floorAreaSqm, floorAreaBasis }) {
  const [catalog, setCatalog] = useState(null);
  const [catalogError, setCatalogError] = useState(null);
  const [selections, setSelections] = useState({}); // id -> { included, pct }
  const [response, setResponse] = useState(null);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open || catalog) return;
    let cancelled = false;
    async function run() {
      try {
        console.log("[substitution] GET /boq-carbon/substitution-catalog");
        const data = await getSubstitutionCatalog();
        if (cancelled) return;
        console.log("[substitution] catalog", data);
        setCatalog(data);
        const initial = {};
        for (const entry of data) {
          initial[entry.id] = { included: false, pct: entry.max_recommended_pct };
        }
        setSelections(initial);
      } catch (err) {
        if (!cancelled) setCatalogError(err.message);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [open, catalog]);

  function toggle(id, included) {
    setSelections((s) => ({ ...s, [id]: { ...s[id], included } }));
  }
  function setPct(id, pct) {
    setSelections((s) => ({ ...s, [id]: { ...s[id], pct } }));
  }

  const includedIds = Object.entries(selections).filter(([, v]) => v.included).map(([id]) => id);

  async function runComparison() {
    setApplying(true);
    setApplyError(null);
    setResponse(null);
    try {
      const substitutions = includedIds.map((id) => ({ substitution_id: id, user_pct: selections[id].pct }));
      console.log("[substitution] POST /boq-carbon/substitute", { fileName: file?.name, sheetName, floorAreaSqm, floorAreaBasis, substitutions });
      const result = await applyBoqSubstitutions(file, { sheetName, floorAreaSqm, floorAreaBasis, substitutions });
      console.log("[substitution] response", result);
      setResponse(result);
    } catch (err) {
      console.error("[substitution] failed", err);
      setApplyError(err.message);
    } finally {
      setApplying(false);
    }
  }

  if (!open) {
    return (
      <div className="ledger p-6 flex items-center justify-between flex-wrap gap-4">
        <div>
          <p className="spec-label !text-cyan mb-1">Material Substitution</p>
          <p className="text-sm text-ink/70">
            Compare this BOQ against evidence-backed lower-carbon alternatives -- real recompute on
            the actual affected lines, not an estimated delta.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          disabled={!file}
          title={!file ? "Original BOQ file not available in this session -- re-upload to explore substitutions" : undefined}
          className="bg-ink text-paper font-display text-lg tracking-wide px-6 py-3 hover:bg-cyan transition-colors disabled:opacity-40 shrink-0"
        >
          Explore Substitutions →
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="spec-label !text-cyan">Material Substitution</p>
        <button type="button" onClick={() => setOpen(false)} className="spec-label px-3 py-1 border border-ink hover:bg-cyan-dim/40">
          collapse
        </button>
      </div>

      {catalogError && (
        <div className="ledger p-4" style={{ borderColor: "var(--color-safety)" }}>
          <span className="spec-label !text-safety">Error loading catalog</span>
          <p className="text-sm mt-1">{catalogError}</p>
        </div>
      )}

      {!catalog && !catalogError && <p className="spec-label">Loading catalog…</p>}

      {catalog && catalog.length === 0 && (
        <div className="ledger-note p-4">
          <p className="text-sm">No substitutions in the catalog yet.</p>
        </div>
      )}

      {catalog && catalog.length > 0 && (
        <>
          <div className="space-y-3">
            {catalog.map((entry) => (
              <CatalogCard
                key={entry.id}
                entry={entry}
                selected={!!selections[entry.id]?.included}
                pct={selections[entry.id]?.pct ?? entry.max_recommended_pct}
                onToggle={(v) => toggle(entry.id, v)}
                onPctChange={(v) => setPct(entry.id, v)}
              />
            ))}
          </div>

          <button
            type="button"
            onClick={runComparison}
            disabled={applying || includedIds.length === 0}
            className="bg-ink text-paper font-display text-lg tracking-wide px-6 py-3 hover:bg-cyan transition-colors disabled:opacity-40"
          >
            {applying ? "Recomputing…" : `Run Comparison (${includedIds.length} selected) →`}
          </button>

          {applyError && (
            <div className="ledger p-4" style={{ borderColor: "var(--color-safety)" }}>
              <span className="spec-label !text-safety">Error</span>
              <p className="text-sm mt-1">{applyError}</p>
            </div>
          )}

          {response && (
            <div className="space-y-3">
              <p className="spec-label mb-1">Results</p>
              {response.substitutions.map((r) => (
                <ResultCard key={r.substitution_id} r={r} />
              ))}

              {response.combined_impact && (
                <div className="ledger p-5" style={{ borderColor: "var(--color-cyan)", borderWidth: 2 }}>
                  <p className="spec-label !text-cyan mb-2">If all selected substitutions applied together</p>
                  {response.combined_impact.note ? (
                    <p className="text-sm text-ink/70">{response.combined_impact.note}</p>
                  ) : (
                    <>
                      <p className="data-num text-2xl" style={{ color: "var(--color-carbon-down)" }}>
                        −{fmt(response.combined_impact.total_savings_kg_co2e)} kg (
                        {fmt(response.combined_impact.total_savings_pct_of_total_boq, 2)}% of total BOQ)
                      </p>
                      {response.combined_impact.requires_engineering_review && (
                        <p className="spec-label !text-safety mt-2">
                          Includes at least one substitution requiring engineering review.
                        </p>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
