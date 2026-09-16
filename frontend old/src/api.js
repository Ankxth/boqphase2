// Base URL for the FastAPI backend. Adjust if you run it somewhere
// other than localhost:8000. Note: unlike the boq-carbon-frontend this
// was adapted from, this backend's routers are mounted at the ROOT
// (see backend/app/main.py -- app.include_router(form.router) etc.,
// no "/api" prefix), so there's no "/api" segment here.
const BASE_URL = "http://localhost:8000";

async function handle(res, label) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail
        ? typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail)
        : JSON.stringify(body);
    } catch {
      // response wasn't JSON -- fall back to statusText
    }
    throw new Error(`${label} failed (${res.status}): ${detail}`);
  }
  return res.json();
}

async function getJSON(path) {
  const res = await fetch(`${BASE_URL}${path}`);
  return handle(res, `GET ${path}`);
}

async function postJSON(path, body) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return handle(res, `POST ${path}`);
}

async function patchJSON(path, body) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handle(res, `PATCH ${path}`);
}

// --- Project lifecycle (api/form.py) ---

// Submits the tiered form. The backend immediately runs BOQ matching +
// LLM fallback and persists the result -- what comes back is already
// fully filled and ready for the review step, not a bare echo of what
// was submitted.
export function submitForm(fields) {
  return postJSON("/form", fields);
}

export function getProject(projectId) {
  return getJSON(`/form/${projectId}`);
}

// Applies review-step corrections. Only include the fields that
// actually changed -- each included field OVERWRITES unconditionally
// as source="user-entered", confidence=1.0, regardless of what was
// there before. Fields omitted are left untouched.
export function patchProject(projectId, edits) {
  return patchJSON(`/form/${projectId}`, edits);
}

// --- Calculation (api/calculate.py) ---

export function calculateProject(projectId) {
  return postJSON(`/calculate/${projectId}`);
}

// --- Substitution suggestions (api/substitute.py) ---

export function getSubstitutions(projectId) {
  return postJSON(`/substitute/${projectId}`);
}

// --- Own-BOQ refinement (api/refine.py) ---
// Multipart upload -- field name must be exactly "boq_file", matching
// the FastAPI endpoint's parameter name.
export async function refineWithBoq(projectId, file) {
  const form = new FormData();
  form.append("boq_file", file);
  const res = await fetch(`${BASE_URL}/refine/${projectId}`, { method: "POST", body: form });
  return handle(res, `POST /refine/${projectId}`);
}

// --- Health check, for the Shell header's connectivity dot ---
export async function pingBackend() {
  try {
    const res = await fetch(`${BASE_URL}/health`, { signal: AbortSignal.timeout(2500) });
    return res.ok;
  } catch {
    return false;
  }
}

// --- Phase 2: raw-BOQ-upload carbon calculation (api/boq_carbon.py) ---
// Multipart upload -- field name must be exactly "boq_file". sheetName,
// floorAreaSqm and floorAreaBasis are all optional, but floorAreaSqm and
// floorAreaBasis must be given together (same rule the backend enforces).
export async function calculateBoqCarbon(file, { sheetName, floorAreaSqm, floorAreaBasis } = {}) {
  const form = new FormData();
  form.append("boq_file", file);
  if (sheetName) form.append("sheet_name", sheetName);
  if (floorAreaSqm !== undefined && floorAreaSqm !== null) form.append("floor_area_sqm", String(floorAreaSqm));
  if (floorAreaBasis) form.append("floor_area_basis", floorAreaBasis);
  const res = await fetch(`${BASE_URL}/boq-carbon/calculate`, { method: "POST", body: form });
  return handle(res, "POST /boq-carbon/calculate");
}

// --- Phase 2: material substitution (api/boq_carbon_substitute.py) ---

// The full catalog -- every substitution's evidence tier, max recommended
// %, sourced reasoning, and structural caveat. Nothing about a catalog
// entry is hardcoded client-side; this is the single source of truth the
// substitution panel renders from.
export function getSubstitutionCatalog() {
  return getJSON("/boq-carbon/substitution-catalog");
}

// Stateless like /boq-carbon/calculate -- the backend doesn't persist
// anything between requests, so the ORIGINAL file must be re-sent here
// (not just the already-computed result), along with the exact same
// sheet/floor-area inputs used for the base calculation, so the
// substitution comparison is apples-to-apples with what's on screen.
// `substitutions` is an array of {substitution_id, user_pct}.
export async function applyBoqSubstitutions(
  file,
  { sheetName, floorAreaSqm, floorAreaBasis, substitutions } = {}
) {
  const form = new FormData();
  form.append("boq_file", file);
  if (sheetName) form.append("sheet_name", sheetName);
  if (floorAreaSqm !== undefined && floorAreaSqm !== null) form.append("floor_area_sqm", String(floorAreaSqm));
  if (floorAreaBasis) form.append("floor_area_basis", floorAreaBasis);
  form.append("substitutions", JSON.stringify(substitutions ?? []));
  const res = await fetch(`${BASE_URL}/boq-carbon/substitute`, { method: "POST", body: form });
  return handle(res, "POST /boq-carbon/substitute");
}

