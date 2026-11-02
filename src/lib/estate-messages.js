// User-facing estate copy lives here. Routes, the snapshot reader, and the console pull these codes.

export const ESTATE_MESSAGES = {
  "auth.required": { status: 401, message: "Sign in again." },
  "auth.forbidden": { status: 403, message: "Your role does not allow that." },
  "project.missing": { status: 400, message: "Create a project first." },
  "project.setupMember": { status: 200, message: "An organization admin has not added you to a project yet." },
  "project.setupAdmin": { status: 200, message: "Connect Azure, create a project, and attach the subscriptions that belong to it." },
  "sync.workerDown": { status: 200, message: "The background sync could not be queued. Open the schedule and try again once the worker is running." },
  "sync.preparing": { status: 200, message: "The first copy of this view is being prepared in the background. You can keep working." },
  "part.unknown": { status: 500, message: "That estate part is not available." },
  "part.failed": { status: 500, message: "That part could not be loaded." },
  "status.failed": { status: 500, message: "Project status could not be loaded." },
  "overview.failed": { status: 500, message: "Overview figures could not be loaded." },
  "resources.failed": { status: 500, message: "Resources could not be loaded." },
  "activity.failed": { status: 500, message: "Activity could not be loaded." },
  "alerts.failed": { status: 500, message: "Alerts could not be loaded." },
  "advisor.failed": { status: 500, message: "Advisor recommendations could not be loaded." },
  "schedule.failed": { status: 500, message: "The sync schedule could not be saved." },
  "storage.failed": { status: 500, message: "Saved copies could not be loaded." },
  "cache.failed": { status: 500, message: "The read cache could not be loaded." },
  "calls.failed": { status: 500, message: "Sandbox calls could not be loaded." },
  "network.failed": { status: 500, message: "The network request failed." },
  unknown: { status: 500, message: "Something went wrong." },
};

export const ESTATE_PARTS = ["overview", "resources", "activity", "alerts", "advisor"];

export function estateMessage(code) {
  return (ESTATE_MESSAGES[code] || ESTATE_MESSAGES.unknown).message;
}

export class EstateError extends Error {
  constructor(code) {
    const entry = ESTATE_MESSAGES[code] || ESTATE_MESSAGES.unknown;
    super(entry.message);
    this.code = ESTATE_MESSAGES[code] ? code : "unknown";
    this.status = entry.status || 500;
  }
}
