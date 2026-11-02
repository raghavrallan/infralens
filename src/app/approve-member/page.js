"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { SUITE_DOWN, suiteJson, suiteToken } from "@/lib/suite";

export default function ApproveMemberPage() {
  const [message, setMessage] = useState("Processing the membership request…");

  useEffect(() => {
    document.title = "Approve member · Infralens";
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") || "";
    const id = params.get("id") || "";
    if (!token || !id) {
      const timer = window.setTimeout(() => setMessage("Missing approval token or request id."), 0);
      return () => window.clearTimeout(timer);
    }
    let cancel = false;
    const authed = Boolean(suiteToken());
    const request = authed
      ? suiteJson(`/api/member-requests/${id}/decide`, { method: "POST", body: { decision: "approved", token } })
      : suiteJson(`/api/member-requests/decide-email?request_id=${encodeURIComponent(id)}`, {
          method: "POST",
          body: { decision: "approved", token },
        });
    request
      .then(() => {
        if (!cancel) setMessage("Membership request approved.");
      })
      .catch((error) => {
        if (!cancel) setMessage(error.status === 503 ? SUITE_DOWN : error.message);
      });
    return () => {
      cancel = true;
    };
  }, []);

  return (
    <main className="grid min-h-screen place-items-center bg-canvas px-4">
      <div className="w-full max-w-md rounded-3xl border border-line bg-white p-6">
        <div className="text-sm font-bold text-brand">Infralens</div>
        <h1 className="mt-2 text-2xl font-semibold">Membership approval</h1>
        <p className="mt-3 text-sm text-ink">{message}</p>
        <p className="mt-4 text-sm">
          <Link href="/login" className="font-semibold text-brand">Workspace sign-in</Link>
        </p>
      </div>
    </main>
  );
}
