import { existsSync, statSync } from "fs";
import path from "path";
import { inventoryFilter } from "../services.js";
import { assertSubscription, ensureLogin, listSubscriptions, profileDir, runAz } from "./cli.js";

const ARM = "https://management.azure.com";
const GRAPH = `${ARM}/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01`;

const INVENTORY = `Resources
| where ${inventoryFilter()}
| extend kindText = tostring(kind), skuName = coalesce(tostring(sku.name), tostring(properties.sku.name), ''), skuTier = coalesce(tostring(sku.tier), tostring(properties.sku.tier), ''), skuCapacity = tostring(sku.capacity)
| extend power = tostring(properties.extended.instanceView.powerState.displayStatus), vmSize = tostring(properties.hardwareProfile.vmSize)
| extend hns = tostring(properties.isHnsEnabled), enabledFlag = tostring(properties.enabled), severityText = tostring(properties.severity)
| extend osType = tostring(properties.storageProfile.osDisk.osType)
| extend imageName = strcat(tostring(properties.storageProfile.imageReference.offer), ' ', tostring(properties.storageProfile.imageReference.sku))
| extend zoneName = iff(isnull(zones), '', strcat_array(zones, ', '))
| extend provisioning = tostring(properties.provisioningState)
| extend siteState = tostring(properties.state)
| extend hostName = tostring(properties.defaultHostName)
| extend httpsFlag = tostring(properties.httpsOnly)
| extend availabilityState = tostring(properties.availabilityState)
| extend runtime = coalesce(tostring(properties.siteConfig.linuxFxVersion), tostring(properties.siteConfig.windowsFxVersion), tostring(properties.siteConfig.netFrameworkVersion), '')
| extend planName = extract('/serverfarms/([^/]+)$', 1, tostring(properties.serverFarmId))
| extend runningStatus = tostring(properties.runningStatus)
| extend minReplicas = tostring(properties.template.scale.minReplicas)
| extend maxReplicas = tostring(properties.template.scale.maxReplicas)
| extend ingressExternal = tostring(properties.configuration.ingress.external)
| extend fqdn = coalesce(tostring(properties.configuration.ingress.fqdn), tostring(properties.fqdn), '')
| extend revision = tostring(properties.latestRevisionName)
| extend environmentName = extract('/managedEnvironments/([^/]+)$', 1, tostring(properties.managedEnvironmentId))
| extend k8sVersion = tostring(properties.kubernetesVersion)
| extend powerCode = tostring(properties.powerState.code)
| extend networkPlugin = tostring(properties.networkProfile.networkPlugin)
| extend poolCount = tostring(array_length(properties.agentPoolProfiles))
| extend poolSize = ''
| extend poolNodes = ''
| extend orchestration = tostring(properties.orchestrationMode)
| extend upgradeMode = tostring(properties.upgradePolicy.mode)
| extend diskCount = tostring(array_length(properties.storageProfile.dataDisks))
| extend containerImage = extract('image":"([^"]+)', 1, tostring(properties.template.containers))
| extend revisionMode = tostring(properties.configuration.activeRevisionsMode)
| extend statusText = tostring(properties.status)
| extend versionText = coalesce(tostring(properties.version), tostring(properties.redisVersion), '')
| extend publicNet = coalesce(tostring(properties.publicNetworkAccess), tostring(properties.network.publicNetworkAccess), tostring(properties.allowBlobPublicAccess), '')
| extend dataEndpoint = coalesce(tostring(properties.fullyQualifiedDomainName), tostring(properties.hostName), tostring(properties.workspaceUrl), tostring(properties.documentEndpoint), tostring(properties.endpoint), tostring(properties.vaultUri), tostring(properties.gatewayUrl), tostring(properties.serviceBusEndpoint), '')
| extend tlsVersion = tostring(properties.minimumTlsVersion)
| extend httpsTraffic = tostring(properties.supportsHttpsTrafficOnly)
| extend accessTier = tostring(properties.accessTier)
| extend haMode = tostring(properties.highAvailability.mode)
| extend storageGb = tostring(properties.storage.storageSizeGB)
| extend backupDays = tostring(properties.backup.backupRetentionDays)
| extend consistencyLevel = tostring(properties.consistencyPolicy.defaultConsistencyLevel)
| extend backupKind = coalesce(tostring(properties.backupPolicy.type), tostring(properties.currentBackupStorageRedundancy), '')
| extend zoneRedundant = tostring(properties.zoneRedundant)
| extend skuFamily = tostring(sku.family)
| extend serverName = extract('/servers/([^/]+)/', 1, id)
| extend maxBytes = tostring(properties.maxSizeBytes)
| extend minCapacity = tostring(properties.minCapacity)
| extend edition = tostring(properties.currentServiceObjectiveName)
| extend iops = tostring(properties.storage.iops)
| extend netDefault = tostring(properties.networkAcls.defaultAction)
| extend ipRules = tostring(properties.networkAcls.ipRules)
| extend addressSpace = iff(isnull(properties.addressSpace.addressPrefixes), '', strcat_array(properties.addressSpace.addressPrefixes, ', '))
| extend subnetCount = tostring(array_length(properties.subnets))
| extend ddos = tostring(properties.enableDdosProtection)
| extend operational = tostring(properties.operationalState)
| extend frontendCount = tostring(array_length(properties.frontendIPConfigurations))
| extend backendCount = tostring(array_length(properties.backendAddressPools))
| extend ruleCount = tostring(array_length(properties.loadBalancingRules))
| extend probeCount = tostring(array_length(properties.probes))
| extend listenerCount = tostring(array_length(properties.httpListeners))
| extend threatIntel = tostring(properties.threatIntelMode)
| extend enabledState = tostring(properties.enabledState)
| extend policyName = extract('/([^/]+)$', 1, tostring(properties.firewallPolicy.id))
| extend wafEnabled = tostring(properties.webApplicationFirewallConfiguration.enabled)
| extend scaleMin = tostring(properties.autoscaleConfiguration.minCapacity)
| extend scaleMax = tostring(properties.autoscaleConfiguration.maxCapacity)
| extend softDelete = tostring(properties.enableSoftDelete)
| extend purgeProtection = tostring(properties.enablePurgeProtection)
| extend rbacAuth = tostring(properties.enableRbacAuthorization)
| extend vaultUri = tostring(properties.vaultUri)
| extend gatewayUrl = tostring(properties.gatewayUrl)
| extend vnetType = tostring(properties.virtualNetworkType)
| extend workflowState = tostring(properties.state)
| extend localAuth = tostring(properties.disableLocalAuth)
| extend kafka = tostring(properties.kafkaEnabled)
| extend autoInflate = tostring(properties.isAutoInflateEnabled)
| extend customDomain = tostring(properties.customSubDomainName)
| project id, name, type, location, resourceGroup, subscriptionId, kindText, skuName, skuTier, skuCapacity, power, vmSize, hns, enabledFlag, severityText, osType, imageName, zoneName, provisioning, siteState, hostName, httpsFlag, availabilityState, runtime, planName, runningStatus, minReplicas, maxReplicas, ingressExternal, fqdn, revision, environmentName, k8sVersion, powerCode, networkPlugin, poolCount, poolSize, poolNodes, orchestration, upgradeMode, diskCount, containerImage, revisionMode, statusText, versionText, publicNet, dataEndpoint, tlsVersion, httpsTraffic, accessTier, haMode, storageGb, backupDays, consistencyLevel, backupKind, zoneRedundant, skuFamily, serverName, maxBytes, minCapacity, edition, iops, netDefault, ipRules, addressSpace, subnetCount, ddos, operational, frontendCount, backendCount, ruleCount, probeCount, listenerCount, threatIntel, enabledState, policyName, wafEnabled, scaleMin, scaleMax, softDelete, purgeProtection, rbacAuth, vaultUri, gatewayUrl, vnetType, workflowState, localAuth, kafka, autoInflate, customDomain`;

