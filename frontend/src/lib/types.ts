// Mirrors backend/app/schemas/* and the response models in
// app/api/*.py -- kept intentionally close to the OpenAPI shapes
// rather than "improved," so a diff against boqws13openapi.json
// stays easy for whoever maintains this next.

export type FieldSource = "user-entered" | "boq-matched" | "own-boq-extracted" | "llm-estimated" | "unset";

export interface FieldValue<T> {
  value: T | null;
  source: FieldSource;
  confidence: number;
}

export type StructuralSystemType = "rcc_frame" | "load_bearing_masonry" | "steel_frame" | "composite";
export type Typology = "residential" | "commercial" | "institutional" | "mixed_use";
export type FoundationType = "isolated_footing" | "raft" | "pile" | "combined_footing";
export type FinishSpecLevel = "economical" | "standard" | "premium";
export type MepComplexity = "basic" | "standard" | "complex";
export type SiteCondition = "normal_soil" | "rocky" | "waterlogged" | "reclaimed_land";
export type CementType = "OPC" | "PSC" | "PPC";
export type FloorAreaBasis = "net_internal_gia" | "built_up_total" | "carpet_saleable" | "other";
export type BaselineSourceType = "boq" | "wo" | "phase1_estimate";

export interface MandatoryFields {
  gfa_sqm: FieldValue<number>;
  location: FieldValue<string>;
  structural_system_type: FieldValue<StructuralSystemType>;
}

export interface Tier2Fields {
  typology: FieldValue<Typology>;
  num_floors: FieldValue<number>;
  has_basement: FieldValue<boolean>;
  basement_count: FieldValue<number>;
  foundation_type: FieldValue<FoundationType>;
  finish_spec_level: FieldValue<FinishSpecLevel>;
  parking_type: FieldValue<string>;
  parking_area_sqm: FieldValue<number>;
}

export interface Tier3Fields {
  concrete_grade_mix: FieldValue<string>;
  cement_type: FieldValue<CementType>;
  steel_reinforcement_ratio_kg_per_sqm: FieldValue<number>;
  facade_type: FieldValue<string>;
  glazing_pct: FieldValue<number>;
  mep_complexity: FieldValue<MepComplexity>;
  green_cert_target: FieldValue<string>;
  site_condition: FieldValue<SiteCondition>;
}

export interface ProjectSchema {
  project_id: string;
  company_id: string;
  project_name: string | null;
  mandatory: MandatoryFields;
  tier2: Tier2Fields;
  tier3: Tier3Fields;
}

export interface FormSubmission {
  company_id?: string | null;
  project_name?: string | null;
  gfa_sqm?: number | null;
  location?: string | null;
  structural_system_type?: StructuralSystemType | null;
  typology?: Typology | null;
  num_floors?: number | null;
  has_basement?: boolean | null;
  basement_count?: number | null;
  foundation_type?: FoundationType | null;
  finish_spec_level?: FinishSpecLevel | null;
  parking_type?: string | null;
  parking_area_sqm?: number | null;
  concrete_grade_mix?: string | null;
  cement_type?: CementType | null;
  steel_reinforcement_ratio_kg_per_sqm?: number | null;
  facade_type?: string | null;
  glazing_pct?: number | null;
  mep_complexity?: MepComplexity | null;
  green_cert_target?: string | null;
  site_condition?: SiteCondition | null;
}

export interface MaterialBreakdown {
  material: string;
  quantity: number;
  quantity_unit: string;
  factor_used: number;
  factor_unit: string;
  factor_source: string;
  carbon_kg: number;
  quantity_source: string;
}

export interface CalculationResult {
  project_id: string;
  gfa_sqm: number;
  breakdown: MaterialBreakdown[];
  total_carbon_kg: number;
  total_carbon_tonnes: number;
  carbon_per_sqm: number;
  carbon_per_sqft: number;
  scope_note: string;
}

export interface InflationAdjustment {
  multiplier: number;
  priced_year: number | null;
  current_year: number;
  cumulative_pct_increase: number;
  reasoning: string;
  applied: boolean;
}

export interface CostBreakdown {
  material: string;
  quantity: number;
  quantity_unit: string;
  base_rate: number;
  rate_used: number;
  rate_unit: string;
  rate_provenance: string;
  inflation_adjustment: InflationAdjustment;
  cost_inr: number;
}

export interface CostEstimate {
  project_id: string;
  gfa_sqm: number;
  breakdown: CostBreakdown[];
  total_cost_inr: number;
  cost_per_sqm_inr: number;
  scope_note: string;
  disclaimer: string;
}

