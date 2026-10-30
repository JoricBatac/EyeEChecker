"use client";

import { useState, type FormEvent } from "react";

import { api, useAuth } from "@/lib/auth";
import { errorText, useApi } from "@/lib/useApi";

type OrgUser = { id: string; email: string; full_name: string; role: string; profession: string | null; is_active: boolean };
type Org = { name: string; address: string | null; settings: { llm_polish?: boolean } };

export default function Settings() {
  const { session } = useAuth();
  const isAdmin = session?.user.role === "org_admin";
  const org = useApi(() => api.request<Org>("GET", "/v1/org"));
  const users = useApi(() => (isAdmin ? api.request<OrgUser[]>("GET", "/v1/org/users") : Promise.resolve([])), [isAdmin]);
  const [form, setForm] = useState({ email: "", full_name: "", role: "clinician", profession: "physician", license_no: "" });
  const [created, setCreated] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    }
  }

  async function invite(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      const body = { ...form, profession: form.role === "clinician" || form.role === "staff" ? form.profession : null };
      const r = await api.request<{ email: string; temporary_password: string }>("POST", "/v1/org/users", body);
      setCreated(`${r.email}: temporary password ${r.temporary_password} (shown once)`);
      users.reload();
    });
  }

  return (
    <>
      <h1>Settings</h1>
      {error ? <div className="error card">{errorText(error)}</div> : null}
      <div className="card">
        <h2>{org.data?.name}</h2>
        <p className="muted">{org.data?.address}</p>
        {isAdmin && (
          <label style={{ flexDirection: "row", alignItems: "center" }}>
            <input
              type="checkbox"
              checked={!!org.data?.settings.llm_polish}
              onChange={(e) =>
                run(async () => {
                  await api.request("PUT", "/v1/org/settings", { llm_polish: e.target.checked });
                  org.reload();
                })
              }
            />
            Polish report wording with AI (no photos or patient identifiers are sent)
          </label>
        )}
      </div>
      {isAdmin && (
        <div className="card">
          <h2>Users</h2>
          <table>
            <tbody>
              {(users.data ?? []).map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td>
                  <td>{u.email}</td>
                  <td>{u.role}</td>
                  <td>{u.profession ?? "-"}</td>
                  <td>
                    <button
                      className="secondary"
                      disabled={u.id === session?.user.id}
                      onClick={() =>
                        run(async () => {
                          await api.request("PATCH", `/v1/org/users/${u.id}`, { is_active: !u.is_active });
                          users.reload();
                        })
                      }>
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2 style={{ marginTop: 18 }}>Invite user</h2>
          <form onSubmit={invite} className="row" style={{ alignItems: "flex-end" }}>
            <label>
              Name
              <input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            </label>
            <label>
              Email
              <input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </label>
            <label>
              Role
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="clinician">Clinician</option>
                <option value="staff">Staff</option>
                <option value="org_admin">Clinic admin</option>
              </select>
            </label>
            <label>
              Profession
              <select value={form.profession} onChange={(e) => setForm({ ...form, profession: e.target.value })}>
                <option value="physician">Physician</option>
                <option value="optometrist">Optometrist</option>
                <option value="ophthalmologist">Ophthalmologist</option>
                <option value="nurse">Nurse</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label>
              License no.
              <input value={form.license_no} onChange={(e) => setForm({ ...form, license_no: e.target.value })} />
            </label>
            <button>Invite</button>
          </form>
          {created && <p className="badge ok">{created}</p>}
        </div>
      )}
    </>
  );
}
