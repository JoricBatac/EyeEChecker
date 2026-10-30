"use client";

import { t } from "@scanassist/shared";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Urgency } from "@/components/Shell";
import { api, downloadPdf } from "@/lib/auth";
import { errorText, useApi } from "@/lib/useApi";

export default function EncounterDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: e, error, reload } = useApi(() => api.encounter(id), [id]);
  const packs = useApi(() => api.packs());
  const [addendum, setAddendum] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<unknown>(null);
  if (error) return <div className="error">{errorText(error)}</div>;
  if (!e) return null;
  const pack = packs.data?.find((p) => p.id === e.pack_id);
  const conditionName = (cid: string) => t(pack?.conditions.find((c) => c.id === cid)?.name, "en") || cid;
  const fieldLabel = (fid: string) => t(pack?.exam_form.fields.find((f) => f.id === fid)?.label, "en") || fid;

  async function addAddendum(reportId: string) {
    setActionError(null);
    try {
      await api.addendum(reportId, addendum[reportId]);
      setAddendum({ ...addendum, [reportId]: "" });
      reload();
    } catch (err) {
      setActionError(err);
    }
  }

  return (
    <>
      <h1>
        {e.patient.full_name} <span className="badge">{e.status}</span>
      </h1>
      <p className="muted">
        {new Date(e.created_at).toLocaleString()} · {e.pack_id} · photos {e.photos_deleted ? "deleted after sign-off" : `${e.photos.length} (temporary)`}
      </p>

      {e.red_flags.length > 0 && (
        <div className="card">
          <h2>Red flags</h2>
          {e.red_flags.map((r) => (
            <p key={r.id}>
              <Urgency value={r.severity} /> {t(r.message, "en")} {r.acknowledged ? <span className="muted">(acknowledged)</span> : null}
            </p>
          ))}
        </div>
      )}

      {!e.photos_deleted && e.photos.length > 0 && (
        <div className="card">
          <h2>Photos</h2>
          <div className="row">
            {e.photos.map((p) =>
              p.url ? (
                // eslint-disable-next-line @next/next/no-img-element -- short-lived signed URLs, not optimizable
                <img key={p.id} src={p.url.startsWith("/") ? `${api.baseUrl}${p.url}` : p.url} alt={p.view} style={{ width: 220, borderRadius: 8 }} />
              ) : null,
            )}
          </div>
        </div>
      )}

      <div className="card">
        <h2>Exam</h2>
        <table>
          <tbody>
            {Object.entries(e.exam).map(([k, v]) => (
              <tr key={k}>
                <th>{fieldLabel(k)}</th>
                <td>{Array.isArray(v) ? v.join(", ") : String(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {e.assessment && (
        <div className="card">
          <h2>Assessment</h2>
          <p>
            {e.assessment.diagnoses.map((d) => `${conditionName(d.condition_id)}${d.side ? ` (${d.side})` : ""}`).join(", ")} ·{" "}
            <Urgency value={e.assessment.urgency} />
          </p>
          {e.assessment.changed_after_reveal ? <p className="muted">Revised after comparing with AI.</p> : null}
        </div>
      )}

      <div className="card">
        <h2>Reports</h2>
        {actionError ? <div className="error">{errorText(actionError)}</div> : null}
        {e.reports.map((r) => (
          <div key={r.id} style={{ marginBottom: 18 }}>
            <div className="row">
              <b>
                {r.type.replace("_", " ")} ({r.locale})
              </b>
              <span className={`badge ${r.status === "signed" ? "ok" : ""}`}>{r.status}</span>
              <button className="secondary" onClick={() => downloadPdf(r.id, `${r.type}-${r.id.slice(0, 8)}.pdf`)}>
                PDF
              </button>
            </div>
            <pre className="report">{r.content}</pre>
            {r.status === "signed" && r.type !== "addendum" && (
              <div className="row">
                <input
                  placeholder="Addendum (signed in the mobile app)"
                  value={addendum[r.id] ?? ""}
                  onChange={(ev) => setAddendum({ ...addendum, [r.id]: ev.target.value })}
                  style={{ flex: 1 }}
                />
                <button onClick={() => addAddendum(r.id)} disabled={!addendum[r.id]}>
                  Add addendum
                </button>
              </div>
            )}
          </div>
        ))}
        {!e.reports.length && <p className="muted">No reports yet.</p>}
      </div>
    </>
  );
}
