"use client";

import { createClient, type User } from "@scanassist/shared";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const KEY = "scanassist.session";
const IDLE_MS = 30 * 60 * 1000;

type Session = { token: string; user: User };

// sessionStorage: the session ends when the tab closes. Never localStorage for patient-data access.
function readSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

let current: Session | null = null;

export const api = createClient({
  baseUrl: API_URL,
  getToken: () => current?.token ?? null,
  onUnauthorized: () => {
    sessionStorage.removeItem(KEY);
    window.location.href = "/login";
  },
});

type AuthValue = {
  session: Session | null;
  ready: boolean;
  login: (s: Session) => void;
  logout: () => void;
};

const AuthContext = createContext<AuthValue>({ session: null, ready: false, login: () => {}, logout: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    current = readSession();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sessionStorage is only readable after mount
    setSession(current);
    setReady(true);
  }, []);

  useEffect(() => {
    if (!session) return;
    let timer = setTimeout(logout, IDLE_MS);
    const reset = () => {
      clearTimeout(timer);
      timer = setTimeout(logout, IDLE_MS);
    };
    window.addEventListener("pointerdown", reset);
    window.addEventListener("keydown", reset);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("pointerdown", reset);
      window.removeEventListener("keydown", reset);
    };
  }, [session]);

  function login(s: Session) {
    current = s;
    sessionStorage.setItem(KEY, JSON.stringify(s));
    setSession(s);
  }

  function logout() {
    current = null;
    sessionStorage.removeItem(KEY);
    setSession(null);
    window.location.href = "/login";
  }

  const value = useMemo(() => ({ session, ready, login, logout }), [session, ready]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

export function isInternal(user: User | undefined | null) {
  return user?.role === "internal_admin" || user?.role === "internal_reviewer";
}

export async function downloadPdf(reportId: string, filename: string) {
  const res = await fetch(api.reportPdfUrl(reportId), { headers: { Authorization: `Bearer ${current?.token}` } });
  if (!res.ok) throw new Error(`PDF download failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