const ALERTS = `Resources
| where type =~ 'microsoft.insights/metricalerts'
| extend enabledFlag = tostring(properties.enabled), severityText = tostring(properties.severity), description = tostring(properties.description)
| extend frequency = tostring(properties.evaluationFrequency), window = tostring(properties.windowSize), autoMitigate = tostring(properties.autoMitigate)
| extend targetType = tostring(properties.targetResourceType), targetRegion = tostring(properties.targetResourceRegion)
| extend scopes = tostring(properties.scopes), criteria = tostring(properties.criteria), actions = tostring(properties.actions)
| project id, name, type, location, resourceGroup, enabledFlag, severityText, description, frequency, window, autoMitigate, targetType, targetRegion, scopes, criteria, actions`;

const GROUPS = `ResourceContainers
| where type =~ 'microsoft.resources/subscriptions/resourcegroups'
| project name`;

const ADVISOR = `advisorresources
| where type =~ 'microsoft.advisor/recommendations'
| project id, properties
| limit 30`;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function openSandbox(connectionId, creds) {
  const profile = profileDir(connectionId);
  await ensureLogin(profile, creds);
  return profile;
}

export async function listSandboxSubscriptions(connectionId, creds) {
  const profile = await openSandbox(connectionId, creds);
  return listSubscriptions(profile);
}

