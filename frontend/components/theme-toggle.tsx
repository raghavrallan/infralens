"use client";

import { useTheme } from "./theme-provider";

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M21 14.3A8.4 8.4 0 0 1 9.7 3 7.2 7.2 0 1 0 21 14.3Z"
      />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="4.2" />
      <path strokeLinecap="round" d="M12 3.2v1.6M12 19.2v1.6M4.8 12H3.2M20.8 12h-1.6M6.3 6.3l-1.1-1.1M18.8 18.8l-1.1-1.1M17.7 6.3l1.1-1.1M6.3 17.7l-1.1 1.1" />
    </svg>
  );
}

export function ThemeToggle({
  variant = "nav",
}: {
  variant?: "nav" | "floating" | "header";
}) {
  const { toggleTheme } = useTheme();

  return (
    <button
      type="button"
      className={`theme-toggle theme-toggle-${variant}`}
      onClick={toggleTheme}
      aria-label="Toggle dark mode"
      title="Toggle dark mode"
    >
      <span className="theme-toggle-icon theme-toggle-moon">
        <MoonIcon />
      </span>
      <span className="theme-toggle-icon theme-toggle-sun">
        <SunIcon />
      </span>
    </button>
  );
}
