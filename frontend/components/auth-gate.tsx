"use client";

import { useEffect, useState } from "react";
import { fetchCurrentUser, getToken } from "../lib/auth";
import { GlobalLoader } from "./global-loader";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      const token = getToken();
      if (!token) {
        window.location.replace("/login");
        return;
      }
      const current = await fetchCurrentUser();
      if (cancelled) return;
      if (!current) {
        window.location.replace("/login");
        return;
      }
      setReady(true);
    }
    void check();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return <GlobalLoader active label="Loading InfraLens" />;
  }

  return <>{children}</>;
}
