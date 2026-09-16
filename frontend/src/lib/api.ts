import axios from "axios";
import type {
  BillPeriod,
  BoqCarbonResult,
  BoqSubstitutionResponse,
  CalculateResponse,
  ChatAnswer,
  ChatToolCatalog,
  DashboardResult,
  FactorHistoryEntry,
  FloorAreaBasis,
  FormSubmission,
  OnboardingJob,
  Phase3Baseline,
  ProjectSchema,
  ProjectSummary,
  RefineResponse,
  SubstituteResponse,
  SubstitutionCatalogEntry,
  WoCarbonResult,
} from "./types";

// Same-origin by default (so a desktop-wrapped build that serves the
// API from the app itself just works); override for local dev against
// a separately-running backend via .env's VITE_API_BASE_URL.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const http = axios.create({ baseURL: BASE_URL });

// ---------------------------------------------------------------------------
// Phase 1 -- tiered conceptual estimator
// ---------------------------------------------------------------------------

export async function submitForm(body: FormSubmission): Promise<ProjectSchema> {
  const { data } = await http.post<ProjectSchema>("/form", body);
  return data;
}

export async function getProject(projectId: string, companyId: string): Promise<ProjectSchema> {
  const { data } = await http.get<ProjectSchema>(`/form/${projectId}`, { params: { company_id: companyId } });
  return data;
}

export async function editProject(projectId: string, companyId: string, body: FormSubmission): Promise<ProjectSchema> {
  const { data } = await http.patch<ProjectSchema>(`/form/${projectId}`, body, { params: { company_id: companyId } });
  return data;
}

export async function calculateProject(projectId: string, companyId: string): Promise<CalculateResponse> {
  const { data } = await http.post<CalculateResponse>(`/calculate/${projectId}`, null, { params: { company_id: companyId } });
  return data;
}

export async function substituteProject(projectId: string, companyId: string): Promise<SubstituteResponse> {
  const { data } = await http.post<SubstituteResponse>(`/substitute/${projectId}`, null, { params: { company_id: companyId } });
  return data;
}

export async function refineWithOwnBoq(projectId: string, companyId: string, file: File): Promise<RefineResponse> {
  const form = new FormData();
  form.append("boq_file", file);
  const { data } = await http.post<RefineResponse>(`/refine/${projectId}`, form, { params: { company_id: companyId } });
  return data;
}

// ---------------------------------------------------------------------------
// Phase 2 -- BOQ / Work Order carbon calculators
// ---------------------------------------------------------------------------

export interface BoqCalculateOptions {
  sheetName?: string;
  floorAreaSqm?: number;
  floorAreaBasis?: FloorAreaBasis;
  registerAsReference?: boolean;
  companyId?: string;
  structuralSystemType?: string;
  typology?: string;
  referenceSlug?: string;
  useLlmExtractionFallback?: boolean;
}

export async function calculateBoqCarbon(file: File, opts: BoqCalculateOptions = {}): Promise<BoqCarbonResult> {
  const form = new FormData();
  form.append("boq_file", file);
  if (opts.sheetName) form.append("sheet_name", opts.sheetName);
  if (opts.floorAreaSqm != null) form.append("floor_area_sqm", String(opts.floorAreaSqm));
  if (opts.floorAreaBasis) form.append("floor_area_basis", opts.floorAreaBasis);
  form.append("register_as_reference", String(!!opts.registerAsReference));
  if (opts.companyId) form.append("company_id", opts.companyId);
  if (opts.structuralSystemType) form.append("structural_system_type", opts.structuralSystemType);
  if (opts.typology) form.append("typology", opts.typology);
  if (opts.referenceSlug) form.append("reference_slug", opts.referenceSlug);
  form.append("use_llm_extraction_fallback", String(opts.useLlmExtractionFallback ?? true));
  const { data } = await http.post<BoqCarbonResult>("/boq-carbon/calculate", form);
  return data;
}

