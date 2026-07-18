"use client";

import Link from "next/link";
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
          <Link href="/" className={`nav-item${pathname === "/" ? " active" : ""}`}>Chat</Link>
          <Link href="/dashboard" className={`nav-item${pathname.startsWith("/dashboard") ? " active" : ""}`}>Dashboard</Link>
          <Link href="/wiki" className={`nav-item${pathname.startsWith("/wiki") ? " active" : ""}`}>Wiki</Link>
          <Link href="/settings" className={`nav-item${pathname.startsWith("/settings") ? " active" : ""}`}>Settings</Link>
        </nav>
      </header>
      {children}
    </div>
  );
}
