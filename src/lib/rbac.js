export const ORG_ROLES = ["org_owner", "org_admin", "member"];

export const MODULES = [
  ["module.dashboard", "Dashboard", "Estate"],
  ["module.compute", "Compute", "Estate"],
  ["module.data", "Data", "Estate"],
  ["module.network", "Network", "Estate"],
  ["module.platform", "Platform", "Estate"],
  ["module.costs", "Costs and billing", "Estate"],
  ["module.alerts", "Alerts", "Estate"],
  ["module.advisor", "Advisor", "Estate"],
  ["module.sandbox", "Sandbox", "Estate"],
  ["module.chat", "Chat", "Agentic"],
  ["module.wiki", "Wiki", "Agentic"],
  ["module.findings", "Findings", "Agentic"],
  ["module.workflows", "Workflows", "Agentic"],
  ["module.approvals", "Approvals", "Agentic"],
  ["module.architecture", "Architecture", "Agentic"],
  ["module.engineering", "Engineering", "Agentic"],
  ["module.break-glass", "Break-glass", "Agentic"],
];

const ALL_MODULES = MODULES.map(([key]) => key);
const SERVICE_MODULES = ["module.compute", "module.data", "module.network", "module.platform"];
const SKILL_MODULES = ["module.chat", "module.wiki", "module.findings", "module.workflows", "module.architecture", "module.engineering"];

const LEGACY_GRANTS = {
  "project.read": ["module.dashboard", "module.sandbox"],
  "resources.read": [...SERVICE_MODULES, "module.alerts", "module.advisor"],
  "billing.read": ["module.costs"],
  "suite.use": SKILL_MODULES,
  "suite.manage": ["module.approvals", "module.break-glass"],
};

export const LADDER = [
  {
    key: "auditor",
    label: "Auditor",
    rank: 10,
    power: "Read the modules on this role. Cannot invite people or change a project.",
    modules: ["module.dashboard", "module.costs", "module.advisor"],
  },
  {
    key: "developer",
    label: "Developer",
    rank: 20,
    power: "Work in project services and skills chat. Cannot open cost or manage people.",
    modules: ["module.dashboard", "module.compute", "module.data", "module.network", "module.platform", "module.chat", "module.wiki", "module.findings"],
  },
  {
    key: "finops_analyst",
    label: "FinOps analyst",
    rank: 30,
    power: "Own cost, invoices, and savings advice. Cannot change infrastructure or people.",
    modules: ["module.dashboard", "module.costs", "module.advisor"],
  },
  {
    key: "security_analyst",
    label: "Security analyst",
    rank: 40,
    power: "Review alerts, advisor, and findings. Cannot change billing or invite people.",
    modules: ["module.dashboard", "module.alerts", "module.advisor", "module.findings", "module.approvals"],
  },
  {
    key: "sre",
    label: "Site reliability engineer",
    rank: 50,
    power: "Operate services, alerts, and the sandbox. Cannot open cost or manage the organization.",
    modules: ["module.dashboard", ...SERVICE_MODULES, "module.alerts", "module.sandbox", "module.chat", "module.workflows"],
  },
  {
    key: "engineering_lead",
    label: "Engineering lead",
    rank: 60,
    power: "Run the project estate and skills, including approvals. Cannot create projects or map connections.",
    modules: ["module.dashboard", ...SERVICE_MODULES, "module.alerts", "module.advisor", "module.sandbox", ...SKILL_MODULES, "module.approvals"],
  },
  {
    key: "project_manager",
    label: "Project manager",
    rank: 70,
    power: "Open every project module, including cost. Cannot map Azure connections or manage the organization.",
    modules: ALL_MODULES,
  },
];

const LEGACY_MODULES = {
  viewer: ["module.dashboard", "module.sandbox", "module.costs", ...SERVICE_MODULES, "module.alerts", "module.advisor", ...SKILL_MODULES],
  billing_reader: ["module.dashboard", "module.sandbox", "module.costs", ...SERVICE_MODULES, "module.alerts", "module.advisor", ...SKILL_MODULES],
  operator: ["module.dashboard", "module.sandbox", ...SERVICE_MODULES, "module.alerts", "module.advisor", ...SKILL_MODULES],
  project_admin: ALL_MODULES,
};

