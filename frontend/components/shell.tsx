"use client";

/* Static export navigation must be handled by FastAPI's HTML fallback. */
/* eslint-disable @next/next/no-html-link-for-pages */
import { usePathname } from "next/navigation";

export function Shell({ children, subtitle = "Skills Suite", scroll = false }: {
  children: React.ReactNode;
  subtitle?: string;
  scroll?: boolean;
}) {
  const pathname = usePathname();
  return (
    <div className={`page${scroll ? " scroll-page" : ""}`}>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">DS</div>
          <div><h1>DevSecOps</h1><p>{subtitle}</p></div>
        </div>
        <nav className="nav">
          <a href="/dashboard" className={`nav-item${pathname.startsWith("/dashboard") ? " active" : ""}`}>Dashboard</a>
          <a href="/" className={`nav-item${pathname === "/" ? " active" : ""}`}>Chat</a>
          <a href="/wiki" className={`nav-item${pathname.startsWith("/wiki") ? " active" : ""}`}>Wiki</a>
          <a href="/settings" className={`nav-item${pathname.startsWith("/settings") ? " active" : ""}`}>Settings</a>
        </nav>
      </header>
      {children}
    </div>
  );
}
