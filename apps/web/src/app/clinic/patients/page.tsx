"use client";

import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/auth";
import { errorText, useApi } from "@/lib/useApi";

export default function Patients() {
  const [query, setQuery] = useState("");
  const { data, error } = useApi(() => api.searchPatients(query), [query]);
  return (
    <>
      <h1>Patients</h1>
      <div className="card">
        <input placeholder="Search name or clinic ID" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: 320 }} />
        {error ? <div className="error">{errorText(error)}</div> : null}
        <table style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Age</th>
              <th>Sex</th>
              <th>Clinic ID</th>
              <th>Registered</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((p) => (
              <tr key={p.id}>
                <td>
                  <Link href={`/clinic/patients/${p.id}`}>{p.full_name}</Link>
                </td>
                <td>{p.age ?? "-"}</td>
                <td>{p.sex ?? "-"}</td>
                <td>{p.clinic_ref ?? "-"}</td>
                <td className="muted">{new Date(p.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
