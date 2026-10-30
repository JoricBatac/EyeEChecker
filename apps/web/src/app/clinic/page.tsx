"use client";

import Link from "next/link";

import { Urgency } from "@/components/Shell";
import { api } from "@/lib/auth";
import { errorText, useApi } from "@/lib/useApi";

export default function Overview() {
  const encounters = useApi(() => api.encounters());
  const referrals = useApi(() => api.referrals());
  const weekAgo = Date.now() - 7 * 86400_000;
  const all = encounters.data ?? [];
  const open = (referrals.data ?? []).filter((r) => r.status === "to_refer" || r.status === "referred");

  return (
    <>
      <h1>Overview</h1>
      <div className="grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <b>{all.filter((e) => new Date(e.created_at).getTime() > weekAgo).length}</b>
          <span className="muted">Encounters this week</span>
        </div>
        <div className="card stat">
          <b>{all.filter((e) => e.status === "draft").length}</b>
          <span className="muted">Unsigned drafts</span>
        </div>
        <div className="card stat">
          <b>{open.length}</b>
          <span className="muted">Open referrals</span>
        </div>
        <div className="card stat">
          <b>{open.filter((r) => r.urgency === "urgent").length}</b>
          <span className="muted">Urgent referrals</span>
        </div>
      </div>
      <div className="card">
        <h2>Urgent and open referrals</h2>
        {referrals.error ? <div className="error">{errorText(referrals.error)}</div> : null}
        <table>
          <tbody>
            {open.slice(0, 10).map((r) => (
              <tr key={r.id}>
                <td>
                  <Link href={`/clinic/encounters/${r.encounter_id}`}>{r.patient.full_name}</Link>
                </td>
                <td>
                  <Urgency value={r.urgency} />
                </td>
                <td>{r.reasons.join("; ")}</td>
                <td className="muted">{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!open.length && <p className="muted">No open referrals.</p>}
      </div>
    </>
  );
}
