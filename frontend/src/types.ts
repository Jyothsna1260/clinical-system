// TypeScript mirrors of the backend Pydantic schemas
// (backend/app/schemas/clinical.py and backend/app/schemas/api.py).
// Datetimes and dates arrive as ISO strings.

export type ISODateTime = string;
export type ISODate = string;

// ------------------------------------------------------------------ errors

/** GET /api/health (public). */
export interface Health {
  status: string;
  storage: string;
  storage_backend: string;
  workflow_state: string;
  llm_provider: string;
  embeddings_enabled: boolean;
  clinical_nlp: string;
  web_search: string;
  max_upload_mb?: number;
  max_pdf_pages?: number;
  human_review_notice: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

/** Structured error stored on trials/runs: {code, message, details}. */
export interface StructuredError {
  code?: string;
  message?: string;
  details?: Record<string, unknown>;
  [key: string]: unknown;
}

// ------------------------------------------------------------------ protocol

export type Operator = "gt" | "gte" | "lt" | "lte" | "eq" | "between" | "present" | "absent" | "within_days";
export type Category = "inclusion" | "exclusion";
export type InclusionStatus = "SATISFIED" | "UNSATISFIED" | "UNKNOWN";
export type ExclusionStatus = "TRIGGERED" | "NOT_TRIGGERED" | "UNKNOWN";
export type CriterionStatus = InclusionStatus | ExclusionStatus;
export type ComparisonMethod = "deterministic" | "semantic_llm" | "not_evaluable";
export type OverallStatus = "ELIGIBLE" | "NOT_ELIGIBLE" | "MORE_INFORMATION_REQUIRED";

export interface NormalizedRule {
  attribute: string;
  operator: Operator;
  value?: number | string | string[] | null;
  value_max?: number | null;
  unit?: string | null;
  inclusive?: boolean | null;
}

export interface Criterion {
  criterion_id: string;
  trial_id: string;
  category: Category;
  original_text: string;
  normalized_rule?: NormalizedRule | null;
  /** Second clause of a compound criterion ("A or B", "x >= 30 and <= 90"). */
  secondary_rule?: NormalizedRule | null;
  rule_combinator?: "and" | "or" | null;
  required_attributes: string[];
  source_page: number;
  source_excerpt: string;
  extraction_confidence: number;
  requires_human_review: boolean;
  review_reasons: string[];
  extraction_method: "rule_based" | "llm";
}

// ------------------------------------------------------------------ patient

export type Sex = "male" | "female" | "other" | "unknown";

export interface Demographics {
  age?: number | null;
  sex?: Sex | null;
  date_of_birth?: ISODate | null;
}

export interface LabInput {
  name: string;
  value: number;
  unit?: string | null;
  observed_at?: ISODate | null;
  reference_range?: string | null;
}

export interface DiagnosisInput {
  name: string;
  code?: string | null;
  documented_at?: ISODate | null;
}

export interface MedicationInput {
  name: string;
  start_date?: ISODate | null;
  stop_date?: ISODate | null;
}

export interface HistoryInput {
  condition: string;
  present?: boolean | null;
}

export interface PatientProfileInput {
  demographics?: Demographics;
  labs?: LabInput[];
  diagnoses?: DiagnosisInput[];
  medications?: MedicationInput[];
  history?: HistoryInput[];
  as_of?: ISODate | null;
}

export type DataQualityFlagKind = "missing" | "stale" | "conflicting" | "ambiguous" | "unit_unconvertible";

export interface DataQualityFlag {
  attribute: string;
  flag: DataQualityFlagKind;
  detail: string;
}

// ------------------------------------------------------------------ results

export interface EvidenceReference {
  page: number;
  excerpt: string;
  chunk_id?: string | null;
  source: "protocol_citation" | "retrieval";
  score?: number | null;
}

export interface CriterionEvaluation {
  criterion_id: string;
  category: Category;
  status: CriterionStatus;
  original_text: string;
  patient_value?: string | null;
  expected_condition: string;
  comparison_method: ComparisonMethod;
  explanation: string;
  evidence_references: EvidenceReference[];
  uncertainty_notes: string[];
  requires_human_review: boolean;
  attribute?: string | null;
}

export interface PatientFinding {
  attribute: string;
  value: string;
  observed_at?: ISODate | null;
}

export interface SilentExclusionTrigger {
  trigger_id: string;
  domain: string;
  inclusion_criterion_ids: string[];
  exclusion_criterion_ids: string[];
  related_failing_criterion_ids: string[];
  patient_findings: PatientFinding[];
  explanation: string;
  evidence_references: EvidenceReference[];
  review_priority: "high" | "medium" | "low";
  confidence: number;
  unresolved_uncertainties: string[];
  requires_human_review: true;
}

export interface Conflict {
  conflict_type: "conflicting_rules" | "inconsistent_patient_values" | "ambiguous_rule";
  description: string;
  criterion_ids: string[];
  attributes: string[];
}

export interface MissingInformation {
  attribute: string;
  criterion_ids: string[];
  reason: string;
}

export interface DecisiveEvidence {
  criterion_id: string;
  status: string;
  patient_value: string | null;
  expected_condition: string;
  evidence_references: EvidenceReference[];
}

export interface PatientValueUsed {
  attribute: string;
  label: string;
  value: string;
  observed_at: string | null;
  status: string;
  source: string | null;
  criterion_ids: string[];
}

/** Web search context for an ambiguous criterion. Never used in the decision. */
export interface ExternalReference {
  criterion_id: string;
  query: string;
  title: string;
  url: string;
  snippet: string;
  provider: string;
}

/** Persistent memory: the previous assessment of the same patient for the same trial. */
export interface PriorAssessment {
  run_id: string;
  overall_status: OverallStatus | null;
  analyzed_at: ISODateTime | null;
  patient_profile_version: number;
  protocol_version: string;
  changed_criteria: string[];
}

export interface EligibilityResult {
  run_id: string;
  overall_status: OverallStatus;
  inclusion_results: CriterionEvaluation[];
  exclusion_results: CriterionEvaluation[];
  silent_exclusion_triggers: SilentExclusionTrigger[];
  missing_information: MissingInformation[];
  unresolved_conflicts: Conflict[];
  decisive_evidence: DecisiveEvidence[];
  final_explanation: string;
  human_review_required: true;
  human_review_notice: string;
  protocol_version: string;
  analyzed_at: ISODateTime;
  reviewer_notes: string[];
  // Optional: absent on results saved before these fields existed.
  patient_values_used?: PatientValueUsed[];
  external_references?: ExternalReference[];
  prior_assessment?: PriorAssessment | null;
}

// ------------------------------------------------------------------ API

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  created_at: ISODateTime;
}