const LEGACY_LABELS = {
  viewer: "Viewer",
  billing_reader: "Billing reader",
  operator: "Operator",
  project_admin: "Project admin",
};

export const PROJECT_ROLES = [...LADDER.map((role) => role.key), ...Object.keys(LEGACY_MODULES)];
export const ASSIGNABLE_ROLES = LADDER.map((role) => role.key);
export const PROJECT_RANKS = LADDER.map((role) => role.rank);

const ORG_ONLY = new Set(["connection.manage", "members.manage", "project.create"]);

export function suiteRoleFor(orgRole, projectRole) {
  const key = canonical(projectRole);
  if (orgRole === "org_owner" || orgRole === "org_admin") return "org_admin";
  if (key === "project_manager" || key === "engineering_lead" || projectRole === "project_admin" || projectRole === "devops_lead") return "devops_lead";
  if (key === "sre" || key === "security_analyst" || projectRole === "devops_engineer") return "devops_engineer";
  if (key === "developer") return "developer";
  return "viewer";
}

export function isOrgManager(role) {
  return role === "org_owner" || role === "org_admin";
}

export function levelOf(rank) {
  return Math.max(1, Math.round(Number(rank) / 10));
}

function canonical(role) {
  return LADDER.some((item) => item.key === role) ? role : role;
}

export function rankOf(role, customRoles = []) {
  if (role === "org_owner") return 100;
  if (role === "org_admin") return 80;
  const preset = LADDER.find((item) => item.key === role);
  if (preset) return preset.rank;
  if (LEGACY_MODULES[role]) return role === "project_admin" ? 60 : role === "operator" ? 50 : role === "billing_reader" ? 30 : 10;
  const custom = (customRoles || []).find((item) => item.id === role);
  const rank = Number(custom?.rank);
  return PROJECT_RANKS.includes(rank) ? rank : 10;
}

export function expandPermissions(values) {
  const out = new Set();
  for (const value of values || []) {
    const key = String(value || "");
    if (!key) continue;
    out.add(key);
    for (const extra of LEGACY_GRANTS[key] || []) out.add(extra);
  }
  return [...out];
}

export function permissionsFor(role) {
  const preset = LADDER.find((item) => item.key === role);
  if (preset) return [...preset.modules];
  return [...(LEGACY_MODULES[role] || [])];
}

function allows(keys, permission) {
  if (keys.has(permission)) return true;
  if (permission === "module.services") return SERVICE_MODULES.some((key) => keys.has(key));
  if (permission === "project.read") return [...keys].some((key) => key.startsWith("module."));
  if (permission === "billing.read") return keys.has("module.costs");
  if (permission === "resources.read") return [...SERVICE_MODULES, "module.alerts", "module.advisor"].some((key) => keys.has(key));
  if (permission === "suite.use") return [...SKILL_MODULES, "module.approvals", "module.break-glass"].some((key) => keys.has(key));
  if (permission === "suite.manage") return keys.has("module.approvals") || keys.has("module.break-glass");
  if (permission === "project.manage") return false;
  return false;
}

export function can(orgRole, projectRole, permission, customPermissions) {
  if (ORG_ONLY.has(permission)) return isOrgManager(orgRole);
  if (isOrgManager(orgRole)) return true;
  const source = Array.isArray(customPermissions) ? customPermissions : permissionsFor(projectRole);
  return allows(new Set(expandPermissions(source)), permission);
}

export function roleLabel(role) {
  const preset = LADDER.find((item) => item.key === role);
  if (preset) return preset.label;
  if (LEGACY_LABELS[role]) return LEGACY_LABELS[role];
  const labels = {
    org_owner: "Organization owner",
    org_admin: "Organization admin",
    member: "Member",
  };
  return labels[role] || role;
}

export function rolePower(role) {
  return LADDER.find((item) => item.key === role)?.power || "";
}