export interface BenchmarkResult {
  project_id: string;
  actual_carbon_per_sqm: number;
  baseline_carbon_per_sqm: number;
  pct_difference_from_baseline: number;
  comparison_label: string;
  floor_band_used: string;
  baseline_result: CalculationResult;
  disclaimer: string;
}

export interface GrihaCriterion21Estimate {
  project_id: string;
  baseline_gwp_kg: number;
  design_gwp_kg: number;
  pct_reduction: number;
  points_estimated: number;
  max_points: number;
  scope_note: string;
  disclaimer: string;
}

export interface CalculateResponse {
  project_id: string;
  carbon: CalculationResult;
  cost: CostEstimate;
  benchmark: BenchmarkResult;
  griha_criterion_21: GrihaCriterion21Estimate;
}

export interface SubstitutionResult {
  substitution_id: string;
  label: string;
  applicable: boolean;
  reason_not_applicable?: string | null;
  current_value?: string | null;
  suggested_value?: string | null;
  carbon_kg_before: number;
  carbon_kg_after: number;
  savings_kg: number;
  savings_pct: number;
  requires_engineering_review: boolean;
  [key: string]: unknown;
}

export interface SubstituteResponse {
  project_id: string;
  carbon_before: CalculationResult;
  suggestions: SubstitutionResult[];
  combined?: unknown;
  [key: string]: unknown;
}

export interface RefineResponse {
  project_id: string;
  [key: string]: unknown;
}

export interface CategoryTotal {
  category: string;
  gwp_kg_co2e: number;
  line_item_count: number;
  pct_of_total: number;
}

export interface CoverageExclusion {
  reason: string;
  line_item_count: number;
  value_excluded: number;
}

export interface Coverage {
  total_value: number;
  computed_value: number;
  coverage_pct: number;
  top5_total_value: number;
  top5_computed_value: number;
  top5_coverage_pct: number;
  excluded_by_reason: CoverageExclusion[];
}

export interface LineItemResult {
  row: number;
  enriched_description: string;
  uom: string | null;
  qty: number | null;
  category: string | null;
  cement_type?: string | null;
  grade?: string | null;
  gwp_kg_co2e: number | null;
  basis_note: string;
  rate?: number | null;
  amount?: number | null;
}

export interface BoqCarbonResult {
  source_file: string;
  sheet_name: string;
  n_lines_total: number;
  n_lines_classified: number;
  n_lines_computed: number;
  total_gwp_kg_co2e: number;
  total_gwp_tonnes_co2e: number;
  by_category: CategoryTotal[];
  floor_area_sqm: number | null;
  floor_area_basis: FloorAreaBasis | null;
  floor_area_basis_note: string | null;
  gwp_per_sqm: number | null;
  gwp_per_sqft: number | null;
  line_items: LineItemResult[];
  registered_as_reference: boolean | null;
  reference_slug: string | null;
  registration_note: string | null;
  coverage: Coverage | null;
  scope_note: string;
  factor_disclaimer: string;
}

export interface CombinedImpact {
  total_savings_kg_co2e: number;
  total_savings_pct_of_total_boq: number;
  requires_engineering_review: boolean;
  note: string | null;
}

export interface BoqSubstitutionResult {
  substitution_id: string;
  label: string;
  user_pct: number;
  max_recommended_pct: number;
  exceeds_recommended: boolean;
  requires_engineering_review: boolean;
  reasoning: string;
  structural_caveat: string;
  source: string;
  evidence_tier: string;
  requires_supplier_match: string | null;
  affected_line_item_count: number;
  original_gwp_kg_co2e: number;
  new_gwp_kg_co2e: number;
  savings_kg_co2e: number;
  savings_pct_of_affected_lines: number;
  savings_pct_of_total_boq: number;
}

export interface BoqSubstitutionResponse {
  base_result: BoqCarbonResult;
  substitutions: BoqSubstitutionResult[];
  combined_impact: CombinedImpact | null;
}

export interface SubstitutionCatalogEntry {
  substitution_id: string;
  label: string;
  category: string;
  max_recommended_pct: number;
  reasoning: string;
  structural_caveat: string;
  source: string;
  evidence_tier: string;
  [key: string]: unknown;
}

export interface WoCategoryTotal {
  category: string;
  gwp_kg_co2e: number;
  line_item_count: number;
  pct_of_total: number;
}

export interface WoLineItemResult {
  row?: number;
  description?: string;
  category?: string | null;
  gwp_kg_co2e?: number | null;
  [key: string]: unknown;
}

