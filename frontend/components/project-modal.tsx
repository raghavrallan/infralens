"use client";

import { useState } from "react";
import { Modal } from "./modal";

export function ProjectModal({ onClose, onCreate }: { onClose: () => void; onCreate: (name: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const close = () => { if (!saving) onClose(); };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setMessage("Enter a project name.");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      await onCreate(trimmed);
      onClose();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create project.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal eyebrow="Projects" title="Create a new project" description="Projects keep connections, repositories, chats, and findings isolated." onClose={close}>
      <form className="modal-body" onSubmit={(event) => void submit(event)}>
        <label className="modal-label">
          <span>Project name</span>
          <input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="Platform security" />
        </label>
        {message && <div className="form-msg error">{message}</div>}
        <div className="modal-actions">
          <button type="button" className="modal-btn ghost" onClick={close} disabled={saving}>Cancel</button>
          <button type="submit" className="modal-btn primary" disabled={saving}>{saving ? "Creating..." : "Create project"}</button>
        </div>
      </form>
    </Modal>
  );
}