export async function getSubstitutionCatalog(): Promise<SubstitutionCatalogEntry[]> {
  const { data } = await http.get<SubstitutionCatalogEntry[]>("/boq-carbon/substitution-catalog");
  return data;
}

export async function substituteBoqCarbon(
  file: File,
  substitutions: Record<string, number>,
  opts: { sheetName?: string; floorAreaSqm?: number; floorAreaBasis?: FloorAreaBasis } = {}
): Promise<BoqSubstitutionResponse> {
  const form = new FormData();
  form.append("boq_file", file);
  if (opts.sheetName) form.append("sheet_name", opts.sheetName);
  if (opts.floorAreaSqm != null) form.append("floor_area_sqm", String(opts.floorAreaSqm));
  if (opts.floorAreaBasis) form.append("floor_area_basis", opts.floorAreaBasis);
  form.append("substitutions", JSON.stringify(substitutions));
  const { data } = await http.post<BoqSubstitutionResponse>("/boq-carbon/substitute", form);
  return data;
}

export interface WoCalculateOptions {
  floorAreaSqm?: number;
  floorAreaBasis?: FloorAreaBasis;
  companyId?: string;
  registerAsReference?: boolean;
  structuralSystemType?: string;
  typology?: string;
  referenceSlug?: string;
}

export async function calculateWoCarbon(file: File, opts: WoCalculateOptions = {}): Promise<WoCarbonResult> {
  const form = new FormData();
  form.append("wo_file", file);
  if (opts.floorAreaSqm != null) form.append("floor_area_sqm", String(opts.floorAreaSqm));
  if (opts.floorAreaBasis) form.append("floor_area_basis", opts.floorAreaBasis);
  if (opts.companyId) form.append("company_id", opts.companyId);
  form.append("register_as_reference", String(!!opts.registerAsReference));
  if (opts.structuralSystemType) form.append("structural_system_type", opts.structuralSystemType);
  if (opts.typology) form.append("typology", opts.typology);
  if (opts.referenceSlug) form.append("reference_slug", opts.referenceSlug);
  const { data } = await http.post<WoCarbonResult>("/wo-carbon/calculate", form);
  return data;
}

// ---------------------------------------------------------------------------
// Onboarding -- per-company item-code dataset pipeline
// ---------------------------------------------------------------------------

export async function uploadItemCodes(companyId: string, file: File, useLlmDraft = true, amountsByCode?: Record<string, number>): Promise<OnboardingJob> {
  const form = new FormData();
  form.append("item_code_file", file);
  form.append("use_llm_draft", String(useLlmDraft));
  if (amountsByCode) form.append("amounts_by_code", JSON.stringify(amountsByCode));
  const { data } = await http.post<OnboardingJob>(`/onboarding/${companyId}/upload`, form);
  return data;
}

export async function getOnboardingJob(companyId: string, jobId: string): Promise<OnboardingJob> {
  const { data } = await http.get<OnboardingJob>(`/onboarding/${companyId}/jobs/${jobId}`);
  return data;
}

export interface ConfirmDecision {
  code: string;
  fields?: Record<string, unknown>;
  register_as_new_category?: string | null;
}

export async function confirmOnboardingJob(companyId: string, jobId: string, decisions: ConfirmDecision[]): Promise<unknown> {
  const { data } = await http.post(`/onboarding/${companyId}/jobs/${jobId}/confirm`, { decisions });
  return data;
}

export async function listCanonicalCategories(): Promise<unknown> {
  const { data } = await http.get("/onboarding/canonical-categories");
  return data;
}

// ---------------------------------------------------------------------------
// Factors -- versioned emission-factor snapshot & history
// ---------------------------------------------------------------------------

export async function getCurrentFactorSnapshot(asOf?: string): Promise<Record<string, unknown>> {
  const { data } = await http.get<Record<string, unknown>>("/factors/current", { params: asOf ? { as_of: asOf } : {} });
  return data;
}

export async function getFactorCategoryHistory(category: string): Promise<FactorHistoryEntry[]> {
  const { data } = await http.get<FactorHistoryEntry[]>(`/factors/${category}/history`);
  return data;
}

