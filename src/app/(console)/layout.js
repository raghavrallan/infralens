import { Suspense } from "react";
import AppShell from "@/components/AppShell";
import { ConsoleProvider } from "@/context/ConsoleContext";

export default function ConsoleLayout({ children }) {
  return (
    <ConsoleProvider>
      <Suspense fallback={<div className="grid min-h-screen place-items-center text-sm text-muted">Opening the workspace…</div>}>
        <AppShell>{children}</AppShell>
      </Suspense>
    </ConsoleProvider>
  );
}
