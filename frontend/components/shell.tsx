"use client";

/* Static export navigation must be handled by FastAPI's HTML fallback. */
/* eslint-disable @next/next/no-html-link-for-pages */
import { usePathname } from "next/navigation";
import { getStoredUser, logout } from "../lib/auth";
import { AuthGate } from "./auth-gate";
import { GlobalLoader } from "./global-loader";

export function Shell({ children, subtitle = "Skills Suite", scroll = false, loading = false }: {
  children: React.ReactNode;
  subtitle?: string;
  scroll?: boolean;
  loading?: boolean;
}) {
  const pathname = usePathname();
  const user = getStoredUser();

  return (
    <AuthGate>
      <div className={`page${scroll ? " scroll-page" : ""}`}>
        <GlobalLoader active={loading} />
        <header className="topbar">
          <div className="brand">
            <div className="brand-mark">IL</div>
            <div><h1>InfraLens</h1><p>{subtitle}</p></div>
          </div>
          <nav className="nav">
            <a href="/dashboard" className={`nav-item${pathname.startsWith("/dashboard") ? " active" : ""}`}>Dashboard</a>
            <a href="/" className={`nav-item${pathname === "/" ? " active" : ""}`}>Chat</a>
            <a href="/wiki" className={`nav-item${pathname.startsWith("/wiki") ? " active" : ""}`}>Wiki</a>
            <a href="/settings" className={`nav-item${pathname.startsWith("/settings") ? " active" : ""}`}>Settings</a>
            <div className="nav-user">
              <span className="nav-user-name">{user?.name || user?.username || "Admin"}</span>
              <button type="button" className="nav-logout" onClick={() => logout()}>Sign out</button>
            </div>
          </nav>
        </header>
        {children}
      </div>
    </AuthGate>
  );
}