export function describeSandbox(connectionId) {
  try {
    const profile = profileDir(connectionId);
    const tokenFile = path.join(profile, "accessTokens.json");
    const profileFile = path.join(profile, "azureProfile.json");
    const ready = existsSync(tokenFile) || existsSync(profileFile);
    const stamp = existsSync(tokenFile) ? statSync(tokenFile).mtimeMs : existsSync(profileFile) ? statSync(profileFile).mtimeMs : null;
    return { ready, lastLoginAt: stamp ? Math.round(stamp) : null };
  } catch {
    return { ready: false, lastLoginAt: null };
  }
}

async function sandboxRest(profile, { method = "get", url, body, retries = 2, timeoutMs = 90000 }) {
  const args = ["rest", "--method", method, "--url", url];
  if (body) args.push("--body", JSON.stringify(body));
  let last;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await runAz(profile, args, { timeoutMs });
    } catch (err) {
      last = err;
      if (!/too many requests|429|503/i.test(err.message) || attempt === retries) throw err;
      await sleep(Math.min(6000 * (attempt + 1), 20000));
    }
  }
  throw last;
}

async function graph(profile, subscriptionIds, query) {
  const rows = [];
  let skipToken = "";
  for (let page = 0; page < 4; page += 1) {
    const payload = await sandboxRest(profile, {
      method: "post",
      url: GRAPH,
      timeoutMs: 90000,
      body: {
        subscriptions: subscriptionIds,
        query,
        options: { resultFormat: "objectArray", top: 2000, ...(skipToken ? { skipToken } : {}) },
      },
    });
    rows.push(...(payload?.data || []));
    skipToken = payload?.$skipToken || "";
    if (!skipToken) break;
  }
  return rows;
}

export async function graphQuery(profile, subscriptionIds, query) {
  return graph(profile, subscriptionIds, query);
}

export function listAlerts(profile, subscriptions) {
  return graph(profile, subscriptions.map((row) => row.id), ALERTS);
}

export async function readSandbox(profile, subscriptions) {
  const ids = subscriptions.map((row) => row.id);
  const resources = await graph(profile, ids, INVENTORY);
  const groups = await graph(profile, ids, GROUPS).catch(() => []);
  const advisor = await graph(profile, ids, ADVISOR).catch(() => []);
  const alerts = await graph(profile, ids, ALERTS).catch(() => []);
  return { resources, groups, advisor, alerts };
}

function billingDay(date) {
  const iso = date.toISOString().slice(0, 10);
  const [year, month, day] = iso.split("-");
  return `${month}-${day}-${year}`;
}

function invoiceVersion(version) {
  if (!/^\d{4}-\d{2}-\d{2}(-preview)?$/.test(version)) throw new Error("That invoice is not available.");
  return version;
}