// ---------------------------------------------------------------------------
// Phase 3 -- baselines, bills, dashboard, chatbot
// ---------------------------------------------------------------------------

export async function listProjects(companyId: string): Promise<ProjectSummary[]> {
  const { data } = await http.get<ProjectSummary[]>("/phase3/projects", { params: { company_id: companyId } });
  return data;
}

export interface RecordBaselineOptions {
  file?: File;
  sheetName?: string;
  floorAreaSqm?: number;
  floorAreaBasis?: FloorAreaBasis;
  companyId?: string;
  structuralSystemType?: string;
  numFloors?: number;
  typology?: string;
  overwrite?: boolean;
}

export async function recordBaseline(
  projectId: string,
  sourceType: "boq" | "wo" | "phase1_estimate",
  opts: RecordBaselineOptions = {}
): Promise<Phase3Baseline> {
  const form = new FormData();
  form.append("source_type", sourceType);
  if (opts.file) form.append("file", opts.file);
  if (opts.sheetName) form.append("sheet_name", opts.sheetName);
  if (opts.floorAreaSqm != null) form.append("floor_area_sqm", String(opts.floorAreaSqm));
  if (opts.floorAreaBasis) form.append("floor_area_basis", opts.floorAreaBasis);
  if (opts.companyId) form.append("company_id", opts.companyId);
  if (opts.structuralSystemType) form.append("structural_system_type", opts.structuralSystemType);
  if (opts.numFloors != null) form.append("num_floors", String(opts.numFloors));
  if (opts.typology) form.append("typology", opts.typology);
  form.append("overwrite", String(!!opts.overwrite));
  const { data } = await http.post<Phase3Baseline>(`/phase3/projects/${projectId}/baseline`, form);
  return data;
}

export interface UploadBillOptions {
  sheetName?: string;
  statedPercentComplete?: number;
  companyId?: string;
  overwrite?: boolean;
}

export async function uploadBill(
  projectId: string,
  period: string,
  billedDate: string,
  file: File,
  opts: UploadBillOptions = {}
): Promise<BillPeriod> {
  const form = new FormData();
  form.append("period", period);
  form.append("billed_date", billedDate);
  form.append("bill_file", file);
  if (opts.sheetName) form.append("sheet_name", opts.sheetName);
  if (opts.statedPercentComplete != null) form.append("stated_percent_complete", String(opts.statedPercentComplete));
  if (opts.companyId) form.append("company_id", opts.companyId);
  form.append("overwrite", String(!!opts.overwrite));
  const { data } = await http.post<BillPeriod>(`/phase3/projects/${projectId}/bills`, form);
  return data;
}

export async function listBills(projectId: string, companyId: string): Promise<BillPeriod[]> {
  const { data } = await http.get<BillPeriod[]>(`/phase3/projects/${projectId}/bills`, { params: { company_id: companyId } });
  return data;
}

export async function getDashboard(projectId: string, companyId: string): Promise<DashboardResult> {
  const { data } = await http.get<DashboardResult>(`/phase3/projects/${projectId}/dashboard`, { params: { company_id: companyId } });
  return data;
}

export async function listChatTools(): Promise<ChatToolCatalog> {
  const { data } = await http.get<ChatToolCatalog>("/phase3/chat/tools");
  return data;
}

export async function askChat(projectId: string, companyId: string, question: string): Promise<ChatAnswer> {
  const { data } = await http.post<ChatAnswer>(`/phase3/projects/${projectId}/chat`, { question }, { params: { company_id: companyId } });
  return data;
}

export async function health(): Promise<unknown> {
  const { data } = await http.get("/health");
  return data;
}

/** Extracts FastAPI's {detail: "..."} (or its 422 validation array) into one readable string. */
export function apiErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => (typeof d === "string" ? d : d?.msg || JSON.stringify(d))).join("; ");
    }
    if (err.code === "ERR_NETWORK") {
      return `Can't reach the backend at ${BASE_URL} -- is it running, and does it allow this origin (CORS)?`;
    }
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}
