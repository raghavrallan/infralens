"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { getToken } from "../lib/auth";
import { ThemeToggle } from "./theme-toggle";

export function ApproveMemberPage() {
  const [message, setMessage] = useState("Processing…");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") || "";
    const id = params.get("id") || "";
    if (!token || !id) {
      setMessage("Missing approval token or request id.");
      return;
    }
    const authed = Boolean(getToken());
    void (async () => {
      try {
        if (authed) {
          await api(`/api/member-requests/${id}/decide`, {
            method: "POST",
            body: JSON.stringify({ decision: "approved", token }),
          });
        } else {
          await api(
            `/api/member-requests/decide-email?request_id=${encodeURIComponent(id)}`,
            {
              method: "POST",
              body: JSON.stringify({ decision: "approved", token }),
            },
          );
        }
        setMessage("Membership request approved.");
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Approval failed");
      }
    })();
  }, []);

  return (
    <div className="page login-page">
      <ThemeToggle variant="floating" />
      <main className="login-card">
        <h1>Membership approval</h1>
        <p>{message}</p>
        <a href="/organizations?tab=requests">Open Organizations</a>
      </main>
    </div>
  );
}