export function invoiceList(profile, subscriptionId, version = "2019-10-01-preview") {
  const id = assertSubscription(subscriptionId);
  const api = invoiceVersion(version);
  const end = billingDay(new Date());
  const start = billingDay(new Date(Date.UTC(new Date().getUTCFullYear() - 2, 0, 1)));
  const period = api.startsWith("2018") ? "" : `&periodStartDate=${start}&periodEndDate=${end}`;
  const url = `${ARM}/subscriptions/${id}/providers/Microsoft.Billing/invoices?api-version=${api}${period}`;
  return runAz(profile, ["rest", "--method", "get", "--url", url, "-o", "json"], { timeoutMs: 45000 });
}

const BILLING_PROFILE = /^\/providers\/Microsoft\.Billing\/billingAccounts\/[A-Za-z0-9._:-]+\/billingProfiles\/[A-Za-z0-9._:-]+$/;

export function billingProperty(profile, subscriptionId) {
  const id = assertSubscription(subscriptionId);
  const url = `${ARM}/subscriptions/${id}/providers/Microsoft.Billing/billingProperty/default?api-version=2024-04-01`;
  return runAz(profile, ["rest", "--method", "get", "--url", url, "-o", "json"], { timeoutMs: 45000 });
}

export function profileInvoices(profile, profileId) {
  if (!BILLING_PROFILE.test(profileId)) throw new Error("That billing profile is not available.");
  const url = `${ARM}${profileId}/invoices?api-version=2024-04-01`;
  return runAz(profile, ["rest", "--method", "get", "--url", url, "-o", "json"], { timeoutMs: 45000 });
}

export function saveInvoicePdf(profile, url, dest) {
  const folder = path.resolve(process.cwd(), "data", "invoices");
  const file = path.resolve(dest);
  if (!file.startsWith(`${folder}${path.sep}`) || !file.endsWith(".pdf")) throw new Error("That invoice is not available.");
  let parsed;
  try {
    parsed = new URL(String(url || ""));
  } catch {
    throw new Error("That invoice is not available.");
  }
  if (parsed.protocol !== "https:" || !/azure|microsoft|windows\.net/i.test(parsed.hostname)) throw new Error("That invoice is not available.");
  return runAz(profile, ["rest", "--method", "get", "--url", parsed.toString(), "--output-file", file], { timeoutMs: 60000 });
}

export function profileInvoice(profile, profileId, name) {
  if (!BILLING_PROFILE.test(profileId) || !/^[A-Za-z0-9._:-]{1,160}$/.test(name)) throw new Error("That invoice is not available.");
  const url = `${ARM}${profileId}/invoices/${encodeURIComponent(name)}?api-version=2024-04-01`;
  return runAz(profile, ["rest", "--method", "get", "--url", url, "-o", "json"], { timeoutMs: 45000 });
}

export function invoiceGet(profile, subscriptionId, name) {
  if (!/^[A-Za-z0-9._:-]{1,120}$/.test(name)) throw new Error("That invoice is not available.");
  const id = assertSubscription(subscriptionId);
  const versions = ["2019-10-01-preview", "2018-03-01-preview", "2020-05-01"];
  return (async () => {
    let last;
    for (const version of versions) {
      const url = `${ARM}/subscriptions/${id}/providers/Microsoft.Billing/invoices/${encodeURIComponent(name)}?api-version=${version}`;
      try {
        return await runAz(profile, ["rest", "--method", "get", "--url", url, "-o", "json"], { timeoutMs: 45000 });
      } catch (err) {
        last = err;
        if (/not authorized|AuthorizationFailed|Forbidden|403/i.test(err.message)) {
          throw new Error("Azure did not share this invoice. The PDF needs access on the billing account.");
        }
      }
    }
    throw last || new Error("Azure did not attach a PDF to this invoice.");
  })();
}

export function costSandbox(profile, subscriptionId, body) {
  const id = assertSubscription(subscriptionId);
  const url = `${ARM}/subscriptions/${id}/providers/Microsoft.CostManagement/query?api-version=2023-11-01`;
  return sandboxRest(profile, { method: "post", url, body, timeoutMs: 90000 });
}

