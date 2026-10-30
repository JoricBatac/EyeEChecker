import type {
  Analysis,
  Assessment,
  Compare,
  Encounter,
  EncounterListItem,
  LoginResult,
  Pack,
  Patient,
  Photo,
  RedFlag,
  Referral,
  Report,
  SignOffResult,
  Urgency,
  User,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.join("\n") : `HTTP ${status}`);
  }
}

export interface ClientOptions {
  baseUrl: string;
  getToken: () => string | null | Promise<string | null>;
  onUnauthorized?: () => void;
}

export interface AssessmentInput {
  diagnoses: { condition_id: string; side?: string | null; note?: string | null }[];
  urgency: Urgency;
  plan: { items: string[]; notes?: string | null; refer?: boolean };
}

export function createClient({ baseUrl, getToken, onUnauthorized }: ClientOptions) {
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const token = await getToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    let payload: BodyInit | undefined;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const res = await fetch(`${baseUrl}${path}`, { method, headers, body: payload });
    if (res.status === 401) onUnauthorized?.();
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try {
        detail = (await res.json()).detail;
      } catch {}
      throw new ApiError(res.status, detail);
    }
    return res.json() as Promise<T>;
  }

  const get = <T>(p: string) => request<T>("GET", p);
  const post = <T>(p: string, b?: unknown) => request<T>("POST", p, b);
  const put = <T>(p: string, b?: unknown) => request<T>("PUT", p, b);
  const patch = <T>(p: string, b?: unknown) => request<T>("PATCH", p, b);

  return {
    baseUrl,
    request,
    login: (email: string, password: string) => post<LoginResult>("/v1/auth/login", { email, password }),
    mfa: (mfa_token: string, code: string) => post<LoginResult>("/v1/auth/mfa", { mfa_token, code }),
    me: () => get<User>("/v1/auth/me"),
    packs: () => get<Pack[]>("/v1/packs"),

    searchPatients: (query = "") => get<Patient[]>(`/v1/patients?query=${encodeURIComponent(query)}`),
    patient: (id: string) => get<Patient>(`/v1/patients/${id}`),
    createPatient: (p: Partial<Patient> & { full_name: string; age_years?: number | null }) =>
      post<Patient>("/v1/patients", p),
    recordConsent: (patientId: string, version: string, granted: boolean) =>
      post<Patient>(`/v1/patients/${patientId}/consents`, { version, granted }),

    encounters: (status?: string) => get<EncounterListItem[]>(`/v1/encounters${status ? `?status=${status}` : ""}`),
    encounter: (id: string) => get<Encounter>(`/v1/encounters/${id}`),
    startEncounter: (patient_id: string, pack_id: string) => post<Encounter>("/v1/encounters", { patient_id, pack_id }),
    uploadPhoto: (encounterId: string, form: FormData) => post<Photo>(`/v1/encounters/${encounterId}/photos`, form),
    overrideQuality: (encounterId: string, photoId: string, reason: string) =>
      patch<Photo>(`/v1/encounters/${encounterId}/photos/${photoId}`, { quality_override_reason: reason }),
    deletePhoto: (encounterId: string, photoId: string) =>
      request<{ deleted: boolean }>("DELETE", `/v1/encounters/${encounterId}/photos/${photoId}`),
    saveExam: (encounterId: string, answers: Record<string, unknown>) =>
      put<{ answers: Record<string, unknown>; red_flags: RedFlag[]; missing_fields: string[]; required_views: string[] }>(
        `/v1/encounters/${encounterId}/exam`,
        { answers },
      ),
    analyze: (encounterId: string) => post<Analysis>(`/v1/encounters/${encounterId}/analyze`),
    acknowledge: (encounterId: string, alertId: string) =>
      post<RedFlag>(`/v1/encounters/${encounterId}/alerts/${alertId}/ack`),
    saveAssessment: (encounterId: string, body: AssessmentInput) =>
      put<{ assessment: Assessment; red_flags: RedFlag[]; compare_available: boolean; required_views: string[] }>(
        `/v1/encounters/${encounterId}/assessment`,
        body,
      ),
    compare: (encounterId: string) => get<Compare>(`/v1/encounters/${encounterId}/ai-compare`),
    feedback: (encounterId: string, rating: string) => post(`/v1/encounters/${encounterId}/feedback`, { rating }),
    draftReport: (encounterId: string, type: string, locale = "en") =>
      post<Report>(`/v1/encounters/${encounterId}/reports`, { type, locale }),
    signOff: (encounterId: string, report_ids: string[]) =>
      post<SignOffResult>(`/v1/encounters/${encounterId}/sign-off`, { report_ids }),

    report: (id: string) => get<Report>(`/v1/reports/${id}`),
    editReport: (id: string, content: string) => patch<Report>(`/v1/reports/${id}`, { content }),
    polishReport: (id: string) => post<Report & { polished: boolean }>(`/v1/reports/${id}/polish`),
    addendum: (id: string, content: string) => post<Report>(`/v1/reports/${id}/addenda`, { content }),
    signReport: (id: string) => post<SignOffResult>(`/v1/reports/${id}/sign`),
    reportPdfUrl: (id: string) => `${baseUrl}/v1/reports/${id}/pdf`,

    referrals: (status?: string) => get<Referral[]>(`/v1/referrals${status ? `?status=${status}` : ""}`),
    updateReferral: (id: string, body: { status?: string; notes?: string }) => patch<Referral>(`/v1/referrals/${id}`, body),

    internal: {
      reviewQueue: (packId = "eye") => get<Record<string, unknown>[]>(`/v1/internal/review-queue?pack_id=${packId}`),
      addReviewNote: (caseId: string, note: string, verdict?: string) =>
        post(`/v1/internal/review-queue/${caseId}/notes`, { note, verdict }),
      metrics: (packId = "eye") => get<Record<string, unknown>>(`/v1/internal/metrics?pack_id=${packId}`),
      packs: () => get<{ id: string; name: Record<string, string>; placeholder: boolean; conditions: { id: string; name: Record<string, string>; emergency: boolean }[]; model: { version: string } }[]>("/v1/internal/packs"),
      states: (packId: string, orgId?: string) =>
        get<{ states: Record<string, string>; model_version: string }>(
          `/v1/internal/packs/${packId}/states${orgId ? `?org_id=${orgId}` : ""}`,
        ),
      setState: (packId: string, conditionId: string, body: { state: string; org_id?: string | null; advisor_signoff?: string }) =>
        put(`/v1/internal/packs/${packId}/conditions/${conditionId}/state`, body),
      orgs: () => get<{ id: string; name: string; kind: string; packs: string[] }[]>("/v1/internal/orgs"),
      createOrg: (body: { name: string; kind: string; admin_email: string; admin_name: string; address?: string }) =>
        post<{ id: string; admin: { email: string; temporary_password: string } }>("/v1/internal/orgs", body),
      enablePack: (orgId: string, packId: string, enabled: boolean) =>
        put(`/v1/internal/orgs/${orgId}/packs/${packId}`, { enabled }),
    },
  };
}

export type ApiClient = ReturnType<typeof createClient>;
