// Response shapes of the ScanAssist API (backend/app/api/v1). Keep in sync with the backend.

export type Localized = Record<string, string>;
export type Urgency = "routine" | "soon" | "urgent";
export type Role = "clinician" | "staff" | "org_admin" | "internal_reviewer" | "internal_admin";
export type ConditionState = "off" | "shadow" | "reveal_after" | "visible";
export type Side = "right" | "left" | "both";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  profession: string | null;
  license_no: string | null;
  org_id: string;
  org_name: string | null;
}

export interface LoginResult {
  access_token?: string;
  user?: User;
  mfa_required?: boolean;
  mfa_token?: string;
  enrollment?: { secret: string; otpauth_uri: string };
}

export interface FormOption {
  value: string;
  label: Localized;
}

export interface FormField {
  id: string;
  type: "single" | "multi" | "number" | "text" | "boolean" | "visual_acuity";
  label: Localized;
  required: boolean;
  required_if: Expr | null;
  show_if: Expr | null;
  options: FormOption[];
  free_text: boolean;
}

export type Expr =
  | { all: Expr[] }
  | { any: Expr[] }
  | { not: Expr }
  | { fact: string; op: string; value?: unknown };

export interface CaptureView {
  id: string;
  label: Localized;
  required: boolean;
  overlay: string | null;
  flash: boolean;
  instructions: Localized;
}

export interface ManagementOption {
  id: string;
  text: Localized;
  professions: string[];
  referral: boolean;
}

export interface PackCondition {
  id: string;
  name: Localized;
  default_urgency: Urgency | null;
  emergency: boolean;
  always_refer: boolean;
  required_exam_fields_by_side: Partial<Record<"right" | "left", string[]>>;
}

export interface Pack {
  id: string;
  version: string;
  name: Localized;
  pediatric_age_threshold: number;
  conditions: PackCondition[];
  capture_protocol: {
    views: CaptureView[];
    retake_tips: Record<string, Localized>;
    lighting_views?: Record<string, string>;
    lighting_labels?: Record<string, Localized>;
  };
  exam_form: { version: number; fields: FormField[] };
  management: Record<string, ManagementOption[]>;
  content: Record<string, Record<string, string>>;
  report_types: string[];
  report_locales: string[];
}

export interface Patient {
  id: string;
  full_name: string;
  birth_date: string | null;
  age: number | null;
  sex: string | null;
  contact: string | null;
  clinic_ref: string | null;
  created_at: string;
  has_care_consent?: boolean;
  encounters?: { id: string; pack_id: string; status: string; created_at: string }[];
}

export interface QualityIssue {
  code: string;
  tip: Localized;
}

export interface Photo {
  id: string;
  view: string;
  quality: { ok: boolean; issues: QualityIssue[]; metrics: Record<string, number> };
  quality_override_reason: string | null;
  deleted: boolean;
  url: string | null;
}

export interface RedFlag {
  id: string;
  rule_id: string;
  severity: Urgency;
  message: Localized;
  referral: boolean;
  acknowledged: boolean;
}

export interface Suggestion {
  condition_id: string;
  name: Localized;
  likelihood: "high" | "moderate" | "low";
  probability: number;
  default_urgency: Urgency | null;
}

export interface AIBlock {
  available: boolean;
  suggestions: Suggestion[];
  label?: string;
  model_version?: string;
  compare_after_assessment?: boolean;
  revealed?: boolean;
}

export interface Diagnosis {
  condition_id: string;
  side: Side | null;
  note: string | null;
}

export interface Assessment {
  id: string;
  phase: "pre_reveal" | "post_reveal";
  diagnoses: Diagnosis[];
  urgency: Urgency;
  plan: { items: string[]; notes: string | null; refer: boolean };
  agreement: string;
  changed_after_reveal: boolean | null;
}

export interface Report {
  id: string;
  encounter_id: string;
  type: string;
  locale: string;
  status: "draft" | "signed";
  content: string;
  source: string;
  parent_report_id: string | null;
  signed_at: string | null;
  created_at: string;
  pdf_base64?: string;
}

export interface Encounter {
  id: string;
  pack_id: string;
  status: "draft" | "signed" | "expired";
  created_at: string;
  signed_at: string | null;
  photos_deleted: boolean;
  patient: Patient;
  photos: Photo[];
  exam: Record<string, unknown>;
  red_flags: RedFlag[];
  ai: AIBlock;
  assessment: Assessment | null;
  pre_reveal_assessment: Assessment | null;
  reports: Report[];
  required_views: string[];
  missing_fields: string[];
}

export interface Analysis {
  red_flags: RedFlag[];
  suggested_urgency: Urgency;
  ai: AIBlock;
  required_views: string[];
  missing_fields: string[];
}

export interface Compare {
  available: boolean;
  suggestions: Suggestion[];
  red_flags?: RedFlag[];
  label?: string;
  model_version?: string;
}

export interface SignOffResult {
  encounter_status: string;
  photos_deleted: boolean;
  referral_id: string | null;
  reports: Report[];
}

export interface Referral {
  id: string;
  encounter_id: string;
  patient: { id: string; full_name: string };
  urgency: Urgency;
  reasons: string[];
  status: "to_refer" | "referred" | "seen" | "closed";
  notes: string | null;
  created_at: string;
}

export interface EncounterListItem {
  id: string;
  pack_id: string;
  status: string;
  created_at: string;
  patient: { id: string; full_name: string };
}
