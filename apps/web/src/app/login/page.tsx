"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api, isInternal, useAuth } from "@/lib/auth";
import { errorText } from "@/lib/useApi";

export default function Login() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [enroll, setEnroll] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = mfaToken ? await api.mfa(mfaToken, code.trim()) : await api.login(email.trim(), password);
      if (r.mfa_required) {
        setMfaToken(r.mfa_token ?? null);
        setEnroll(r.enrollment ?? null);
      } else if (r.access_token && r.user) {
        login({ token: r.access_token, user: r.user });
        router.replace(isInternal(r.user) ? "/internal" : "/clinic");
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login card">
      <h1>ScanAssist</h1>
      <form onSubmit={submit}>
        {mfaToken ? (
          <>
            {enroll ? (
              <p>
                Set up two-factor authentication: add this key to your authenticator app, then enter the code.
                <br />
                <code>{enroll.secret}</code>
              </p>
            ) : (
              <p>Enter the 6-digit code from your authenticator app.</p>
            )}
            <label>
              Code
              <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={6} autoFocus />
            </label>
          </>
        ) : (
          <>
            <label>
              Email
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
            </label>
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
          </>
        )}
        <button disabled={busy}>{mfaToken ? "Verify" : "Log in"}</button>
        {error ? <div className="error">{errorText(error)}</div> : null}
      </form>
    </div>
  );
}
