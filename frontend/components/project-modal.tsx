"use client";

import { OnboardingWizard } from "./onboarding-wizard";

/** Project create entry — opens the onboarding wizard (existing vs new repo). */
export function ProjectModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
}) {
  return (
    <OnboardingWizard
      onClose={onClose}
      onFinished={async (projectId) => {
        try {
          await onCreate(projectId);
        } catch {
          // Caller may refresh from API even if name-shaped create fails.
        }
        onClose();
        window.location.href = `/dashboard?project_id=${encodeURIComponent(projectId)}`;
      }}
    />
  );
}
