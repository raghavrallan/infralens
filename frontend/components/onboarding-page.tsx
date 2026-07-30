"use client";

import { AuthGate } from "./auth-gate";
import { OnboardingWizard } from "./onboarding-wizard";

function skipKey(userId?: string) {
  return userId ? `onboarding_skipped:${userId}` : "onboarding_skipped";
}

export function OnboardingPage() {
  return (
    <AuthGate>
      <div className="page onboarding-page">
        <div className="onboarding-page-frame">
          <header className="onboarding-brand">
            <div className="brand-mark">IL</div>
            <div>
              <h1>InfraLens</h1>
              <p>Set up your workspace</p>
            </div>
          </header>
          <OnboardingWizard
            force
            asPage
            onFinished={(projectId) => {
              try {
                const raw = window.localStorage.getItem("infralens_auth_user");
                const user = raw ? (JSON.parse(raw) as { id?: string }) : null;
                if (user?.id) {
                  window.localStorage.setItem(skipKey(user.id), "1");
                }
              } catch {
                // ignore
              }
              window.localStorage.setItem("projectId", projectId);
              window.location.href = `/dashboard?project_id=${encodeURIComponent(projectId)}`;
            }}
          />
        </div>
      </div>
    </AuthGate>
  );
}
