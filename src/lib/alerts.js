const OPERATORS = {
  GreaterThan: "greater than",
  GreaterThanOrEqual: "at or above",
  LessThan: "less than",
  LessThanOrEqual: "at or below",
  Equals: "equal to",
  GreaterOrLessThan: "outside",
};

const SEVERITY = {
  0: "Critical",
  1: "Error",
  2: "Warning",
  3: "Informational",
  4: "Verbose",
};

function tidy(value) {
  const text = String(value ?? "").trim();
  if (!text || text.toLowerCase() === "null") return "";
  return text;
}

function parseJson(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") return value;
  const text = tidy(value);
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

function lastPart(id) {
  return String(id || "").split("/").filter(Boolean).pop() || "";
}

function resourceType(id) {
  const parts = String(id || "").split("/").filter(Boolean);
  const providers = parts.indexOf("providers");
  if (providers < 0) return "";
  const rest = parts.slice(providers + 1);
  if (rest.length < 2) return rest.join("/");
  const types = [`${rest[0]}/${rest[1]}`];
  for (let index = 3; index < rest.length; index += 2) types.push(rest[index]);
  return types.join("/");
}

export function durationLabel(value) {
  const match = tidy(value).match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/);
  if (!match) return tidy(value);
  const parts = [];
  if (match[1]) parts.push(`${match[1]} hour${match[1] === "1" ? "" : "s"}`);
  if (match[2]) parts.push(`${match[2]} minute${match[2] === "1" ? "" : "s"}`);
  if (match[3]) parts.push(`${match[3]} second${match[3] === "1" ? "" : "s"}`);
  return parts.join(" ");
}

export function severityLabel(value) {
  const key = tidy(value);
  if (!key) return "—";
  return SEVERITY[key] ? `Sev ${key} · ${SEVERITY[key]}` : `Sev ${key}`;
}

export function conditionText(condition) {
  if (!condition) return "";
  if (condition.kind === "Webtest") {
    const places = condition.threshold === "" || condition.threshold === undefined ? "one or more locations" : `${condition.threshold} or more locations`;
    return `Availability test fails in ${places}`;
  }
  const metric = condition.metric || "the metric";
  const aggregation = condition.aggregation ? `${condition.aggregation} of ` : "";
  const dynamic = /dynamic/i.test(condition.kind) || condition.sensitivity;
  const base = dynamic
    ? `${aggregation}${metric} is unusual (${condition.sensitivity || "dynamic"} sensitivity)`
    : `${aggregation}${metric} is ${OPERATORS[condition.operator] || "compared with"}${condition.threshold === "" || condition.threshold === undefined ? "" : ` ${condition.threshold}`}`;
  const dimensions = (condition.dimensions || [])
    .filter((item) => item.name)
    .map((item) => `${item.name} ${item.operator || "includes"} ${(item.values || []).join(", ")}`.trim());
  return [base.replace(/\s+/g, " ").trim(), dimensions.length ? `when ${dimensions.join("; ")}` : ""].filter(Boolean).join(" ");
}

export function presentAlert(row) {
  if (Array.isArray(row?.conditions)) return row;
  const criteria = parseJson(row.criteria);
  const actions = parseJson(row.actions);
  const parsedScopes = parseJson(row.scopes);
  const webtest = /WebtestLocationAvailabilityCriteria/i.test(criteria["odata.type"] || "");
  const conditions = webtest ? [{
    metric: "Availability test",
    namespace: "",
    operator: "",
    threshold: criteria.failedLocationCount ?? "",
    aggregation: "",
    sensitivity: "",
    kind: "Webtest",
    dimensions: [],
  }] : (criteria.allOf || criteria.anyOf || []).map((item) => ({
    metric: tidy(item.metricName || item.name),
    namespace: tidy(item.metricNamespace),
    operator: tidy(item.operator),
    threshold: item.threshold ?? "",
    aggregation: tidy(item.timeAggregation),
    sensitivity: tidy(item.alertSensitivity),
    kind: tidy(item.criterionType),
    dimensions: (item.dimensions || []).map((dim) => ({
      name: tidy(dim.name),
      operator: tidy(dim.operator),
      values: Array.isArray(dim.values) ? dim.values.map((value) => String(value)) : [],
    })),
  }));
  const enabled = row.enabledFlag ?? row.enabled;
  return {
    id: row.id || row.name || "",
    name: row.name || "",
    group: row.resourceGroup || row.group || "",
    location: tidy(row.location),
    state: enabled === false || enabled === "false" ? "Disabled" : "Enabled",
    severity: tidy(row.severityText ?? row.severity),
    description: tidy(row.description),
    frequency: durationLabel(row.frequency),
    window: durationLabel(row.window),
    targetType: tidy(row.targetType),
    targetRegion: tidy(row.targetRegion),
    autoMitigate: row.autoMitigate === "true" ? "Yes" : row.autoMitigate === "false" ? "No" : "",
    scopes: (Array.isArray(parsedScopes) ? parsedScopes : []).map((id) => ({
      name: lastPart(id),
      type: resourceType(id),
    })).filter((item) => item.name),
    conditions,
    actionGroups: (actions.actionGroups || []).map((item) => lastPart(item.actionGroupId)).filter(Boolean),
    signal: conditionText(conditions[0]),
  };
}
