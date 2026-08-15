"""Live Azure connector.

Uses the Azure connection stored in Settings (tenant / client / secret /
subscription) to authenticate with the Microsoft identity platform and query
the subscription's real resources through Azure Resource Graph. The result is a
compact, security-focused environment report the skills can reason over — so a
question like "review my Azure infrastructure" analyses real data instead of
asking the user to paste files.

Everything here is READ-ONLY: it only issues Resource Graph queries and token
requests; it never creates, updates or deletes anything.
"""
import calendar
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.platform import connections

_AUTHORITY = "https://login.microsoftonline.com"
_ARM = "https://management.azure.com"
_SCOPE = "https://management.azure.com/.default"
_LOGS_SCOPE = "https://api.loganalytics.io/.default"
_LOGS_URL_TMPL = "https://api.loganalytics.io/v1/workspaces/{ws}/query"
_GRAPH_URL = f"{_ARM}/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01"
_COST_URL_TMPL = (
    _ARM + "/subscriptions/{sub}/providers/Microsoft.CostManagement/query"
    "?api-version=2023-11-01"
)
_TIMEOUT = 30.0

_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


class AzureConnectionError(RuntimeError):
    """Raised when Azure is not connected or credentials are incomplete."""


class AzureApiError(RuntimeError):
    """Raised when an Azure API call fails (auth, permissions, throttling…)."""


@dataclass
class AzureCredentials:
    tenant_id: str
    client_id: str
    client_secret: str
    subscription_id: Optional[str] = None


def load_credentials(project_id: str) -> AzureCredentials:
    fields = connections.get_secret_fields(project_id, "azure")
    if not fields:
        raise AzureConnectionError("No Azure connection is configured for this project.")
    tenant = fields.get("tenant_id") or ""
    client = fields.get("client_id") or ""
    secret = fields.get("client_secret") or ""
    missing = [
        name
        for name, value in (
            ("Tenant ID", tenant),
            ("Client ID", client),
            ("Client secret", secret),
        )
        if not value
    ]
    if missing:
        raise AzureConnectionError(
            "Azure connection is missing: " + ", ".join(missing) + "."
        )
    return AzureCredentials(
        tenant_id=tenant,
        client_id=client,
        client_secret=secret,
        subscription_id=fields.get("subscription_id") or None,
    )


def is_connected(project_id: str) -> bool:
    try:
        load_credentials(project_id)
        return True
    except AzureConnectionError:
        return False


