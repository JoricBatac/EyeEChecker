"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { isInternal, useAuth } from "@/lib/auth";

export default function Home() {
  const { session, ready } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (ready) router.replace(!session ? "/login" : isInternal(session.user) ? "/internal" : "/clinic");
  }, [ready, session, router]);
  return null;
}
