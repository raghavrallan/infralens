"use client";

import { useId, useState } from "react";

export default function PasswordField({
  label,
  value,
  onChange,
  autoComplete = "current-password",
  minLength,
  required = false,
  className = "",
  inputClassName = "h-11 w-full rounded-2xl border border-line px-3 pr-11 text-sm font-normal outline-none focus:border-brand",
}) {
  const [visible, setVisible] = useState(false);
  const fieldId = useId();
  return (
    <div className={`text-xs font-semibold text-muted ${className}`}>
      <label htmlFor={fieldId}>{label}</label>
      <span className="relative mt-1 block">
        <input
          id={fieldId}
          type={visible ? "text" : "password"}
          autoComplete={autoComplete}
          minLength={minLength}
          required={required}
          value={value}
          onChange={onChange}
          className={inputClassName}
        />
        <button
          type="button"
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          onClick={() => setVisible((current) => !current)}
          className="absolute inset-y-0 right-0 grid w-11 place-items-center text-muted"
        >
          {visible ? <EyeOff /> : <Eye />}
        </button>
      </span>
    </div>
  );
}

function Eye() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
      <circle cx="12" cy="12" r="2.5" />
    </svg>
  );
}

function EyeOff() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M3 3l18 18" />
      <path d="M10.6 6.2A10.7 10.7 0 0 1 12 6c6.5 0 10 6 10 6a17.2 17.2 0 0 1-3.2 3.8" />
      <path d="M6.1 6.1C3.7 7.8 2 12 2 12s3.5 6 10 6c1.3 0 2.5-.2 3.6-.7" />
      <path d="M9.9 9.9a2.5 2.5 0 0 0 3.2 3.2" />
    </svg>
  );
}