def _get_token(creds: AzureCredentials, scope: str = _SCOPE) -> str:
    url = f"{_AUTHORITY}/{creds.tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scope": scope,
    }
    try:
        resp = httpx.post(url, data=data, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise AzureApiError(f"Could not reach Azure sign-in endpoint: {exc}") from exc
    if resp.status_code != 200:
        detail = _error_detail(resp)
        raise AzureApiError(f"Azure authentication failed ({resp.status_code}): {detail}")
    return resp.json().get("access_token", "")


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        return resp.text[:300]
    if isinstance(body, dict):
        if "error_description" in body:
            return str(body["error_description"]).splitlines()[0][:300]
        if "error" in body:
            err = body["error"]
            if isinstance(err, dict):
                details = err.get("details")
                if isinstance(details, list) and details:
                    inner = details[0]
                    if isinstance(inner, dict) and inner.get("message"):
                        return str(inner["message"])[:300]
                return str(err.get("message", err))[:300]
            return str(err)[:300]
    return json.dumps(body)[:300]


def _run_query(token: str, subscriptions: list[str], query: str) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"query": query, "options": {"resultFormat": "objectArray"}}
    if subscriptions:
        payload["subscriptions"] = subscriptions
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = httpx.post(_GRAPH_URL, headers=headers, json=payload, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise AzureApiError(f"Resource Graph request failed: {exc}") from exc
    if resp.status_code != 200:
        raise AzureApiError(
            f"Resource Graph query failed ({resp.status_code}): {_error_detail(resp)}"
        )
    return resp.json().get("data", []) or []


_INVENTORY_QUERY = (
    "Resources | project name, type, location, resourceGroup, kind, "
    "skuName=tostring(sku.name) | order by type asc | limit 500"
)
_COUNT_QUERY = (
    "Resources | summarize total=count() by type | order by total desc"
)

_PROBES: list[tuple[str, str]] = [
    (
        "Storage accounts (encryption in transit & public blob access)",
        "Resources | where type =~ 'microsoft.storage/storageAccounts' "
        "| project name, resourceGroup, "
        "httpsOnly=tostring(properties.supportsHttpsTrafficOnly), "
        "allowBlobPublicAccess=tostring(properties.allowBlobPublicAccess), "
        "minTls=tostring(properties.minimumTlsVersion) | limit 100",
    ),
    (
        "Inbound NSG rules open to the internet",
        "Resources | where type =~ 'microsoft.network/networkSecurityGroups' "
        "| mv-expand rule=properties.securityRules "
        "| where tostring(rule.properties.direction)=='Inbound' "
        "and tostring(rule.properties.access)=='Allow' "
        "and tostring(rule.properties.sourceAddressPrefix) in ('*','Internet','0.0.0.0/0') "
        "| project nsg=name, resourceGroup, ruleName=tostring(rule.name), "
        "port=tostring(rule.properties.destinationPortRange), "
        "protocol=tostring(rule.properties.protocol) | limit 100",
    ),
    (
        "Public IP addresses",
        "Resources | where type =~ 'microsoft.network/publicIPAddresses' "
        "| project name, resourceGroup, "
        "allocation=tostring(properties.publicIPAllocationMethod) | limit 100",
    ),
    (
        "Key vaults (soft delete & purge protection)",
        "Resources | where type =~ 'microsoft.keyvault/vaults' "
        "| project name, resourceGroup, "
        "softDelete=tostring(properties.enableSoftDelete), "
        "purgeProtection=tostring(properties.enablePurgeProtection) | limit 100",
    ),
    (
        "SQL servers (public network access)",
        "Resources | where type =~ 'microsoft.sql/servers' "
        "| project name, resourceGroup, "
        "publicNetworkAccess=tostring(properties.publicNetworkAccess) | limit 100",
    ),
    (
        "Virtual machines (managed disk & OS)",
        "Resources | where type =~ 'microsoft.compute/virtualMachines' "
        "| project name, resourceGroup, "
        "osType=tostring(properties.storageProfile.osDisk.osType), "
        "vmSize=tostring(properties.hardwareProfile.vmSize) | limit 100",
    ),
]


def _format_rows(rows: list[dict[str, Any]], limit: int = 60) -> str:
    if not rows:
        return "(none found)"
    shown = rows[:limit]
    lines = [json.dumps(row, default=str, separators=(",", ": ")) for row in shown]
    if len(rows) > limit:
        lines.append(f"... and {len(rows) - limit} more")
    return "\n".join(lines)


def build_environment_report(project_id: str, max_resources: int = 500) -> dict[str, Any]:
    """Fetch a live, read-only Azure environment report.

    Returns a dict with a formatted ``text`` block for the LLM plus structured
    ``meta`` (subscription, counts). Raises AzureConnectionError /
    AzureApiError on failure so the caller can surface a precise message.
    """
    creds = load_credentials(project_id)
    token = _get_token(creds)
    if not token:
        raise AzureApiError("Azure returned an empty access token.")

    subs = [creds.subscription_id] if creds.subscription_id else []

    counts = _run_query(token, subs, _COUNT_QUERY)
    inventory = _run_query(token, subs, _INVENTORY_QUERY)

    sections: list[str] = []
    scope = creds.subscription_id or "all subscriptions visible to this app"
    sections.append(f"Subscription scope: {scope}")
    sections.append(f"Total resources returned: {len(inventory)}")

    if counts:
        count_lines = "\n".join(
            f"- {row.get('type')}: {row.get('total')}" for row in counts[:60]
        )
        sections.append("Resource counts by type:\n" + count_lines)

    sections.append("Resource inventory (name, type, resourceGroup, location):\n"
                    + _format_rows(inventory, limit=max_resources))

    for label, query in _PROBES:
        try:
            rows = _run_query(token, subs, query)
        except AzureApiError as exc:
            sections.append(f"{label}:\n(could not evaluate: {exc})")
            continue
        sections.append(f"{label}:\n{_format_rows(rows)}")

    text = "\n\n".join(sections)
    return {
        "text": text,
        "meta": {
            "subscription": creds.subscription_id,
            "resource_count": len(inventory),
            "type_count": len(counts),
        },
    }


def parse_cost_period(text: str, today: Optional[date] = None) -> tuple[date, date, str]:
    """Resolve a natural-language billing period into (from, to, label).

    Understands 'june', 'june 2025', 'last month', 'this/current month' and a
    bare 'YYYY-MM'. Falls back to the current month. A month named without a year
    is assumed to be the most recent occurrence (this year, or last year if that
    month has not happened yet).
    """
    today = today or date.today()
    lowered = (text or "").lower()

    def _month_range(year: int, month: int) -> tuple[date, date, str]:
        first = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        last = date(year, month, last_day)
        if year == today.year and month == today.month:
            last = today
        label = f"{calendar.month_name[month]} {year}"
        return first, last, label

    iso = re.search(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b", lowered)
    if iso:
        return _month_range(int(iso.group(1)), int(iso.group(2)))

    if "last month" in lowered or "previous month" in lowered:
        year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return _month_range(year, month)

    if "this month" in lowered or "current month" in lowered:
        return _month_range(today.year, today.month)

    year_match = re.search(r"\b(20\d{2})\b", lowered)
    for token, month in _MONTHS.items():
        if re.search(rf"\b{token}\b", lowered):
            if year_match:
                year = int(year_match.group(1))
            else:
                year = today.year if month <= today.month else today.year - 1
            return _month_range(year, month)

    return _month_range(today.year, today.month)


def _cost_payload(
    from_date: date, to_date: date, group_by: str = "service"
) -> dict[str, Any]:
    grouping = [{"type": "Dimension", "name": "ServiceName"}]
    if group_by == "meter":
        grouping.append({"type": "Dimension", "name": "Meter"})
    return {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {
            "from": f"{from_date.isoformat()}T00:00:00Z",
            "to": f"{to_date.isoformat()}T23:59:59Z",
        },
        "dataset": {
            "granularity": "None",
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": grouping,
        },
    }


def build_cost_report(
    project_id: str,
    from_date: date,
    to_date: date,
    label: str,
    group_by: str = "service",
    service_filter: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Fetch real Azure spend for a period, grouped by service (and optionally meter).

    When ``service_filter`` is given, only services whose name contains one of
    the substrings are counted (e.g. ["storage"] or ["openai", "cognitive"]),
    so "billing for storage" or "Foundry token cost" can be answered precisely.
    With ``group_by="meter"`` the breakdown is per service+meter, which surfaces
    token meters (input/output) for Azure OpenAI. Raises AzureConnectionError /
    AzureApiError so the caller can surface a precise message.
    """
    creds = load_credentials(project_id)
    if not creds.subscription_id:
        raise AzureApiError(
            "No subscription id is set on the Azure connection, but a billing "
            "query needs a subscription scope. Add the subscription id in Settings."
        )
    token = _get_token(creds)
    if not token:
        raise AzureApiError("Azure returned an empty access token.")

    url = _COST_URL_TMPL.format(sub=creds.subscription_id)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = httpx.post(
            url,
            headers=headers,
            json=_cost_payload(from_date, to_date, group_by),
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise AzureApiError(f"Cost Management request failed: {exc}") from exc
    if resp.status_code != 200:
        raise AzureApiError(
            f"Cost Management query failed ({resp.status_code}): {_error_detail(resp)}"
        )

    props = resp.json().get("properties", {}) or {}
    columns = [c.get("name") for c in props.get("columns", [])]
    rows = props.get("rows", []) or []
    try:
        cost_idx = columns.index("Cost")
    except ValueError:
        cost_idx = 0
    service_idx = columns.index("ServiceName") if "ServiceName" in columns else None
    meter_idx = columns.index("Meter") if "Meter" in columns else None
    currency_idx = columns.index("Currency") if "Currency" in columns else None

    filters = [s.lower() for s in (service_filter or [])]
    lines: list[dict[str, Any]] = []
    total = 0.0
    currency = "USD"
    for row in rows:
        service = row[service_idx] if service_idx is not None else "(unknown)"
        if filters and not any(f in str(service).lower() for f in filters):
            continue
        amount = float(row[cost_idx]) if row[cost_idx] is not None else 0.0
        total += amount
        if currency_idx is not None and row[currency_idx]:
            currency = row[currency_idx]
        entry: dict[str, Any] = {"service": service, "cost": round(amount, 2)}
        if meter_idx is not None:
            entry["meter"] = row[meter_idx]
        lines.append(entry)
    lines.sort(key=lambda item: item["cost"], reverse=True)

    filter_label = ", ".join(service_filter) if service_filter else ""
    scope = f"for {filter_label} " if filter_label else ""
    total_scope = f" ({filter_label})" if filter_label else ""
    sections = [
        f"Azure spend {scope}for {label} (subscription {creds.subscription_id}), "
        f"actual cost from {from_date.isoformat()} to {to_date.isoformat()}.",
        f"Total{total_scope}: {round(total, 2)} {currency}",
    ]
    if lines:
        if group_by == "meter":
            breakdown = "\n".join(
                f"- {item['service']} / {item.get('meter', '(meter)')}: "
                f"{item['cost']} {currency}"
                for item in lines
            )
            sections.append("Cost by service and meter:\n" + breakdown)
        else:
            breakdown = "\n".join(
                f"- {item['service']}: {item['cost']} {currency}" for item in lines
            )
            sections.append("Cost by service:\n" + breakdown)
    elif filters:
        sections.append(
            f"No charges matched {', '.join(service_filter)} for this period "
            f"(the total is {round(total, 2)} {currency})."
        )
    else:
        sections.append(
            "No usage/charges were recorded for this period (the total is "
            f"{round(total, 2)} {currency})."
        )

    return {
        "text": "\n\n".join(sections),
        "meta": {
            "subscription": creds.subscription_id,
            "period": label,
            "total": round(total, 2),
            "currency": currency,
            "lines": len(lines),
        },
    }


_NANO_PER_CORE = 1_000_000_000


# Minutes per unit, keyed by the singular base of each accepted spelling.
_UNIT_MINUTES = {
    "minute": 1,
    "min": 1,
    "hour": 60,
    "hr": 60,
    "day": 1440,
    "week": 10080,
    "month": 43200,
}
# Canonical name shown to the user for each base unit.
_UNIT_NAME = {
    "minute": "minute",
    "min": "minute",
    "hour": "hour",
    "hr": "hour",
    "day": "day",
    "week": "week",
    "month": "month",
}
_MAX_WINDOW_MIN = 90 * 1440  # Azure Monitor keeps metrics ~93 days.


def _pick_interval(total_minutes: int) -> str:
    """Choose a sampling interval that yields a readable number of points."""
    if total_minutes <= 90:
        return "PT1M"
    if total_minutes <= 360:
        return "PT5M"
    if total_minutes <= 1440:
        return "PT15M"
    if total_minutes <= 4320:
        return "PT30M"
    if total_minutes <= 10080:
        return "PT1H"
    if total_minutes <= 43200:
        return "PT6H"
    return "P1D"


def _window_from(qty: int, base: str, now: datetime):
    total = min(max(qty, 1) * _UNIT_MINUTES[base], _MAX_WINDOW_MIN)
    name = _UNIT_NAME[base]
    label = f"last {qty} {name}{'s' if qty != 1 else ''}"
    return now - timedelta(minutes=total), now, _pick_interval(total), label


def parse_metrics_window(text: str, now: Optional[datetime] = None):
    """Resolve a natural-language window into (start, end, interval, label).

    Understands any "last N minutes/hours/days/weeks/months" phrasing (and a
    bare "last hour/day/week" with an implied 1). Defaults to 24 hours only when
    no window is expressed.
    """
    now = now or datetime.now(timezone.utc)
    lowered = (text or "").lower()
    # Contextual follow-ups place the current request before this marker. Try
    # that segment first so an older "last 24 hours" does not override a new
    # request such as "this particular hour".
    candidates = [lowered]
    current_marker = "current user request:"
    context_marker = "conversation context:"
    if current_marker in lowered and context_marker in lowered:
        current = lowered.split(current_marker, 1)[1].split(context_marker, 1)[0]
        candidates.insert(0, current)
    for candidate in candidates:
        match = re.search(
            r"(\d+)\s*(minutes?|mins?|hours?|hrs?|days?|weeks?|months?)", candidate
        )
        if match:
            base = match.group(2).rstrip("s")
            return _window_from(int(match.group(1)), base, now)
        for base in ("minute", "hour", "day", "week", "month"):
            if base in candidate:
                return _window_from(1, base, now)
    return now - timedelta(hours=24), now, "PT15M", "last 24 hours"


# Friendly resource keyword -> the Azure resource type(s) to query for metrics.
_RESOURCE_TYPES: dict[str, list[str]] = {
    "container_app": ["microsoft.app/containerapps"],
    "postgresql": [
        "microsoft.dbforpostgresql/flexibleservers",
        "microsoft.dbforpostgresql/servers",
    ],
    "mysql": [
        "microsoft.dbformysql/flexibleservers",
        "microsoft.dbformysql/servers",
    ],
    "mariadb": ["microsoft.dbformariadb/servers"],
    "vm": ["microsoft.compute/virtualmachines"],
    "vmss": ["microsoft.compute/virtualmachinescalesets"],
    "sql_database": ["microsoft.sql/servers/databases"],
    "storage": ["microsoft.storage/storageaccounts"],
    "web_app": ["microsoft.web/sites"],
    "aks": ["microsoft.containerservice/managedclusters"],
    "redis": ["microsoft.cache/redis"],
    "cosmos": ["microsoft.documentdb/databaseaccounts"],
    "app_gateway": ["microsoft.network/applicationgateways"],
    "service_bus": ["microsoft.servicebus/namespaces"],
    "event_hub": ["microsoft.eventhub/namespaces"],
    "cognitive": ["microsoft.cognitiveservices/accounts"],
    "openai": ["microsoft.cognitiveservices/accounts"],
    "foundry": ["microsoft.cognitiveservices/accounts"],
}
_CONTAINER_APP_TYPE = "microsoft.app/containerapps"

# Raw-text fallbacks used when the caller didn't pass a structured resource hint.
_TYPE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (
        (
            "container app",
            "containerapp",
            "container-app",
            "connected app",
            "connected apps",
            "my app",
            "my apps",
            "aca",
        ),
        "container_app",
    ),
    (("postgres", "postgre", "psql"), "postgresql"),
    (("mysql",), "mysql"),
    (("mariadb",), "mariadb"),
    (("virtual machine", " vm ", "vm ", " vm", "vmss"), "vm"),
    (("sql database", "sql db", "azure sql"), "sql_database"),
    (("storage account", "blob storage", "storage account"), "storage"),
    (("web app", "app service", "function app", "webapp"), "web_app"),
    (("aks", "kubernetes cluster", "managed cluster"), "aks"),
    (("redis",), "redis"),
    (("cosmos", "cosmosdb"), "cosmos"),
    (
        ("foundry", "openai", "open ai", "cognitive", "ai model", "ai service", "gpt", "llm"),
        "cognitive",
    ),
]

# Requested metric keyword -> substrings we look for in a metric's name/displayName.
_METRIC_MATCHERS: dict[str, tuple[str, ...]] = {
    "cpu": ("cpu", "usagenanocores", "percentage cpu"),
    "memory": ("memory", "workingset", "working set"),
    "connections": ("connection",),
    "iops": ("iops", "io_consumption"),
    "disk": ("disk", "iops"),
    "storage": ("storage", "usedcapacity", "used capacity", "capacity"),
    "requests": ("request",),
    "latency": ("latency", "response time", "responsetime", "duration"),
    "network": ("network", "rxbytes", "txbytes", "bytes received", "bytes sent", "egress", "ingress"),
    "replicas": ("replica",),
    "restarts": ("restart",),
    "errors": ("error", "5xx", "4xx", "failed"),
    "transactions": ("transaction",),
    "tokens": ("totaltokens", "tokens", "tokentransaction"),
    "input_tokens": ("inputtokens", "processedprompttokens", "prompttokens"),
    "output_tokens": ("outputtokens", "generatedtokens", "completiontokens"),
    "calls": ("totalcalls", "azureopenairequests", "modelrequests", "request"),
}
# Synonyms used to infer which metrics the user asked for from raw text.
_HINT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "cpu": ("cpu", "processor"),
    "memory": ("memory", "ram", "mem "),
    "connections": ("connection",),
    "iops": ("iops",),
    "storage": ("storage", "capacity", "disk usage", "used capacity"),
    "requests": ("request", "traffic"),
    "latency": ("latency", "response time"),
    "network": ("network", "bandwidth", "throughput"),
    "replicas": ("replica", "instances"),
    "restarts": ("restart",),
    "errors": ("error", "5xx", "4xx", "failure"),
    "transactions": ("transaction",),
    "input_tokens": ("input token", "prompt token"),
    "output_tokens": ("output token", "completion token", "generated token"),
    "tokens": ("token usage", "total token", "how many token", "tokens expend"),
    "calls": ("api call", "number of calls", "how many calls", "how many requests"),
}
_METRIC_TITLES: dict[str, str] = {
    "cpu": "CPU",
    "memory": "Memory",
    "connections": "Connections",
    "iops": "IOPS",
    "disk": "Disk",
    "storage": "Storage",
    "requests": "Requests",
    "latency": "Latency",
    "network": "Network",
    "replicas": "Replicas",
    "restarts": "Restarts",
    "errors": "Errors",
    "transactions": "Transactions",
    "tokens": "Total tokens",
    "input_tokens": "Input tokens",
    "output_tokens": "Output tokens",
    "calls": "Calls",
}
_DEFAULT_METRIC_HINTS = ("cpu",)
_MAX_METRICS = 6


def _kql_escape(value: str) -> str:
    return value.replace("'", "''")


def _infer_resource_types(text: str):
    lowered = f" {text.lower()} "
    for keywords, key in _TYPE_KEYWORDS:
        if any(k in lowered for k in keywords):
            return _RESOURCE_TYPES[key], key
    return None, None


_GENERIC_RESOURCE_NAMES = {
    "app",
    "apps",
    "my app",
    "my apps",
    "the app",
    "the apps",
    "connected app",
    "connected apps",
    "the connected app",
    "the connected apps",
    "container app",
    "container apps",
    "aca",
    "all",
    "every",
    "everyone",
    "everything",
    "existing",
    "all of them",
    "all apps",
    "all container apps",
    "every container app",
    "everyone which exist",
    "everyone that exists",
    "which exist",
    "that exist",
    "any",
    "any of them",
}


_ALL_RESOURCES_TERMS = (
    r"\ball\b",
    r"\bevery\b",
    r"\beveryone\b",
    r"\beverything\b",
    r"\bexisting\b",
    r"\beach\b",
    r"\bany\b",
    r"which exist",
    r"that exist",
    r"all of them",
    r"every one",
)


def wants_all_resources(text: str) -> bool:
    """True when the user asks for every matching resource, not one name."""
    lowered = (text or "").lower()
    return any(re.search(pattern, lowered) for pattern in _ALL_RESOURCES_TERMS)


def _specific_resource_name(value: Any) -> Optional[str]:
    """Ignore natural-language collection labels returned as resource names."""
    if not isinstance(value, str):
        return None
    name = re.sub(r"\s+", " ", value).strip()
    lowered = name.lower()
    if lowered in _GENERIC_RESOURCE_NAMES or wants_all_resources(lowered):
        return None
    return name or None


# Names that make a good generic default when the user asks broadly for "metrics".
_DEFAULT_METRIC_KEYWORDS = (
    "percent",
    "utilization",
    "used",
    "capacity",
    "transaction",
    "request",
    "availability",
    "connection",
    "latency",
    "count",
    "throughput",
    "tokens",
)


def _default_definitions(defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick a handful of representative metrics for a broad 'metrics for X' ask."""
    scored: list[tuple[int, dict[str, Any]]] = []
    for definition in defs:
        name = ((definition.get("name", {}) or {}).get("value") or "").lower()
        score = sum(1 for kw in _DEFAULT_METRIC_KEYWORDS if kw in name)
        if (definition.get("unit") or "").lower() == "percent":
            score += 2
        if score:
            scored.append((score, definition))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked = [d for _, d in scored[: _MAX_METRICS]]
    return picked or defs[:_MAX_METRICS]


def _infer_metric_hints(text: str) -> list[str]:
    lowered = text.lower()
    hints = [
        hint
        for hint, syns in _HINT_SYNONYMS.items()
        if any(s in lowered for s in syns)
    ]
    return hints[:_MAX_METRICS] or list(_DEFAULT_METRIC_HINTS)


def _select_resources(text: str, resources: list[dict[str, Any]], limit: int = 3):
    """Prefer resources whose name the user named; otherwise take the first few.

    When the user asks for all/every existing resource, return a larger set so
    the chat does not pretend it needs a single app name.
    """
    lowered = (text or "").lower()
    if wants_all_resources(lowered):
        limit = max(limit, 25)
    named = [
        r
        for r in resources
        if (r.get("name") or "").lower()
        and (r.get("name") or "").lower() in lowered
        and not wants_all_resources((r.get("name") or ""))
    ]
    # Ignore accidental matches on tiny substrings when the user said "all".
    if wants_all_resources(lowered):
        named = []
    return (named or resources)[:limit]


def _fetch_metric(
    token: str,
    resource_id: str,
    metricname: str,
    aggregation: str,
    start: datetime,
    end: datetime,
    interval: str,
) -> dict[str, Any]:
    url = f"{_ARM}{resource_id}/providers/microsoft.insights/metrics"
    params = {
        "api-version": "2018-01-01",
        "metricnames": metricname,
        "timespan": (
            f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        ),
        "interval": interval,
        "aggregation": aggregation,
    }
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise AzureApiError(f"Metrics request failed: {exc}") from exc
    if resp.status_code != 200:
        raise AzureApiError(
            f"Metrics query failed ({resp.status_code}): {_error_detail(resp)}"
        )
    return resp.json()


def _fetch_metric_definitions(token: str, resource_id: str) -> list[dict[str, Any]]:
    """List the metrics Azure Monitor actually exposes for this resource."""
    url = f"{_ARM}{resource_id}/providers/microsoft.insights/metricDefinitions"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.get(
            url, headers=headers, params={"api-version": "2018-01-01"}, timeout=_TIMEOUT
        )
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []
    return resp.json().get("value", []) or []


# Names to strongly prefer when several metrics contain the hint word (e.g.
# "cpu_percent" should win over "cpu_credits_remaining").
_PREFERRED_METRICS: dict[str, tuple[str, ...]] = {
    "cpu": ("cpu_percent", "percentage cpu", "cpu percent", "usagenanocores"),
    "memory": (
        "memory_percent",
        "memory percent",
        "workingsetbytes",
        "available memory bytes",
        "memoryworkingset",
    ),
    "storage": ("storage_percent", "used capacity", "usedcapacity", "storage used"),
    "connections": ("active_connections", "connections", "connection_attempts"),
    "iops": ("iops", "io_consumption_percent"),
    "tokens": ("totaltokens", "tokentransaction"),
    "input_tokens": ("inputtokens", "processedprompttokens"),
    "output_tokens": ("outputtokens", "generatedtokens"),
    "calls": ("totalcalls", "azureopenairequests", "modelrequests"),
    "transactions": ("transactions",),
}


def _match_definition(
    defs: list[dict[str, Any]], hint: str
) -> Optional[dict[str, Any]]:
    """Pick the most relevant exposed metric for a hint, preferring % metrics."""
    subs = _METRIC_MATCHERS.get(hint, (hint,))
    prefs = _PREFERRED_METRICS.get(hint, ())
    prefer_percent = hint in ("cpu", "memory", "storage")
    best: Optional[dict[str, Any]] = None
    best_score = -1
    for definition in defs:
        name_obj = definition.get("name", {}) or {}
        name = (name_obj.get("value") or "").lower()
        disp = (name_obj.get("localizedValue") or name).lower()
        haystack = f"{name} {disp}"
        if not any(s in haystack for s in subs):
            continue
        score = 1
        if name in prefs:
            score += 5
        elif any(p in haystack for p in prefs):
            score += 3
        if prefer_percent and (definition.get("unit") == "Percent" or "percent" in haystack):
            score += 2
        if score > best_score:
            best = definition
            best_score = score
    return best


def _metric_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = payload.get("value") or []
    if not values:
        return []
    series = values[0].get("timeseries") or []
    if not series:
        return []
    return series[0].get("data") or []


def _parse_mem_bytes(alloc: Optional[str]) -> Optional[float]:
    if not alloc:
        return None
    match = re.match(r"([\d.]+)\s*([a-zA-Z]*)", str(alloc).strip())
    if not match:
        return None
    qty = float(match.group(1))
    unit = match.group(2).lower()
    factors = {"": 1, "gi": 1024**3, "mi": 1024**2, "ki": 1024, "g": 1e9, "m": 1e6}
    return qty * factors.get(unit, 1)


def _display_value(unit: Optional[str], value: float) -> tuple[float, str]:
    u = (unit or "").lower()
    if u in ("percent", "percentage"):
        return round(value, 2), "%"
    if u == "bytes":
        return round(value / 1e6, 2), "MB"
    if u == "bytespersecond":
        return round(value / 1e3, 2), "KB/s"
    if u == "countpersecond":
        return round(value, 2), "/s"
    if u == "milliseconds":
        return round(value, 2), "ms"
    if u == "seconds":
        return round(value, 2), "s"
    if u == "count":
        return round(value, 2), ""
    return round(value, 2), unit or ""


def _agg_key(primary: str) -> str:
    return (primary or "Average").lower()


def build_metrics_report(
    project_id: str,
    task: str,
    resource_types: Optional[list[str]] = None,
    resource_name: Optional[str] = None,
    metric_hints: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Fetch live, read-only Azure Monitor metrics for graphing — generically.

    The resource type (Container App, PostgreSQL, VM, SQL, storage, …) and the
    metrics to plot (CPU, memory, connections, IOPS, …) are driven by what the
    caller asks for: ``resource_types``/``resource_name``/``metric_hints`` when
    the AI has parsed the request, otherwise inferred from ``task``. For each
    resource we read the metrics Azure Monitor actually exposes (via metric
    definitions) and plot one chart per requested metric with a series per
    resource. Raises AzureConnectionError / AzureApiError on failure.
    """
    creds = load_credentials(project_id)
    if not creds.subscription_id:
        raise AzureApiError(
            "No subscription id is set on the Azure connection, but reading "
            "metrics needs a subscription scope. Add it in Settings."
        )
    token = _get_token(creds)
    if not token:
        raise AzureApiError("Azure returned an empty access token.")
    subs = [creds.subscription_id]
    start, end, interval, label = parse_metrics_window(task)

    azure_types: Optional[list[str]] = None
    if resource_types:
        azure_types = [
            t for key in resource_types for t in _RESOURCE_TYPES.get(key, [])
        ] or None
    if azure_types is None:
        azure_types, _ = _infer_resource_types(task)

    resource_name = _specific_resource_name(resource_name)
    resources = _discover_resources(token, subs, azure_types, resource_name)
    if not resources and resource_name:
        resources = _run_query(
            token,
            subs,
            f"Resources | where name contains '{_kql_escape(resource_name)}' "
            "| extend cpuAlloc = todouble(properties.template.containers[0].resources.cpu), "
            "memAlloc = tostring(properties.template.containers[0].resources.memory) "
            "| project name, id, type, resourceGroup, cpuAlloc, memAlloc | limit 30",
        )
    if not resources and azure_types is None:
        azure_types = _RESOURCE_TYPES["container_app"]
        resources = _discover_resources(token, subs, azure_types, None)
    if not resources:
        target = resource_name or (
            ", ".join(azure_types) if azure_types else "the requested resource"
        )
        raise AzureApiError(
            f"No resources matching '{target}' were found in subscription "
            f"{creds.subscription_id} to read metrics from."
        )

    selected = _select_resources(task, resources)
    hints = list(metric_hints or []) or _infer_metric_hints(task)
    # Broad health asks ("CPU/memory or request metrics") should cover the common set.
    lowered_task = (task or "").lower()
    if any(term in lowered_task for term in ("health", "cpu", "memory")) and (
        "request" in lowered_task or "or request" in lowered_task or wants_all_resources(lowered_task)
    ):
        for hint in ("cpu", "memory", "requests"):
            if hint not in hints:
                hints.append(hint)
    elif any(term in lowered_task for term in ("cpu", "memory")):
        for hint in ("cpu", "memory"):
            if hint not in hints:
                hints.append(hint)
    hints = hints[:_MAX_METRICS]

    ca_resources = [
        r
        for r in selected
        if (r.get("type") or "").lower() == _CONTAINER_APP_TYPE
    ]
    ca_cpu_pct = bool(ca_resources) and all(r.get("cpuAlloc") for r in ca_resources)
    ca_mem_pct = bool(ca_resources) and all(
        _parse_mem_bytes(r.get("memAlloc")) for r in ca_resources
    )

    defs_cache: dict[str, list[dict[str, Any]]] = {}
    charts: list[dict[str, Any]] = []
    summaries: list[str] = []
    missing: list[str] = []

    for hint in hints:
        series: list[dict[str, Any]] = []
        chart_unit = ""
        display_name = _METRIC_TITLES.get(hint, hint.title())
        for resource in selected:
            rid = resource["id"]
            defs = defs_cache.get(rid)
            if defs is None:
                defs = _fetch_metric_definitions(token, rid)
                defs_cache[rid] = defs
            definition = _match_definition(defs, hint)
            if not definition:
                continue
            metric_name = (definition.get("name", {}) or {}).get("value") or ""
            primary = definition.get("primaryAggregationType") or "Average"
            unit_meta = definition.get("unit")
            is_ca = (resource.get("type") or "").lower() == _CONTAINER_APP_TYPE
            try:
                payload = _fetch_metric(
                    token, rid, metric_name, primary, start, end, interval
                )
            except AzureApiError:
                continue
            key = _agg_key(primary)
            points: list[dict[str, Any]] = []
            values: list[float] = []
            for row in _metric_points(payload):
                raw = row.get(key)
                if raw is None:
                    continue
                if is_ca and metric_name == "UsageNanoCores":
                    cores = float(raw) / _NANO_PER_CORE
                    if ca_cpu_pct and resource.get("cpuAlloc"):
                        value, unit = round(cores / float(resource["cpuAlloc"]) * 100, 2), "%"
                    else:
                        value, unit = round(cores * 1000, 2), "millicores"
                elif is_ca and metric_name == "WorkingSetBytes":
                    alloc = _parse_mem_bytes(resource.get("memAlloc"))
                    if ca_mem_pct and alloc:
                        value, unit = round(float(raw) / alloc * 100, 2), "%"
                    else:
                        value, unit = round(float(raw) / 1e6, 2), "MB"
                else:
                    value, unit = _display_value(unit_meta, float(raw))
                points.append({"t": row.get("timeStamp"), "v": value})
                values.append(value)
                chart_unit = unit
            if not points:
                continue
            avg_v = round(sum(values) / len(values), 2)
            series.append({"name": resource["name"], "points": points})
            if (primary or "").lower() == "total":
                summaries.append(
                    f"- {resource['name']} — {display_name}: total "
                    f"{round(sum(values), 2)}{chart_unit} over the window, "
                    f"peak {max(values)}{chart_unit} per bucket ({len(points)} "
                    "buckets)"
                )
            else:
                summaries.append(
                    f"- {resource['name']} — {display_name}: avg {avg_v}{chart_unit}, "
                    f"peak {max(values)}{chart_unit}, min {min(values)}{chart_unit} "
                    f"({len(points)} samples)"
                )
        if series:
            charts.append(
                {
                    "title": f"{display_name} — {label}",
                    "unit": chart_unit,
                    "type": "line",
                    "series": series,
                }
            )
        else:
            missing.append(display_name)

    if not charts:
        # Requested metrics had no data — fall back to whatever this resource
        # type actually emits so a generic "metrics for X" still returns real
        # figures instead of an empty answer.
        for resource in selected:
            rid = resource["id"]
            defs = defs_cache.get(rid)
            if defs is None:
                defs = _fetch_metric_definitions(token, rid)
                defs_cache[rid] = defs
            for definition in _default_definitions(defs):
                metric_name = (definition.get("name", {}) or {}).get("value") or ""
                title = (
                    (definition.get("name", {}) or {}).get("localizedValue")
                    or metric_name
                )
                primary = definition.get("primaryAggregationType") or "Average"
                unit_meta = definition.get("unit")
                try:
                    payload = _fetch_metric(
                        token, rid, metric_name, primary, start, end, interval
                    )
                except AzureApiError:
                    continue
                key = _agg_key(primary)
                points: list[dict[str, Any]] = []
                values: list[float] = []
                chart_unit = ""
                for row in _metric_points(payload):
                    raw = row.get(key)
                    if raw is None:
                        continue
                    value, unit = _display_value(unit_meta, float(raw))
                    points.append({"t": row.get("timeStamp"), "v": value})
                    values.append(value)
                    chart_unit = unit
                if not points or not any(values):
                    continue
                if (primary or "").lower() == "total":
                    summaries.append(
                        f"- {resource['name']} — {title}: total "
                        f"{round(sum(values), 2)}{chart_unit} over the window, "
                        f"peak {max(values)}{chart_unit} per bucket "
                        f"({len(points)} buckets)"
                    )
                else:
                    summaries.append(
                        f"- {resource['name']} — {title}: avg "
                        f"{round(sum(values) / len(values), 2)}{chart_unit}, "
                        f"peak {max(values)}{chart_unit}, min "
                        f"{min(values)}{chart_unit} ({len(points)} samples)"
                    )
                charts.append(
                    {
                        "title": f"{title} — {label}",
                        "unit": chart_unit,
                        "type": "line",
                        "series": [{"name": resource["name"], "points": points}],
                    }
                )
                if len(charts) >= _MAX_METRICS:
                    break
            if charts:
                missing = []
                break

    if not charts:
        raise AzureApiError(
            f"The resources were found but Azure Monitor returned no data for "
            f"{', '.join(missing) or 'the requested metrics'} over the {label}. "
            "The metric may be unavailable for this resource type or the resource "
            "was idle/scaled to zero."
        )

    names = ", ".join(sorted({s["name"] for c in charts for s in c["series"]}))
    note = (
        f" (no data for {', '.join(missing)})" if missing else ""
    )
    text = (
        f"Live Azure Monitor metrics for {names} over the {label}, subscription "
        f"{creds.subscription_id}{note}:\n" + "\n".join(summaries)
    )
    return {
        "text": text,
        "meta": {"subscription": creds.subscription_id, "window": label},
        "charts": charts,
    }


def _discover_resources(
    token: str,
    subscriptions: list[str],
    azure_types: Optional[list[str]],
    resource_name: Optional[str],
) -> list[dict[str, Any]]:
    """Find candidate resources by type (and optional name) for metric reads."""
    if not azure_types:
        return []
    type_clause = " or ".join(f"type =~ '{t}'" for t in azure_types)
    name_clause = (
        f" and name contains '{_kql_escape(resource_name)}'" if resource_name else ""
    )
    query = (
        f"Resources | where ({type_clause}){name_clause} "
        "| extend cpuAlloc = todouble(properties.template.containers[0].resources.cpu), "
        "memAlloc = tostring(properties.template.containers[0].resources.memory) "
        "| project name, id, type, resourceGroup, cpuAlloc, memAlloc | limit 30"
    )
    return _run_query(token, subscriptions, query)


def _fetch_metric_split(
    token: str,
    resource_id: str,
    metricname: str,
    aggregation: str,
    start: datetime,
    end: datetime,
    interval: str,
    dimension: str,
) -> dict[str, Any]:
    """Fetch a metric split by a dimension (e.g. Requests by statusCode)."""
    url = f"{_ARM}{resource_id}/providers/microsoft.insights/metrics"
    params = {
        "api-version": "2018-01-01",
        "metricnames": metricname,
        "timespan": (
            f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        ),
        "interval": interval,
        "aggregation": aggregation,
        "$filter": f"{dimension} eq '*'",
        "top": "50",
    }
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise AzureApiError(f"Metrics request failed: {exc}") from exc
    if resp.status_code != 200:
        raise AzureApiError(
            f"Metrics query failed ({resp.status_code}): {_error_detail(resp)}"
        )
    return resp.json()


def _parse_status_targets(task: str) -> tuple[set[str], set[str], bool]:
    """Extract the HTTP status codes / categories the user asked about."""
    lowered = task.lower()
    codes = set(re.findall(r"\b([1-5]\d\d)\b", lowered))
    categories = set(re.findall(r"([1-5])xx", lowered))
    categories = {f"{c}xx" for c in categories}
    errors = any(t in lowered for t in ("error", "fail", "5xx", "4xx", "not ok", "non-2xx"))
    return codes, categories, errors


def build_status_report(
    project_id: str, task: str, resource_name: Optional[str] = None
) -> dict[str, Any]:
    """Count container app HTTP responses by status code from request telemetry.

    Reads the Container Apps ``Requests`` metric split by status code (Azure
    Monitor, read-only) so questions like "how many 400 / 500 in the last hour"
    are answered from real request telemetry — no log pasting. Returns an LLM
    ``text`` summary plus ``charts`` (4xx / 5xx over time). Raises
    AzureConnectionError / AzureApiError on failure.
    """
    creds = load_credentials(project_id)
    if not creds.subscription_id:
        raise AzureApiError(
            "No subscription id is set on the Azure connection, but reading "
            "request telemetry needs a subscription scope. Add it in Settings."
        )
    token = _get_token(creds)
    if not token:
        raise AzureApiError("Azure returned an empty access token.")
    subs = [creds.subscription_id]
    start, end, interval, label = parse_metrics_window(task)

    resources = _discover_resources(
        token, subs, _RESOURCE_TYPES["container_app"], resource_name
    )
    if not resources:
        raise AzureApiError(
            f"No container apps were found in subscription {creds.subscription_id} "
            "to read request/error telemetry from."
        )
    selected = _select_resources(task, resources)
    want_codes, want_cats, want_errors = _parse_status_targets(task)

    summaries: list[str] = []
    error_series: list[dict[str, Any]] = []
    any_data = False
    for resource in selected:
        try:
            payload = _fetch_metric_split(
                token, resource["id"], "Requests", "Total", start, end, interval,
                "statusCode",
            )
        except AzureApiError:
            continue
        # code -> {timestamp -> count}
        per_code: dict[str, dict[str, float]] = {}
        for ts in (payload.get("value") or [{}])[0].get("timeseries", []) or []:
            meta = ts.get("metadatavalues") or []
            code = "unknown"
            for m in meta:
                if (m.get("name", {}) or {}).get("value", "").lower() == "statuscode":
                    code = str(m.get("value"))
            bucket = per_code.setdefault(code, {})
            for row in ts.get("data", []) or []:
                val = row.get("total")
                if val is None:
                    continue
                bucket[row.get("timeStamp")] = float(val)

        if not per_code:
            continue
        any_data = True
        totals = {code: sum(b.values()) for code, b in per_code.items()}
        cat_totals: dict[str, float] = {}
        for code, tot in totals.items():
            if code[:1] in "12345":
                cat_totals[f"{code[0]}xx"] = cat_totals.get(f"{code[0]}xx", 0) + tot
        total_reqs = sum(totals.values())

        parts = [f"{code}={int(tot)}" for code, tot in sorted(totals.items())]
        cat_parts = [
            f"{cat}={int(tot)}" for cat, tot in sorted(cat_totals.items())
        ]
        detail = ""
        highlighted = sorted(want_codes) + sorted(want_cats)
        if want_errors and not want_codes and not want_cats:
            errs = int(cat_totals.get("4xx", 0) + cat_totals.get("5xx", 0))
            detail = f" | errors (4xx+5xx)={errs}"
        elif highlighted:
            picks = []
            for code in sorted(want_codes):
                picks.append(f"{code}={int(totals.get(code, 0))}")
            for cat in sorted(want_cats):
                picks.append(f"{cat}={int(cat_totals.get(cat, 0))}")
            detail = " | asked: " + ", ".join(picks)

        summaries.append(
            f"- {resource['name']}: {int(total_reqs)} requests over the {label}. "
            f"By category: {', '.join(cat_parts) or 'none'}. "
            f"By code: {', '.join(parts) or 'none'}.{detail}"
        )

        # Build 4xx / 5xx time series aligned by timestamp for the chart.
        timeline = sorted({t for b in per_code.values() for t in b})
        for cat, prefix in (("4xx", "4"), ("5xx", "5")):
            pts = []
            has = False
            for stamp in timeline:
                v = sum(
                    b.get(stamp, 0)
                    for code, b in per_code.items()
                    if code[:1] == prefix
                )
                if v:
                    has = True
                pts.append({"t": stamp, "v": round(v, 2)})
            if has:
                error_series.append(
                    {"name": f"{resource['name']} {cat}", "points": pts}
                )

    if not any_data:
        raise AzureApiError(
            "The container apps were found but Azure Monitor returned no request "
            f"telemetry for the {label}. The apps may have had no ingress traffic "
            "in that window."
        )

    charts = []
    if error_series:
        charts.append(
            {
                "title": f"HTTP 4xx / 5xx responses — {label}",
                "unit": "",
                "type": "bar",
                "series": error_series,
            }
        )
    text = (
        f"Live Azure Monitor request telemetry for container apps over the "
        f"{label}, subscription {creds.subscription_id} (counts by HTTP status "
        "code):\n" + "\n".join(summaries)
    )
    return {
        "text": text,
        "meta": {"subscription": creds.subscription_id, "window": label},
        "charts": charts,
    }


def _arm_get(token: str, path: str, api_version: str) -> dict[str, Any]:
    url = f"{_ARM}{path}"
    url = f"{url}{'&' if '?' in url else '?'}api-version={api_version}"
    try:
        resp = httpx.get(
            url, headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT
        )
    except httpx.HTTPError as exc:
        raise AzureApiError(f"Azure request failed: {exc}") from exc
    if resp.status_code != 200:
        raise AzureApiError(
            f"Azure request failed ({resp.status_code}): {_error_detail(resp)}"
        )
    return resp.json()


def _get_logs_token(creds: AzureCredentials) -> str:
    return _get_token(creds, _LOGS_SCOPE)


def _log_timespan(start: datetime, end: datetime) -> str:
    return (
        f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/"
        f"{end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )


def _run_log_query(
    logs_token: str, workspace_id: str, kql: str, timespan: str
) -> tuple[list[str], list[list[Any]]]:
    """Run a read-only KQL query against a Log Analytics workspace."""
    url = _LOGS_URL_TMPL.format(ws=workspace_id)
    headers = {"Authorization": f"Bearer {logs_token}", "Content-Type": "application/json"}
    try:
        resp = httpx.post(
            url, headers=headers, json={"query": kql, "timespan": timespan},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise AzureApiError(f"Log Analytics request failed: {exc}") from exc
    if resp.status_code != 200:
        raise AzureApiError(
            f"Log Analytics query failed ({resp.status_code}): {_error_detail(resp)}"
        )
    tables = resp.json().get("tables", []) or []
    if not tables:
        return [], []
    cols = [c.get("name") for c in tables[0].get("columns", [])]
    return cols, tables[0].get("rows", []) or []


def _log_workspaces(token: str, subs: list[str]) -> list[str]:
    """Workspace customer ids that container app environments log to (dev first)."""
    rows = _run_query(
        token,
        subs,
        "Resources | where type =~ 'microsoft.app/managedenvironments' "
        "| project cid = tostring(properties.appLogsConfiguration."
        "logAnalyticsConfiguration.customerId)",
    )
    return [r["cid"] for r in rows if r.get("cid")]


def _fmt_log_rows(cols: list[str], rows: list[list[Any]], limit: int = 25) -> str:
    if not rows:
        return "(none)"
    lines = []
    for row in rows[:limit]:
        parts = []
        for name, value in zip(cols, row):
            if value in (None, ""):
                continue
            text = str(value).replace("\n", " ").strip()
            if len(text) > 300:
                text = text[:300] + "…"
            parts.append(f"{name}={text}")
        lines.append("- " + " | ".join(parts))
    if len(rows) > limit:
        lines.append(f"… and {len(rows) - limit} more")
    return "\n".join(lines)


def build_logs_report(
    project_id: str, task: str, resource_name: Optional[str] = None
) -> dict[str, Any]:
    """Read real container app (and Postgres) logs from Log Analytics.

    Fetches, read-only, the container app revision status (ARM), recent
    system/lifecycle events and warnings, and recent error/stderr console lines
    for the requested window, so questions like "my revision failed, what
    happened" or "show me the errors in my container app logs" are answered from
    REAL log data. Includes Postgres server errors when the user asks about the
    database. Raises AzureConnectionError / AzureApiError on failure.
    """
    creds = load_credentials(project_id)
    if not creds.subscription_id:
        raise AzureApiError(
            "No subscription id is set on the Azure connection, but reading logs "
            "needs a subscription scope. Add it in Settings."
        )
    token = _get_token(creds)
    subs = [creds.subscription_id]
    start, end, _interval, label = parse_metrics_window(task)
    timespan = _log_timespan(start, end)

    ws_ids = _log_workspaces(token, subs)
    if not ws_ids:
        rows = _run_query(
            token,
            subs,
            "Resources | where type =~ 'microsoft.operationalinsights/workspaces' "
            "| project cid = tostring(properties.customerId)",
        )
        ws_ids = [r["cid"] for r in rows if r.get("cid")]
    if not ws_ids:
        raise AzureApiError(
            "No Log Analytics workspace is linked to your container app "
            "environment, so there are no container logs to read."
        )

    logs_token = _get_logs_token(creds)
    workspace = ws_ids[0]
    task_lower = task.lower()
    esc = _kql_escape(resource_name) if resource_name else ""
    app_filter = f"| where ContainerAppName_s contains '{esc}'" if esc else ""

    sections: list[str] = [
        f"LIVE AZURE LOGS for the {label} (subscription {creds.subscription_id}), "
        "read-only from Log Analytics and the Container Apps control plane."
    ]

    # Revision status from ARM (which revision is active / failed / unhealthy).
    apps = _discover_resources(
        token, subs, _RESOURCE_TYPES["container_app"], resource_name
    )
    for app in _select_resources(task, apps):
        try:
            detail = _arm_get(token, app["id"], "2024-03-01").get("properties", {}) or {}
            revs = (
                _arm_get(token, app["id"] + "/revisions", "2024-03-01").get("value", [])
                or []
            )
        except AzureApiError:
            continue
        revs.sort(
            key=lambda r: (r.get("properties", {}) or {}).get("createdTime") or "",
            reverse=True,
        )
        rev_lines = []
        for rev in revs[:8]:
            rp = rev.get("properties", {}) or {}
            containers = (rp.get("template", {}) or {}).get("containers", []) or []
            image = containers[0].get("image") if containers else "?"
            rev_lines.append(
                f"  - {rev.get('name')}: active={rp.get('active')} "
                f"health={rp.get('healthState')} provisioning={rp.get('provisioningState')} "
                f"running={rp.get('runningState')} replicas={rp.get('replicas')} "
                f"traffic={rp.get('trafficWeight')}% image={image}"
            )
        sections.append(
            f"Container app {app['name']} — provisioningState="
            f"{detail.get('provisioningState')}, runningStatus="
            f"{detail.get('runningStatus')}, latestRevision="
            f"{detail.get('latestRevisionName')}, latestReady="
            f"{detail.get('latestReadyRevisionName')}.\nRecent revisions:\n"
            + "\n".join(rev_lines)
        )

    # System / lifecycle events and any non-Normal (warning/error) events.
    cols, rows = _run_log_query(
        logs_token,
        workspace,
        f"ContainerAppSystemLogs_CL {app_filter} | summarize n=count() by Reason_s, "
        "Level | order by n desc | take 25",
        timespan,
    )
    sections.append("Container app system events (count by reason/level):\n" + _fmt_log_rows(cols, rows))

    cols, rows = _run_log_query(
        logs_token,
        workspace,
        f"ContainerAppSystemLogs_CL {app_filter} | where Level in "
        "('warning','error','critical') or Reason_s has_any "
        "('Fail','Error','Probe','Crash','Terminated','Unhealthy','OOM','BackOff',"
        "'Kill','Evict','Timeout') "
        "| project TimeGenerated, ContainerAppName_s, RevisionName_s, Level, "
        "Reason_s, Log_s | order by TimeGenerated desc | take 25",
        timespan,
    )
    sections.append(
        "Container app PROBLEM events (probe failures, restarts, scaling errors, "
        "crashes — the likely failure signal):\n" + _fmt_log_rows(cols, rows, limit=25)
    )

    # Application error / stderr console lines.
    cols, rows = _run_log_query(
        logs_token,
        workspace,
        f"ContainerAppConsoleLogs_CL {app_filter} | where Stream_s == 'stderr' "
        "or Log_s has 'Traceback' or Log_s has 'Exception' or Log_s has 'error' "
        "or Log_s has 'FATAL' or Log_s has 'panic' "
        "| project TimeGenerated, ContainerAppName_s, RevisionName_s, Log_s "
        "| order by TimeGenerated desc | take 40",
        timespan,
    )
    sections.append(
        "Recent application error / stderr log lines:\n" + _fmt_log_rows(cols, rows, limit=40)
    )

    # Postgres server errors when the user asks about the database.
    if any(k in task_lower for k in ("postgre", "postgres", "psql", "database", "db ")):
        cols, rows = _run_log_query(
            logs_token,
            workspace,
            "PGSQLServerLogs | where ErrorLevel in ('ERROR','FATAL','PANIC','WARNING') "
            "| project TimeGenerated, LogicalServerName, ErrorLevel, SqlErrorCode, "
            "Message | order by TimeGenerated desc | take 30",
            timespan,
        )
        sections.append(
            "PostgreSQL server errors/warnings:\n" + _fmt_log_rows(cols, rows, limit=30)
        )

    return {
        "text": "\n\n".join(sections),
        "meta": {
            "subscription": creds.subscription_id,
            "window": label,
            "workspace": workspace,
        },
    }


_RELATIONSHIP_QUERY = (
    "Resources "
    "| extend parent = tostring(properties.parent) "
    "| project name, type, resourceGroup, location, "
    "vnet=tostring(properties.virtualNetwork.id), "
    "subnet=tostring(properties.subnet.id), "
    "nsg=tostring(properties.networkSecurityGroup.id), "
    "identity=tostring(identity.type) "
    "| order by resourceGroup asc, type asc "
    "| limit 400"
)


def discover_topology(project_id: str, max_resources: int = 400) -> dict[str, Any]:
    """Return a structured Azure resource inventory with relationship fields.

    Used by the project context engine and existing-project analyzer. Read-only.
    """
    creds = load_credentials(project_id)
    token = _get_token(creds)
    if not token:
        raise AzureApiError("Azure returned an empty access token.")
    subs = [creds.subscription_id] if creds.subscription_id else []
    inventory = _run_query(token, subs, _RELATIONSHIP_QUERY)
    if max_resources:
        inventory = inventory[:max_resources]
    by_rg: dict[str, list[dict[str, Any]]] = {}
    edges: list[dict[str, str]] = []
    for row in inventory:
        rg = str(row.get("resourceGroup") or "unknown")
        by_rg.setdefault(rg, []).append(row)
        name = str(row.get("name") or "")
        for field, relation in (
            ("vnet", "uses_vnet"),
            ("subnet", "uses_subnet"),
            ("nsg", "uses_nsg"),
        ):
            target = str(row.get(field) or "").strip()
            if target and target.lower() not in {"", "null", "none"}:
                edges.append(
                    {
                        "from": f"{rg}/{name}",
                        "to": target.split("/")[-1],
                        "relation": relation,
                    }
                )
    return {
        "provider": "azure",
        "subscription": creds.subscription_id,
        "resource_count": len(inventory),
        "resource_groups": sorted(by_rg.keys()),
        "resources": inventory,
        "relationships": edges[:500],
        "text": (
            f"AZURE TOPOLOGY — subscription {creds.subscription_id or 'unknown'}; "
            f"{len(inventory)} resources across {len(by_rg)} resource groups; "
            f"{len(edges)} relationship edges.\n"
            + _format_rows(inventory, limit=min(max_resources, 120))
        ),
    }
