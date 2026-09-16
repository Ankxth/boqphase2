import { useState } from "react";
import { submitForm } from "../api";

const STRUCTURAL_SYSTEMS = [
  ["rcc_frame", "RCC Frame"],
  ["load_bearing_masonry", "Load-Bearing Masonry"],
  ["steel_frame", "Steel Frame"],
  ["composite", "Composite"],
];
const TYPOLOGIES = [
  ["residential", "Residential"],
  ["commercial", "Commercial"],
  ["institutional", "Institutional"],
  ["mixed_use", "Mixed Use"],
];
const FOUNDATION_TYPES = [
  ["isolated_footing", "Isolated Footing"],
  ["raft", "Raft"],
  ["pile", "Pile"],
  ["combined_footing", "Combined Footing"],
];
const FINISH_LEVELS = [
  ["economical", "Economical"],
  ["standard", "Standard"],
  ["premium", "Premium"],
];
const MEP_COMPLEXITY = [
  ["basic", "Basic"],
  ["standard", "Standard"],
  ["complex", "Complex"],
];
const SITE_CONDITIONS = [
  ["normal_soil", "Normal Soil"],
  ["rocky", "Rocky"],
  ["waterlogged", "Waterlogged"],
  ["reclaimed_land", "Reclaimed Land"],
];
const CEMENT_TYPES = [
  ["OPC", "OPC — Ordinary Portland"],
  ["PSC", "PSC — 25% GGBS Slag Blend"],
  ["PPC", "PPC — 30% Fly Ash Blend"],
];

function Select({ label, value, onChange, options, required }) {
  return (
    <div>
      <p className="spec-label mb-1">{label}{required && " *"}</p>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="field-input" required={required}>
        <option value="">— not specified —</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </div>
  );
}

function NumberField({ label, value, onChange, required, placeholder, step }) {
  return (
    <div>
      <p className="spec-label mb-1">{label}{required && " *"}</p>
      <input
        type="number"
        step={step || "any"}
        className="field-input"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        required={required}
      />
    </div>
  );
}

function TextField({ label, value, onChange, required, placeholder }) {
  return (
    <div>
      <p className="spec-label mb-1">{label}{required && " *"}</p>
      <input
        type="text"
        className="field-input"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        required={required}
      />
    </div>
  );
}