export interface WoCarbonResult {
  source_file: string;
  n_line_items_parsed: number;
  n_line_items_computed: number;
  total_gwp_kg_co2e: number;
  total_gwp_tonnes_co2e: number;
  by_category: WoCategoryTotal[];
  floor_area_sqm: number | null;
  floor_area_basis: FloorAreaBasis | null;
  gwp_per_sqm: number | null;
  gwp_per_sqft: number | null;
  total_wo_amount: number;
  computed_wo_amount: number;
  parse_checksum_ok: boolean | null;
  line_items: WoLineItemResult[];
  registered_as_reference: boolean | null;
  reference_slug: string | null;
  registration_note: string | null;
  coverage: Coverage | null;
}

export interface ProjectSummary {
  project_id: string;
  company_id: string;
  project_name: string | null;
  has_phase1_record: boolean;
  has_baseline: boolean;
  baseline_source_type: BaselineSourceType | null;
  baseline_is_estimated: boolean;
  n_bills: number;
  latest_bill_period: string | null;
  latest_billed_date: string | null;
}

export interface Phase3Baseline {
  project_id: string;
  company_id: string;
  source_type: BaselineSourceType;
  source_file: string;
  recorded_at: string;
  total_gwp_kg_co2e: number;
  total_value: number;
  floor_area_sqm: number | null;
  floor_area_basis: FloorAreaBasis | null;
  structural_system_type: string | null;
  num_floors: number | null;
  typology: string | null;
  coverage: Coverage | null;
  is_estimated: boolean;
  note: string;
}

export interface BillPeriod {
  project_id: string;
  company_id: string;
  period: string;
  billed_date: string;
  source_file: string;
  recorded_at: string;
  stated_percent_complete: number | null;
  total_gwp_kg_co2e_to_date: number;
  total_value_to_date: number;
  cost_per_kg_co2e_to_date: number | null;
  coverage: Coverage | null;
  n_lines_computed: number;
  n_lines_total: number;
}

export interface DashboardPoint {
  period: string;
  billed_date: string;
  total_gwp_kg_co2e_to_date: number;
  total_value_to_date: number;
  cost_per_kg_co2e_to_date: number | null;
  stated_percent_complete: number | null;
}

export interface DashboardResult {
  project_id: string;
  company_id: string;
  baseline: Phase3Baseline;
  points: DashboardPoint[];
  has_bills: boolean;
  latest_period: string | null;
  billed_to_date_gwp_kg_co2e: number | null;
  billed_to_date_value: number | null;
  cost_per_kg_co2e_to_date: number | null;
  percent_complete: number | null;
  percent_complete_source: string | null;
  projected_total_gwp_kg_co2e: number | null;
  projected_vs_baseline_pct: number | null;
  benchmark_available: boolean;
  typical_carbon_per_sqm: number | null;
  projected_carbon_per_sqm: number | null;
  pct_difference_from_typical: number | null;
  benchmark_floor_band_used: string | null;
  notes: string[];
}

export type ChatToolName =
  | "swap_cement_type"
  | "swap_concrete_grade"
  | "swap_steel_ratio"
  | "swap_steel_supplier"
  | "get_carbon_breakdown"
  | "get_totals"
  | "get_benchmark_comparison"
  | "get_project_end_estimate";

export interface ChatToolCall {
  tool: ChatToolName | null;
  params: Record<string, unknown>;
  parse_source: "llm" | "keyword_fallback";
  clarification: string | null;
}

export interface ChatAnswer {
  project_id: string;
  company_id: string;
  question: string;
  tool_call: ChatToolCall;
  applied: boolean;
  current_value: string | null;
  suggested_value: string | null;
  carbon_kg_before: number | null;
  carbon_kg_after: number | null;
  savings_kg: number | null;
  savings_pct: number | null;
  requires_engineering_review: boolean | null;
  data: Record<string, unknown> | null;
  answer_text: string;
  error: string | null;
}

export interface ChatToolCatalogEntry {
  kind: "swap" | "query";
  description: string;
  params: Record<string, string>;
  example_question: string;
}

export type ChatToolCatalog = Record<string, ChatToolCatalogEntry>;

export interface FactorHistoryEntry {
  category: string;
  valid_from: string;
  valid_to: string | null;
  changelog_note: string;
  value: Record<string, unknown>;
}

export interface OnboardingJob {
  job_id: string;
  company_id: string;
  status: string;
  [key: string]: unknown;
}
