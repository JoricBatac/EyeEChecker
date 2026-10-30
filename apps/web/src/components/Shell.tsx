"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { isInternal, useAuth } from "@/lib/auth";

const CLINIC_NAV = [
  ["/clinic", "Overview"],
  ["/clinic/patients", "Patients"],
  ["/clinic/encounters", "Encounters"],
  ["/clinic/referrals", "Referral queue"],
  ["/clinic/settings", "Settings"],
];

const INTERNAL_NAV = [
  ["/internal", "Model metrics"],
  ["/internal/review", "Disagreement review"],
  ["/internal/packs", "Condition states"],
  ["/internal/orgs", "Organizations"],
];

export function Shell({ area, children }: { area: "clinic" | "internal"; children: ReactNode }) {
  const { session, ready, logout } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const internal = isInternal(session?.user);
  const allowed = session && (area === "internal" ? internal : !internal);

  useEffect(() => {
    if (!ready) return;
    if (!session) router.replace("/login");
    else if (!allowed) router.replace(internal ? "/internal" : "/clinic");
  }, [ready, session, allowed, internal, router]);

  if (!allowed) return null;
  const nav = area === "internal" ? INTERNAL_NAV : CLINIC_NAV;
  return (
    <div className="shell">
      <nav className="nav">
        <div className="brand">ScanAssist</div>
        {nav.map(([href, label]) => (
          <Link key={href} href={href} className={path === href ? "active" : ""}>
            {label}
          </Link>
        ))}
        <div style={{ flex: 1 }} />
        <div className="muted" style={{ padding: "0 10px" }}>
          {session.user.full_name}
          <br />
          {session.user.org_name} · {session.user.role}
        </div>
        <button className="secondary" onClick={logout} style={{ margin: 10 }}>
          Log out
        </button>
      </nav>
      <main>{children}</main>
    </div>
  );
}

export function Urgency({ value }: { value: string | null | undefined }) {
  return <span className={`badge ${value ?? ""}`}>{value ?? "-"}</span>;
}