export async function activitySandbox(profile, subscriptionId, provider) {
  const id = assertSubscription(subscriptionId);
  const since = new Date(Date.now() - 7 * 86400000).toISOString();
  const safeProvider = String(provider || "");
  if (safeProvider && !/^microsoft\.[a-z0-9]+$/i.test(safeProvider)) throw new Error("That activity provider is not available.");
  const providerFilter = safeProvider ? ` and resourceProvider eq '${safeProvider}'` : "";
  const filter = encodeURIComponent(`eventTimestamp ge '${since}'${providerFilter}`);
  const url = `${ARM}/subscriptions/${id}/providers/microsoft.insights/eventtypes/management/values?api-version=2015-04-01&$filter=${filter}`;
  const payload = await sandboxRest(profile, { method: "get", url, timeoutMs: 60000, retries: 1 });
  return (payload?.value || []).slice(0, safeProvider ? 25 : 40);
}

const METRIC_WINDOWS = {
  "15m": [15 * 60 * 1000, "PT1M"],
  "1h": [60 * 60 * 1000, "PT5M"],
  "6h": [6 * 60 * 60 * 1000, "PT15M"],
};

export async function metricSandbox(profile, resourceId, metric, aggregation, windowId = "1h") {
  if (!/^\/subscriptions\/[0-9a-f-]{36}\//i.test(resourceId)) throw new Error("Metric target is not an Azure resource.");
  const [span, interval] = METRIC_WINDOWS[windowId] || METRIC_WINDOWS["1h"];
  const end = new Date();
  const start = new Date(end.getTime() - span);
  const timespan = `${start.toISOString()}/${end.toISOString()}`;
  const url = `${ARM}${resourceId}/providers/microsoft.insights/metrics?api-version=2018-01-01&metricnames=${encodeURIComponent(metric)}&timespan=${encodeURIComponent(timespan)}&interval=${interval}&aggregation=${aggregation}`;
  return sandboxRest(profile, { method: "get", url, timeoutMs: 45000, retries: 0 });
}

function assertAppName(name) {
  if (!/^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$/.test(name) || name.includes("--")) throw new Error("That container app name is not valid.");
  return name;
}

function assertGroup(name) {
  if (!/^[A-Za-z0-9._()-]{1,90}$/.test(name) || name.startsWith("-")) throw new Error("That resource group is not valid.");
  return name;
}

function assertSubscriptionId(value) {
  if (!/^[0-9a-f-]{36}$/i.test(value)) throw new Error("That resource has no subscription.");
  return value;
}

export async function blobContainers(profile, resourceId) {
  if (!/^\/subscriptions\/[0-9a-f-]{36}\//i.test(resourceId)) throw new Error("That storage account is not an Azure id.");
  const rows = [];
  let url = `${ARM}${resourceId}/blobServices/default/containers?api-version=2023-01-01`;
  for (let page = 0; page < 5; page += 1) {
    const payload = await runAz(profile, ["rest", "--method", "get", "--url", url, "-o", "json"], { timeoutMs: 45000 });
    rows.push(...(payload?.value || []));
    const next = payload?.nextLink || "";
    if (!next.startsWith("https://management.azure.com/")) break;
    url = next;
  }
  return rows;
}

export async function blobUsage(profile, resourceId) {
  if (!/^\/subscriptions\/[0-9a-f-]{36}\//i.test(resourceId)) throw new Error("That storage account is not an Azure id.");
  const end = new Date();
  const start = new Date(end.getTime() - 26 * 60 * 60 * 1000);
  const timespan = `${start.toISOString()}/${end.toISOString()}`;
  const url = `${ARM}${resourceId}/blobServices/default/providers/microsoft.insights/metrics?api-version=2018-01-01&metricnames=BlobCapacity,BlobCount&timespan=${encodeURIComponent(timespan)}&interval=PT1H&aggregation=Average`;
  const payload = await runAz(profile, ["rest", "--method", "get", "--url", url, "-o", "json"], { timeoutMs: 45000 });
  const series = payload?.value || [];
  function latest(name) {
    const metric = series.find((item) => item.name?.value === name);
    const points = metric?.timeseries?.[0]?.data || [];
    const point = [...points].reverse().find((item) => item.average != null);
    return point ? Number(point.average) : null;
  }
  return { bytes: latest("BlobCapacity"), count: latest("BlobCount") };
}

export function armGet(profile, resourceId, apiVersion) {
  if (!/^\/subscriptions\/[0-9a-f-]{36}\//i.test(resourceId)) throw new Error("That resource is not an Azure id.");
  if (!/^\d{4}-\d{2}-\d{2}(-preview)?$/.test(apiVersion)) throw new Error("That API version is not valid.");
  return runAz(profile, ["rest", "--method", "get", "--url", `${ARM}${resourceId}?api-version=${apiVersion}`, "-o", "json"], { timeoutMs: 45000 });
}

export function childResources(profile, resourceId, child, apiVersion) {
  if (!/^\/subscriptions\/[0-9a-f-]{36}\//i.test(resourceId)) throw new Error("That resource is not an Azure id.");
  if (!/^[A-Za-z]+$/.test(child)) throw new Error("That child list is not available.");
  if (!/^\d{4}-\d{2}-\d{2}(-preview)?$/.test(apiVersion)) throw new Error("That API version is not available.");
  return runAz(profile, ["rest", "--method", "get", "--url", `https://management.azure.com${resourceId}/${child}?api-version=${apiVersion}`, "-o", "json"], { timeoutMs: 45000 });
}

export function containerRevisions(profile, name, group, subscriptionId) {
  return runAz(profile, ["containerapp", "revision", "list", "--name", assertAppName(name), "--resource-group", assertGroup(group), "--subscription", assertSubscriptionId(subscriptionId), "--all", "-o", "json"], { timeoutMs: 60000 });
}

const workspaceCache = new Map();

async function workspaceForEnvironment(profile, subscriptionIds, environment) {
  if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,50}$/.test(environment)) throw new Error("This app has no Container Apps environment to read logs from.");
  const hit = workspaceCache.get(environment);
  if (hit && Date.now() - hit.at < 10 * 60 * 1000) return hit.id;
  const rows = await graph(profile, subscriptionIds, `Resources
| where type =~ 'microsoft.app/managedenvironments' and name =~ '${environment}'
| project customerId = tostring(properties.appLogsConfiguration.logAnalyticsConfiguration.customerId)
| take 1`);
  const id = rows?.[0]?.customerId || "";
  if (!/^[0-9a-f-]{36}$/i.test(id)) throw new Error("This environment is not sending logs to a Log Analytics workspace.");
  workspaceCache.set(environment, { id, at: Date.now() });
  return id;
}

export async function containerWorkspaceLogs(profile, subscriptionIds, environment, appName, kind) {
  const name = assertAppName(appName);
  const workspace = await workspaceForEnvironment(profile, subscriptionIds, environment);
  const table = kind === "system" ? "ContainerAppSystemLogs_CL" : "ContainerAppConsoleLogs_CL";
  const message = kind === "system" ? "Reason_s" : "Log_s";
  const revision = kind === "system" ? "ReplicaName_s" : "RevisionName_s";
  const query = `${table}
| where ContainerAppName_s == '${name}'
| project TimeGenerated, ${revision}, ${message}
| order by TimeGenerated desc
| take 40`;
  const payload = await runAz(profile, [
    "rest",
    "--method", "post",
    "--url", `https://api.loganalytics.io/v1/workspaces/${workspace}/query`,
    "--resource", "https://api.loganalytics.io",
    "--body", JSON.stringify({ query, timespan: "P2D" }),
    "-o", "json",
  ], { timeoutMs: 45000 });
  const tableRows = payload?.tables?.[0]?.rows || [];
  return tableRows.map((row) => {
    const time = row[0] ? String(row[0]).replace("T", " ").replace("Z", " UTC") : "";
    const rev = row[1] || "";
    const text = row[2] || "";
    return [time, rev, text].filter(Boolean).join("  ").slice(0, 400);
  });
}
