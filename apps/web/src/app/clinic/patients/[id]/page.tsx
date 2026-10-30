"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { api } from "@/lib/auth";
import { errorText, useApi } from "@/lib/useApi";

export default function PatientDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: p, error } = useApi(() => api.patient(id), [id]);
  if (error) return <div className="error">{errorText(error)}</div>;
  if (!p) return null;
  return (
    <>
      <h1>{p.full_name}</h1>
      <div className="card">
        <div className="row">
          <span>Age {p.age ?? "-"}</span>·<span>{p.sex ?? "-"}</span>·<span>Clinic ID {p.clinic_ref ?? "-"}</span>·
          <span>Contact {p.contact ?? "-"}</span>
        </div>
        <p className="muted">Care consent: {p.has_care_consent ? "recorded" : "missing"}</p>
      </div>
      <div className="card">
        <h2>Encounters</h2>
        <table>
          <tbody>
            {(p.encounters ?? []).map((e) => (
              <tr key={e.id}>
                <td>
                  <Link href={`/clinic/encounters/${e.id}`}>{new Date(e.created_at).toLocaleString()}</Link>
                </td>
                <td>{e.pack_id}</td>
                <td className="muted">{e.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
