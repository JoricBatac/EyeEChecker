"use client";

import Link from "next/link";
import { useState } from "react";

import { Urgency } from "@/components/Shell";
import { api } from "@/lib/auth";
import { errorText, useApi } from "@/lib/useApi";

const STATUSES = ["to_refer", "referred", "seen", "closed"] as const;

export default function Referrals() {
  const [filter, setFilter] = useState("");
  const { data, error, reload } = useApi(() => api.referrals(filter || undefined), [filter]);
  const [saveError, setSaveError] = useState<unknown>(null);

  async function update(id: string, body: { status?: string; notes?: string }) {
    setSaveError(null);
    try {
      await api.updateReferral(id, body);
      reload();
    } catch (e) {
      setSaveError(e);
    }
  }

  return (
    <>
      <h1>Referral queue</h1>
      <div className="card">
        <div className="row">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
          <span className="muted">Sorted by urgency</span>
        </div>
        {error || saveError ? <div className="error">{errorText(error || saveError)}</div> : null}
        <table style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>Patient</th>
              <th>Urgency</th>
              <th>Reason</th>
              <th>Status</th>
              <th>Notes</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((r) => (
              <tr key={r.id}>
                <td>
                  <Link href={`/clinic/encounters/${r.encounter_id}`}>{r.patient.full_name}</Link>
                </td>
                <td>
                  <Urgency value={r.urgency} />
                </td>
                <td>{r.reasons.join("; ")}</td>
                <td>
                  <select value={r.status} onChange={(e) => update(r.id, { status: e.target.value })}>
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s.replace("_", " ")}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    defaultValue={r.notes ?? ""}
                    placeholder="e.g. referred to EVRMC"
                    onBlur={(e) => e.target.value !== (r.notes ?? "") && update(r.id, { notes: e.target.value })}
                  />
                </td>
                <td className="muted">{new Date(r.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data?.length && <p className="muted">No referrals.</p>}
      </div>
    </>
  );
}
