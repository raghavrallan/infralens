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
from datetime import date
from typing import Any, Optional

import httpx

from app import connections

_AUTHORITY = "https://login.microsoftonline.com"
_ARM = "https://management.azure.com"
_SCOPE = "https://management.azure.com/.default"
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


def _get_token(creds: AzureCredentials) -> str:
    url = f"{_AUTHORITY}/{creds.tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scope": _SCOPE,
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


def _cost_payload(from_date: date, to_date: date) -> dict[str, Any]:
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
            "grouping": [{"type": "Dimension", "name": "ServiceName"}],
        },
    }


def build_cost_report(
    project_id: str, from_date: date, to_date: date, label: str
) -> dict[str, Any]:
    """Fetch real Azure spend for a period, grouped by service.

    Uses the Cost Management query API on the connection's subscription. Returns
    a dict with a formatted ``text`` block plus structured ``meta``. Raises
    AzureConnectionError / AzureApiError so the caller can surface a precise
    message rather than asking the user to paste an invoice.
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
            url, headers=headers, json=_cost_payload(from_date, to_date), timeout=_TIMEOUT
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
    currency_idx = columns.index("Currency") if "Currency" in columns else None

    lines: list[dict[str, Any]] = []
    total = 0.0
    currency = "USD"
    for row in rows:
        amount = float(row[cost_idx]) if row[cost_idx] is not None else 0.0
        total += amount
        if currency_idx is not None and row[currency_idx]:
            currency = row[currency_idx]
        lines.append(
            {
                "service": row[service_idx] if service_idx is not None else "(unknown)",
                "cost": round(amount, 2),
            }
        )
    lines.sort(key=lambda item: item["cost"], reverse=True)

    sections = [
        f"Azure spend for {label} (subscription {creds.subscription_id}), "
        f"actual cost from {from_date.isoformat()} to {to_date.isoformat()}.",
        f"Total: {round(total, 2)} {currency}",
    ]
    if lines:
        breakdown = "\n".join(
            f"- {item['service']}: {item['cost']} {currency}" for item in lines
        )
        sections.append("Cost by service:\n" + breakdown)
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
            "services": len(lines),
        },
    }
