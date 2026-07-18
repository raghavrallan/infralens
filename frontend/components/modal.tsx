"use client";

import { useEffect, useState } from "react";

export function Modal({ title, eyebrow, description, children, onClose, wide = false }: {
  title: string;
  eyebrow?: string;
  description?: string;
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);
  return (
    <div className="modal-overlay open" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className={`modal${wide ? " modal-wide" : ""}`} role="dialog" aria-modal="true">
        <div className="modal-accent" />
        <div className="modal-head">
          {eyebrow && <span className="modal-eyebrow">{eyebrow}</span>}
          <h3 className="modal-title">{title}</h3>
          {description && <p className="modal-desc">{description}</p>}
        </div>
        {children}
      </div>
    </div>
  );
}

export function useToast() {
  const [toast, setToast] = useState<{ message: string; kind?: string } | null>(null);
  const showToast = (message: string, kind?: string) => {
    setToast({ message, kind });
    window.setTimeout(() => setToast(null), 3200);
  };
  const Toast = toast ? <div className={`toast show ${toast.kind || ""}`}>{toast.message}</div> : null;
  return { showToast, Toast };
}
