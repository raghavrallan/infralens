"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";

const FeedbackContext = createContext(null);

export function FeedbackProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const [busy, setBusy] = useState(null);
  const stack = useRef([]);

  const dismiss = useCallback((id) => {
    setToasts((items) => items.filter((item) => item.id !== id));
  }, []);

  const notify = useCallback((message, tone = "info") => {
    const text = String(message || "").trim();
    if (!text) return;
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((items) => [...items, { id, message: text, tone }]);
    window.setTimeout(() => dismiss(id), tone === "error" ? 9000 : 4200);
  }, [dismiss]);

  const startBusy = useCallback((label) => {
    stack.current = [...stack.current, label || "Working…"];
    setBusy(stack.current.at(-1));
  }, []);

  const stopBusy = useCallback(() => {
    stack.current = stack.current.slice(0, -1);
    setBusy(stack.current.at(-1) || null);
  }, []);

  return (
    <FeedbackContext.Provider value={{ notify, startBusy, stopBusy }}>
      {children}
      {busy && (
        <div className="fixed inset-0 z-[80] grid place-items-center bg-ink/45 px-4" role="status" aria-live="assertive">
          <div className="w-full max-w-sm rounded-2xl bg-white px-6 py-5 text-center shadow-[0_16px_40px_rgba(35,35,35,0.18)]">
            <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-orange-100 border-t-brand" />
            <p className="mt-4 text-sm font-semibold text-ink">{busy}</p>
            <p className="mt-1 text-xs text-muted">This can take a minute when Azure CLI is signing in.</p>
          </div>
        </div>
      )}
      <div className="pointer-events-none fixed right-4 top-4 z-[90] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.tone === "error" ? "alert" : "status"}
            className={`rise pointer-events-auto flex items-start justify-between gap-3 rounded-2xl px-4 py-3 text-sm text-white shadow-lg ${
              toast.tone === "error" ? "bg-red-600" : toast.tone === "ok" ? "bg-emerald-700" : "bg-ink"
            }`}
          >
            <span>{toast.message}</span>
            <button type="button" className="text-white/80" onClick={() => dismiss(toast.id)} aria-label="Dismiss">
              ×
            </button>
          </div>
        ))}
      </div>
    </FeedbackContext.Provider>
  );
}

export function useFeedback() {
  const ctx = useContext(FeedbackContext);
  if (!ctx) throw new Error("useFeedback must be used inside FeedbackProvider");
  return ctx;
}
