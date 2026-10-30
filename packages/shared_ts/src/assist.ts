// Client for the stateless mobile assist API (backend/app/api/v1/assist.py).
import { ApiError } from "./client";
import type { Localized, Pack, Side, Urgency } from "./types";

export interface AssistRedFlag {
  rule_id: string;
  subject: string;
  key: string;
  severity: Urgency;
  message: Localized;
  referral: boolean;
}

export interface PhotoQuality {
  ok: boolean;
  issues: { code: string; tip: Localized }[];
  metrics: Record<string, number>;
}

export interface AnalyzeResult {
  analysis_token: string;
  photos: (PhotoQuality & { view: string })[];
  red_flags: AssistRedFlag[];
  suggested_urgency: Urgency;
  required_views: string[];
  missing_fields: string[];
  ai_available: boolean;
}

export interface RankedCondition {
  condition_id: string;
  name: Localized;
  likelihood: "high" | "moderate" | "low";
  probability: number;
}

export interface RevealResult {
  label: string;
  model_version: string | null;
  suggestions: RankedCondition[];
  agreement: "agreed" | "partial" | "differs" | "not_shown";
  red_flags: AssistRedFlag[];
  required_views: string[];
}

export interface Pick {
  condition_id: string;
  side: Side | null;
}

export interface ReportRequest {
  analysis_token: string;
  report_type: "exam_note" | "referral_letter" | "patient_handout";
  locale: "en" | "fil";
  diagnoses: Pick[];
  urgency: Urgency;
  plan_items: string[];
  refer: boolean;
  acknowledged: string[];
  profession?: string | null;
  clinician_name: string;
  clinician_license?: string | null;
  clinic_name: string;
  clinic_address?: string | null;
}

export type Lighting = "normal" | "dim" | "flash";

export interface ExplainedResult {
  condition_id: string;
  name: Localized;
  probability: number;
  likelihood: "high" | "moderate" | "low";
  default_urgency: Urgency | null;
  emergency: boolean;
  visual_features: Localized | null;
  supports: Localized[];
  against: Localized[];
}

export interface QuickResult {
  analysis_token: string;
  label: string;
  model_version: string | null;
  results: ExplainedResult[];
  /** Lower-ranked conditions after the top 3 (shown folded). */
  others: ExplainedResult[];
  /** clear: one cause stands out · split: top causes are close · low: no clear match · unavailable: no model */
  confidence: "clear" | "split" | "low" | "unavailable";
  photos: (PhotoQuality & { view: string; lighting: Lighting })[];
  red_flags: AssistRedFlag[];
  suggested_urgency: Urgency;
  answered_questions: number;
  recommended_views: string[];
  /** Exam field ids (or "age") worth asking for this photo; answers refine the explanation only. */
  follow_up: string[];
}

export interface ReportResult {
  content: string;
  locale: string;
  urgency: Urgency;
  referral_reasons: string[];
  placeholders: string[];
}

export interface AssistClientOptions {
  baseUrl: string;
  getCode: () => string | null | Promise<string | null>;
}

export function createAssistClient({ baseUrl, getCode }: AssistClientOptions) {
  async function request<T>(method: string, path: string, body?: unknown, code?: string): Promise<T> {
    const headers: Record<string, string> = { "X-Clinic-Code": code ?? (await getCode()) ?? "" };
    let payload: BodyInit | undefined;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const res = await fetch(`${baseUrl}${path}`, { method, headers, body: payload });
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try {
        detail = (await res.json()).detail;
      } catch {}
      throw new ApiError(res.status, detail);
    }
    return res.json() as Promise<T>;
  }

  return {
    baseUrl,
    /** Also used to validate a newly entered access code. */
    config: (profession?: string | null, code?: string) =>
      request<{ clinic: string; pack: Pack }>(
        "GET",
        `/v1/assist/config${profession ? `?profession=${encodeURIComponent(profession)}` : ""}`,
        undefined,
        code,
      ),
    quality: (form: FormData) => request<PhotoQuality>("POST", "/v1/assist/quality", form),
    analyze: (form: FormData) => request<AnalyzeResult>("POST", "/v1/assist/analyze", form),
    reveal: (analysis_token: string, diagnoses: Pick[], urgency: Urgency) =>
      request<RevealResult>("POST", "/v1/assist/reveal", { analysis_token, diagnoses, urgency }),
    outcome: (analysis_token: string, final_diagnoses: string[], rating?: string | null) =>
      request<{ ok: boolean }>("POST", "/v1/assist/outcome", { analysis_token, final_diagnoses, rating }),
    report: (body: ReportRequest) => request<ReportResult>("POST", "/v1/assist/report", body),
    /** Simple flow: photo(s) with optional lighting tags -> explained AI ranking, immediately. */
    quick: (form: FormData) => request<QuickResult>("POST", "/v1/assist/quick", form),
    /** Re-explain with follow-up answers; reuses the sealed model output (no re-upload). */
    explain: (analysis_token: string, answers: Record<string, unknown>, age?: number | null) =>
      request<Omit<QuickResult, "photos" | "recommended_views">>("POST", "/v1/assist/explain", {
        analysis_token,
        answers,
        age: age ?? null,
      }),
    confirm: (analysis_token: string, diagnoses: Pick[], urgency: Urgency, rating?: string | null) =>
      request<{ red_flags: AssistRedFlag[]; recommended_views: string[] }>("POST", "/v1/assist/confirm", {
        analysis_token,
        diagnoses,
        urgency,
        rating,
      }),
  };
}

export type AssistClient = ReturnType<typeof createAssistClient>;