export default function TieredForm({ onSubmitted }) {
  // Mandatory
  const [gfaSqm, setGfaSqm] = useState("");
  const [location, setLocation] = useState("");
  const [structuralSystemType, setStructuralSystemType] = useState("");
  // Tier 2
  const [typology, setTypology] = useState("");
  const [numFloors, setNumFloors] = useState("");
  const [hasBasement, setHasBasement] = useState("");
  const [basementCount, setBasementCount] = useState("");
  const [foundationType, setFoundationType] = useState("");
  const [finishSpecLevel, setFinishSpecLevel] = useState("");
  const [parkingType, setParkingType] = useState("");
  const [parkingAreaSqm, setParkingAreaSqm] = useState("");
  // Tier 3
  const [concreteGradeMix, setConcreteGradeMix] = useState("");
  const [cementType, setCementType] = useState("");
  const [steelRatio, setSteelRatio] = useState("");
  const [facadeType, setFacadeType] = useState("");
  const [glazingPct, setGlazingPct] = useState("");
  const [mepComplexity, setMepComplexity] = useState("");
  const [greenCertTarget, setGreenCertTarget] = useState("");
  const [siteCondition, setSiteCondition] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!gfaSqm || !structuralSystemType) {
      setError("GFA and structural system are the two mandatory fields this tool can't estimate on its own.");
      return;
    }

    const payload = {
      gfa_sqm: Number(gfaSqm),
      location: location || null,
      structural_system_type: structuralSystemType,
      typology: typology || null,
      num_floors: numFloors ? Number(numFloors) : null,
      has_basement: hasBasement === "" ? null : hasBasement === "yes",
      basement_count: basementCount ? Number(basementCount) : null,
      foundation_type: foundationType || null,
      finish_spec_level: finishSpecLevel || null,
      parking_type: parkingType || null,
      parking_area_sqm: parkingAreaSqm ? Number(parkingAreaSqm) : null,
      concrete_grade_mix: concreteGradeMix || null,
      cement_type: cementType || null,
      steel_reinforcement_ratio_kg_per_sqm: steelRatio ? Number(steelRatio) : null,
      facade_type: facadeType || null,
      glazing_pct: glazingPct ? Number(glazingPct) : null,
      mep_complexity: mepComplexity || null,
      green_cert_target: greenCertTarget || null,
      site_condition: siteCondition || null,
    };

    setLoading(true);
    setError(null);
    console.log("[form] POST /form", payload);
    try {
      const project = await submitForm(payload);
      console.log("[form] response", project);
      onSubmitted(project);
    } catch (err) {
      console.error("[form] failed", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      <div>
        <p className="spec-label">Step 01</p>
        <h2 className="font-display text-4xl">Project Details</h2>
        <p className="text-ink/70 mt-1 max-w-2xl">
          Give whatever you know now — mandatory fields only if that's all you have. Anything you
          leave blank gets filled in on the next screen, either scaled from a comparable reference
          project's real BOQ or estimated, and every filled field shows exactly which.
        </p>
      </div>

      {error && (
        <div className="ledger p-4 flex items-center gap-3" style={{ borderColor: "var(--color-safety)" }}>
          <span className="spec-label !text-safety">Error</span>
          <p className="text-sm">{error}</p>
        </div>
      )}

      <div className="ledger p-6 space-y-4">
        <p className="spec-label !text-cyan">Mandatory</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <NumberField label="GFA (sqm)" value={gfaSqm} onChange={setGfaSqm} required placeholder="e.g. 50000" />
          <TextField label="Location" value={location} onChange={setLocation} placeholder="City, State" />
          <Select label="Structural System" value={structuralSystemType} onChange={setStructuralSystemType} options={STRUCTURAL_SYSTEMS} required />
        </div>
      </div>

      <div className="ledger p-6 space-y-4">
        <p className="spec-label">Tier 2</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Select label="Typology" value={typology} onChange={setTypology} options={TYPOLOGIES} />
          <NumberField label="Number of Floors" value={numFloors} onChange={setNumFloors} step="1" />
          <Select label="Has Basement" value={hasBasement} onChange={setHasBasement} options={[["yes", "Yes"], ["no", "No"]]} />
          <NumberField label="Basement Count" value={basementCount} onChange={setBasementCount} step="1" />
          <Select label="Foundation Type" value={foundationType} onChange={setFoundationType} options={FOUNDATION_TYPES} />
          <Select label="Finish Spec Level" value={finishSpecLevel} onChange={setFinishSpecLevel} options={FINISH_LEVELS} />
          <TextField label="Parking Type" value={parkingType} onChange={setParkingType} placeholder="e.g. basement" />
          <NumberField label="Parking Area (sqm)" value={parkingAreaSqm} onChange={setParkingAreaSqm} />
        </div>
      </div>

      <div className="ledger p-6 space-y-4">
        <p className="spec-label">Tier 3</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <TextField label="Concrete Grade Mix" value={concreteGradeMix} onChange={setConcreteGradeMix} placeholder="e.g. M30" />
          <Select label="Cement Type" value={cementType} onChange={setCementType} options={CEMENT_TYPES} />
          <NumberField label="Steel Ratio (kg/sqm)" value={steelRatio} onChange={setSteelRatio} />
          <TextField label="Facade Type" value={facadeType} onChange={setFacadeType} placeholder="e.g. cladding" />
          <NumberField label="Glazing (%)" value={glazingPct} onChange={setGlazingPct} />
          <Select label="MEP Complexity" value={mepComplexity} onChange={setMepComplexity} options={MEP_COMPLEXITY} />
          <TextField label="Green Cert Target" value={greenCertTarget} onChange={setGreenCertTarget} placeholder="e.g. GRIHA 3-star" />
          <Select label="Site Condition" value={siteCondition} onChange={setSiteCondition} options={SITE_CONDITIONS} />
        </div>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="bg-ink text-paper font-display text-lg tracking-wide px-6 py-3 hover:bg-cyan transition-colors disabled:opacity-40"
      >
        {loading ? "Filling gaps…" : "Submit & Auto-Fill →"}
      </button>
    </form>
  );
}
