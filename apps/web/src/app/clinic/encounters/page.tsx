"use client";

import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/auth";
import { errorText, useApi } from "@/lib/useApi";

export default function Encounters() {
  const [status, setStatus] = useState("");
  const { data, error } = useApi(() => api.encounters(status || undefined), [status]);
  return (
    <>
      <h1>Encounters</h1>
      <div className="card">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          <option value="draft">Draft</option>
          <option value="signed">Signed</option>
          <option value="expired">Expired</option>
        </select>
        {error ? <div className="error">{errorText(error)}</div> : null}
        <table style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>Date</th>
              <th>Patient</th>
              <th>Specialty</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((e) => (
              <tr key={e.id}>
                <td>
                  <Link href={`/clinic/encounters/${e.id}`}>{new Date(e.created_at).toLocaleString()}</Link>
                </td>
                <td>{e.patient.full_name}</td>
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