export interface TokenOut {
  access_token: string;
  token_type: string;
  user: User;
}

export interface RegisterRequest {
  email: string;
  password: string;
  full_name?: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TrialSummary {
  id: string;
  title: string;
  status: string; // "processing" | "ready" | "error"
  index_status: string;
  current_version: number;
  protocol_version: string | null;
  page_count: number | null;
  criteria_count: number;
  created_at: ISODateTime;
}

export interface TrialDetail extends TrialSummary {
  filename: string | null;
  extraction_method: string | null;
  extraction_warnings: string[];
  criteria: Criterion[];
  error: StructuredError | null;
}

export interface PageOut {
  trial_id: string;
  page: number;
  page_count: number;
  text: string;
}

export interface PatientCreate {
  label: string;
  profile: PatientProfileInput;
}

export interface PatientUpdate {
  label?: string | null;
  profile: PatientProfileInput;
}

export interface PatientOut {
  id: string;
  profile_version_id: string;
  version: number;
  label: string;
  profile: PatientProfileInput;
  data_quality_flags: DataQualityFlag[];
  versions: number[];
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface PatientSummary {
  id: string;
  label: string;
  version: number;
  updated_at: ISODateTime;
}

export interface AnalyzeRequest {
  trial_id: string;
  patient_id: string;
}

export type RunState = "queued" | "running" | "completed" | "failed";

export interface RunCreated {
  run_id: string;
  status: string;
}

export type NodeStatus = "pending" | "running" | "completed" | "failed";

export interface NodeProgress {
  node: string;
  status: NodeStatus | (string & {});
  started_at?: ISODateTime | null;
  ended_at?: ISODateTime | null;
  summary?: Record<string, unknown> | null;
}

export interface RunStatus {
  run_id: string;
  status: RunState | (string & {});
  overall_status: OverallStatus | null;
  progress: NodeProgress[];
  error: StructuredError | null;
  created_at: ISODateTime;
  completed_at: ISODateTime | null;
}

export interface RunSummary {
  run_id: string;
  trial_id: string;
  trial_title: string;
  patient_id: string;
  patient_label: string;
  patient_profile_version: number;
  status: RunState | (string & {});
  overall_status: OverallStatus | null;
  created_at: ISODateTime;
}

export interface RunDetail {
  run_id: string;
  status: RunState | (string & {});
  trial_id: string;
  trial_title: string;
  patient_id: string;
  patient_label: string;
  patient_profile_version: number;
  protocol_version: string;
  /** EligibilityResult once the run is completed, otherwise null. */
  result: EligibilityResult | null;
  error: StructuredError | null;
  human_review_notice: string;
  created_at: ISODateTime;
  completed_at: ISODateTime | null;
}

export interface EvidenceRow {
  criterion_id: string;
  page: number;
  excerpt: string;
  chunk_id: string | null;
  source: string;
  score: number | null;
}

export interface RunEvidence {
  run_id: string;
  trial_id: string;
  protocol_version: string;
  evidence: EvidenceRow[];
  human_review_notice: string;
}

export interface AuditEvent {
  id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, unknown> | null;
  created_at: ISODateTime;
}

export interface AgentExecutionLog {
  node: string;
  status: string;
  started_at: ISODateTime | null;
  ended_at: ISODateTime | null;
  summary: Record<string, unknown> | null;
}

export interface RunAudit {
  run_id: string;
  audit_events: AuditEvent[];
  agent_execution_logs: AgentExecutionLog[];
}
