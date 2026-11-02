export const ADVISOR_MARK = "ADVISOR_GUIDE";

const CATEGORY_GUIDES = {
  Cost: {
    steps: [
      "Confirm the resource is unused before you resize it or shut it down.",
      "Compare the last 14 days of CPU, requests, or stored data with the SKU Advisor named.",
      "If it is idle, stop it or move it to a smaller SKU in a change window.",
      "Check for unattached disks and unused public IPs in the same resource group.",
    ],
  },
  Security: {
    steps: [
      "Open the resource network settings and see whether a public endpoint is required.",
      "Turn on HTTPS only, a firewall, or a private endpoint where Advisor named one.",
      "Leave role assignments unchanged. A tighter network rule does not need a new role.",
      "Re-check the recommendation after the portal shows the setting saved.",
    ],
  },
  HighAvailability: {
    steps: [
      "See whether the resource is pinned to one zone or one instance.",
      "Add a second zone, a backup, or a health probe before the next maintenance window.",
      "Do this on a non-production copy first when the resource serves traffic.",
    ],
  },
  Performance: {
    steps: [
      "Read the metric Advisor cited and confirm it stays high, not just for one spike.",
      "Scale the SKU or disk only if that metric is still above the limit.",
      "Keep the previous SKU noted so you can scale back down.",
    ],
  },
  OperationalExcellence: {
    steps: [
      "Turn on diagnostics for the resource Advisor named.",
      "Add one alert for the failure or the metric in the recommendation.",
      "Send the alert to the people who already own that resource group.",
    ],
  },
};

const MATCHES = [
  {
    test: /unused|idle|orphan|unattached|shutdown|deallocate/i,
    steps: [
      "Identify the exact resource and confirm nothing has called it recently.",
      "Stop or detach it only after that check. Deleting a disk is permanent.",
      "Review Advisor again after the resource is stopped or removed.",
    ],
  },
  {
    test: /reserved|reservation|savings plan/i,
    steps: [
      "Match the reservation term to how long this workload will stay.",
      "Buy the reservation in Cost Management. Do not change the resource SKU first.",
      "Confirm the reservation is applied to this subscription.",
    ],
  },
  {
    test: /https|tls|secure transfer|public access|firewall|private endpoint/i,
    steps: [
      "Find the public endpoint Advisor named.",
      "Require HTTPS and block anonymous or public network access if a private path exists.",
      "Save the setting, then refresh the recommendation.",
    ],
  },
  {
    test: /backup|zone|redundan|availability set/i,
    steps: [
      "Check the current zone and backup policy.",
      "Enable zone redundancy or a backup vault without failing over production yet.",
      "Run one restore test on a copy before you rely on it.",
    ],
  },
  {
    test: /diagnostic|alert|log/i,
    steps: [
      "Enable diagnostic settings to the existing Log Analytics workspace.",
      "Create one alert on the condition Advisor described.",
      "Leave the alert enabled and confirm a test signal arrives.",
    ],
  },
];

function subscriptionOf(row) {
  const match = String(row?.id || "").match(/\/subscriptions\/([0-9a-f-]{36})/i);
  return match ? match[1] : "";
}

function commandsFor(row) {
  const subscription = subscriptionOf(row);
  const lines = ["az advisor recommendation list -o table"];
  if (subscription && /^[0-9a-f-]{36}$/i.test(subscription)) {
    lines.unshift(`az advisor recommendation list --subscription ${subscription} -o table`);
  }
  return lines;
}

export function guideFor(row) {
  const category = String(row?.category || "Advisor");
  const text = `${row?.problem || ""} ${row?.solution || ""}`;
  const matched = MATCHES.find((item) => item.test.test(text));
  const fallback = CATEGORY_GUIDES[category] || {
    steps: [
      "Read the recommendation and open the resource it names.",
      "Apply the change Azure Advisor describes. Skip anything that deletes data or grants a role.",
      "Come back after the portal marks the recommendation resolved.",
    ],
  };
  return {
    source: "playbook",
    steps: matched?.steps || fallback.steps,
    commands: commandsFor(row),
    caution: "These commands only list Advisor recommendations. A change happens in chat, and only after you ask for it and approve it.",
  };
}

export function advisorPrompt(row, guide, projectName) {
  const steps = (guide?.steps || []).map((step, index) => `${index + 1}. ${step}`).join("\n");
  const commands = (guide?.commands || []).join("\n");
  return `${ADVISOR_MARK}
Project: ${projectName || "this project"}
Category: ${row?.category || "Advisor"}
Impact: ${row?.impact || "Unspecified"}
Recommendation: ${row?.problem || "Recommendation"}
Azure solution: ${row?.solution || "None supplied."}

Steps already prepared:
${steps}

Read-only CLI:
${commands || "az advisor recommendation list -o table"}

Guide me through this recommendation. Do not change Azure unless I explicitly ask you to apply one command. A write still needs my approval in chat.`;
}
