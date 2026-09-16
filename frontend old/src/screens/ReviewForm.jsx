import { useEffect, useRef, useState } from "react";
import { getProject, patchProject, refineWithBoq } from "../api";

const ENUM_OPTIONS = {
  structural_system_type: ["rcc_frame", "load_bearing_masonry", "steel_frame", "composite"],
  typology: ["residential", "commercial", "institutional", "mixed_use"],
  foundation_type: ["isolated_footing", "raft", "pile", "combined_footing"],
  finish_spec_level: ["economical", "standard", "premium"],
  mep_complexity: ["basic", "standard", "complex"],
  site_condition: ["normal_soil", "rocky", "waterlogged", "reclaimed_land"],
  cement_type: ["OPC", "PSC", "PPC"],
};
const BOOLEAN_FIELDS = new Set(["has_basement"]);
const NUMBER_FIELDS = new Set([
  "gfa_sqm", "num_floors", "basement_count", "parking_area_sqm",
  "steel_reinforcement_ratio_kg_per_sqm", "glazing_pct",
]);

function SourceTag({ source }) {
  const labels = {
    "user-entered": "your input",
    "own-boq-extracted": "your BOQ",
    "boq-matched": "reference BOQ",
    "llm-estimated": "estimated",
    unset: "not set",
  };
  return <span className={`source-tag source-${source}`}>{labels[source] || source}</span>;
}

function FieldRow({ label, fieldName, field, draftValue, onChange }) {
  const isEnum = fieldName in ENUM_OPTIONS;
  const isBoolean = BOOLEAN_FIELDS.has(fieldName);
  const isNumber = NUMBER_FIELDS.has(fieldName);

  return (
    <div className="flex items-center gap-3 py-2 border-t border-ink/10 first:border-t-0">
      <span className="spec-label w-48 shrink-0">{label}</span>
      {isEnum ? (
        <select
          className="field-input flex-1"
          value={draftValue ?? ""}
          onChange={(e) => onChange(fieldName, e.target.value || null)}
        >
          <option value="">— not set —</option>
          {ENUM_OPTIONS[fieldName].map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      ) : isBoolean ? (
        <select
          className="field-input flex-1"
          value={draftValue === null || draftValue === undefined ? "" : draftValue ? "yes" : "no"}
          onChange={(e) => onChange(fieldName, e.target.value === "" ? null : e.target.value === "yes")}
        >
          <option value="">— not set —</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </select>
      ) : (
        <input
          type={isNumber ? "number" : "text"}
          className="field-input flex-1"
          value={draftValue ?? ""}
          onChange={(e) =>
            onChange(fieldName, isNumber ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value || null)
          }
        />
      )}
      <div className="w-28 shrink-0 text-right">
        <SourceTag source={field.source} />
      </div>
      <span className="data-num text-xs text-ink/40 w-14 text-right shrink-0">
        {field.source !== "unset" ? field.confidence.toFixed(1) : "—"}
      </span>
    </div>
  );
}

export default function ReviewForm({ projectId, onBack, onProceed }) {
  const [project, setProject] = useState(null);
  const [draft, setDraft] = useState({});
  const [dirty, setDirty] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [refineMessage, setRefineMessage] = useState(null);
  const [refining, setRefining] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const p = await getProject(projectId);
      setProject(p);
      const flat = {};
      for (const block of ["mandatory", "tier2", "tier3"]) {
        for (const [name, field] of Object.entries(p[block])) {
          flat[name] = field.value;
        }
      }
      setDraft(flat);
      setDirty(new Set());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId]);

  function handleChange(fieldName, value) {
    setDraft((prev) => ({ ...prev, [fieldName]: value }));
    setDirty((prev) => new Set(prev).add(fieldName));
  }

  async function handleSave() {
    if (dirty.size === 0) return;
    setSaving(true);
    setError(null);
    const payload = {};
    for (const name of dirty) payload[name] = draft[name];
    console.log("[review] PATCH /form/" + projectId, payload);
    try {
      await patchProject(projectId, payload);
      await load();
    } catch (err) {
      console.error("[review] save failed", err);
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleRefineFile(file) {
    if (!file) return;
    const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
    if (![".xlsx", ".xls"].includes(ext)) {
      setError(`Unsupported file type "${ext}" — upload .xlsx or .xls.`);
      return;
    }
    setRefining(true);
    setError(null);
    setRefineMessage(null);
    console.log("[review] POST /refine/" + projectId, file.name);
    try {
      const result = await refineWithBoq(projectId, file);
      console.log("[review] refine response", result);
      setRefineMessage(result.message);
      await load();
    } catch (err) {
      console.error("[review] refine failed", err);
      setError(err.message);
    } finally {
      setRefining(false);
    }
  }

  if (loading) {
    return <p className="spec-label">Loading project…</p>;
  }
  if (!project) {
    return (
      <div className="ledger p-4" style={{ borderColor: "var(--color-safety)" }}>
        <span className="spec-label !text-safety">Error</span>
        <p className="text-sm mt-1">{error || "Could not load this project."}</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <p className="spec-label">Step 02</p>
        <h2 className="font-display text-4xl">Review &amp; Refine</h2>
        <p className="text-ink/70 mt-1 max-w-2xl">
          Every field below is now filled — the tag on the right shows where it came from. Orange
          ("estimated") is a generic LLM guess and deserves the most scrutiny; grey ("reference
          BOQ") is scaled from a comparable project; green ("your BOQ" or "your input") is your
          own real data. Edit anything, or upload this project's own BOQ once you have one to
          override the estimates with real extracted quantities.
        </p>
      </div>

      {error && (
        <div className="ledger p-4 flex items-center gap-3" style={{ borderColor: "var(--color-safety)" }}>
          <span className="spec-label !text-safety">Error</span>
          <p className="text-sm">{error}</p>
        </div>
      )}

      {refineMessage && (
        <div className="ledger-note p-4">
          <span className="spec-label !text-cyan">BOQ Refinement</span>
          <p className="text-sm mt-1">{refineMessage}</p>
        </div>
      )}

      <div className="ledger p-6">
        <p className="spec-label !text-cyan mb-2">Mandatory</p>
        {Object.entries(project.mandatory).map(([name, field]) => (
          <FieldRow key={name} label={name.replace(/_/g, " ")} fieldName={name} field={field} draftValue={draft[name]} onChange={handleChange} />
        ))}
      </div>

      <div className="ledger p-6">
        <p className="spec-label mb-2">Tier 2</p>
        {Object.entries(project.tier2).map(([name, field]) => (
          <FieldRow key={name} label={name.replace(/_/g, " ")} fieldName={name} field={field} draftValue={draft[name]} onChange={handleChange} />
        ))}
      </div>

      <div className="ledger p-6">
        <p className="spec-label mb-2">Tier 3</p>
        {Object.entries(project.tier3).map(([name, field]) => (
          <FieldRow key={name} label={name.replace(/_/g, " ")} fieldName={name} field={field} draftValue={draft[name]} onChange={handleChange} />
        ))}
      </div>

      <div>
        <p className="spec-label mb-2">Refine with this project's own BOQ (optional)</p>
        <div
          onClick={() => fileInputRef.current.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); handleRefineFile(e.dataTransfer.files?.[0]); }}
          className={`ledger p-8 flex flex-col items-center justify-center text-center transition-colors cursor-pointer ${dragging ? "bg-cyan-dim/30" : ""}`}
          style={{ borderStyle: "dashed", borderWidth: 2 }}
        >
          <span className="spec-label">{refining ? "Extracting…" : "Drag file or click to browse"}</span>
          <p className="font-display text-xl mt-1">.xlsx / .xls</p>
          <input ref={fileInputRef} type="file" accept=".xlsx,.xls" className="hidden" onChange={(e) => handleRefineFile(e.target.files?.[0])} />
        </div>
      </div>

      <div className="flex gap-3 flex-wrap items-center">
        <button type="button" onClick={onBack} className="border border-ink px-6 py-3 font-display text-lg tracking-wide hover:bg-ink hover:text-paper transition-colors">
          ← Back
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={dirty.size === 0 || saving}
          className="border border-ink px-6 py-3 font-display text-lg tracking-wide hover:bg-ink hover:text-paper transition-colors disabled:opacity-40"
        >
          {saving ? "Saving…" : dirty.size > 0 ? `Save Changes (${dirty.size})` : "Saved"}
        </button>
        <button
          type="button"
          onClick={onProceed}
          disabled={dirty.size > 0}
          title={dirty.size > 0 ? "Save your changes first" : ""}
          className="bg-ink text-paper font-display text-lg tracking-wide px-6 py-3 hover:bg-cyan transition-colors disabled:opacity-40"
        >
          Calculate Results →
        </button>
      </div>
    </div>
  );
}
