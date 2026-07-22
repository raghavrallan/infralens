"""Safe bridges from explicit chat intents to structured action jobs."""
import re
from typing import Any, Optional

from app import chat_memory, chats, connections
from app.execution import action_planner, service

_REGION_NAMES = {
    "australiaeast", "brazilsouth", "canadacentral", "centralindia", "centralus",
    "eastasia", "eastus", "eastus2", "francecentral", "germanywestcentral",
    "japaneast", "koreacentral", "northcentralus", "northeurope", "southafricanorth",
    "southcentralus", "southeastasia", "swedencentral", "switzerlandnorth",
    "uaenorth", "uksouth", "westeurope", "westus", "westus2", "westus3",
}
_RESOURCE_NAME_STOPWORDS = {"a", "an", "the", "with", "in", "inside", "within", "using", "default", "same"}
_CONFIRMATION = re.compile(r"^(yes|y|confirm(?:ed)?|approved?|approve|proceed|do it|execute|go ahead)\s*[.!]*$", re.IGNORECASE)


def provider_status(project_id: str, action_scope: str = "read_only") -> list[dict[str, Any]]:
    """Return secret-free, project-scoped provider status for chat and the UI.

    Whether an action is allowed is selected in the current chat request. It is
    deliberately not controlled by a process-wide environment flag: projects
    can have different credentials and users can choose read or write scope per
    request.
    """
    return [
        {
            "provider": item["provider"],
            "connected": bool(item.get("connected")),
            "identity": item.get("identity", ""),
            "action_scope": action_scope,
            "actions_available": bool(item.get("connected")),
        }
        for item in connections.all_status(project_id)
    ]


def provider_status_text(project_id: str, action_scope: str = "read_only") -> str:
    labels = {"azure": "Azure", "aws": "AWS", "github": "GitHub"}
    scope_label = "write actions enabled for this request" if action_scope == "write" else "read-only actions"
    lines = [f"PROJECT PROVIDER STATUS (secrets hidden; {scope_label}):"]
    for item in provider_status(project_id, action_scope):
        state = "connected" if item["connected"] else "not connected"
        identity = f"; identity {item['identity']}" if item.get("identity") else ""
        scope = ""
        if item["provider"] == "azure" and item["connected"]:
            fields = connections.get_secret_fields(project_id, "azure") or {}
            scope = "; subscription configured" if fields.get("subscription_id") else "; subscription not configured"
        availability = "actions available" if item["actions_available"] else "connect this provider in Settings"
        lines.append(f"- {labels.get(item['provider'], item['provider'])}: {state}{identity}{scope}; {availability}")
    return "\n".join(lines)


def _resource_group_request(message: str) -> Optional[dict[str, str]]:
    lowered = message.lower()
    # Compound provider requests must go through the general structured
    # planner; otherwise this shortcut would execute only the first clause.
    if any(term in lowered for term in ("vnet", "virtual network", "subnet")):
        return None
    if "resource group" not in lowered or not re.search(r"\b(create|make|provision|new)\b", lowered):
        return None
    # Bind the name to the resource-group phrase. A generic `name <value>`
    # match would mistake a child resource name (for example a VNet or NSG)
    # for the parent group when the request says "inside this resource group".
    name_match = re.search(
        r"\bresource\s+group\b.{0,80}?\b(?:named|name|called)\b\s*[:=]?\s*"
        r"[`\"']?([a-z0-9][a-z0-9._-]{0,89})",
        message,
        re.IGNORECASE,
    )
    if not name_match:
        name_match = re.search(
            r"\bresource\s+group\s+(?!in\b|and\b|with\b|called\b|named\b|name\b)"
            r"[`\"']?([a-z0-9][a-z0-9._-]{0,89})",
            message,
            re.IGNORECASE,
        )
    if not name_match:
        if re.search(r"\b(?:inside|within|under|in)\s+(?:this|the|same)\s+resource\s+group\b", lowered):
            return None
        return {"name": ""}
    region_match = re.search(r"(?:--location|\blocation|\bregion)\s*[:=]?\s*([a-z][a-z0-9-]{1,30})", message, re.IGNORECASE)
    location = ""
    if region_match and region_match.group(1).lower() in _REGION_NAMES:
        location = region_match.group(1).lower()
    if not location:
        location_candidates = re.findall(r"\b[a-z][a-z0-9-]{1,30}\b", lowered)
        location = next((candidate for candidate in location_candidates if candidate in _REGION_NAMES), "")
    return {"name": name_match.group(1), "location": location}


def _pending_action(chat_id: str) -> Optional[dict[str, Any]]:
    chat = chats.get_chat(chat_id)
    if not chat:
        return None
    for message in reversed(chat.get("messages", [])):
        meta = message.get("meta") or {}
        action_id = meta.get("action_id")
        if not action_id:
            continue
        try:
            action = service.get_action(str(action_id))
        except KeyError:
            return None
        return action if action.get("status") == "awaiting_approval" else None
    return None


def _latest_action(chat_id: str) -> Optional[dict[str, Any]]:
    chat = chats.get_chat(chat_id)
    if not chat:
        return None
    for message in reversed(chat.get("messages", [])):
        action_id = (message.get("meta") or {}).get("action_id")
        if action_id:
            try:
                return service.get_action(str(action_id))
            except KeyError:
                return None
    return None


def action_diagnostic_context(chat_id: str, message: str = "") -> str:
    """Return redacted action/queue context only for diagnostic questions.

    An old queued action must not become hidden prompt context for an unrelated
    request. That made the assistant repeat the previous CLI operation instead
    of handling the new user message.
    """
    if message and not _asks_for_action_diagnostics(message):
        return ""
    action = _latest_action(chat_id)
    if not action or action.get("status") not in {"queued", "running"}:
        return ""
    diagnostic = service.diagnose_action(action["id"])
    events = service.list_events(action["id"])[-8:]
    lines = [
        "CURRENT PROVIDER ACTION DIAGNOSTICS (redacted; treat as operational evidence):",
        f"- Action: {action['id']} ({action.get('provider')})",
        f"- Status: {action.get('status')}; queue: {diagnostic.get('queue')}; age_seconds: {diagnostic.get('age_seconds')}",
        f"- Executor available: {diagnostic.get('executor_available')}; queue depth: {diagnostic.get('queue_depth')}",
        f"- Diagnostic: {diagnostic.get('message')}",
        f"- Recommendation: {diagnostic.get('recommendation')}",
        "- Recent event logs:",
    ]
    for event in events:
        payload = event.get("payload") or {}
        detail = payload.get("message") or payload.get("phase") or payload.get("status") or event.get("type")
        lines.append(f"  {event.get('created_at', '')}: {detail}")
    return "\n".join(lines)


def _asks_for_action_diagnostics(message: str) -> bool:
    lowered = message.lower()
    return any(term in lowered for term in ("stuck", "status", "progress", "logs", "log", "queued", "why", "what is running"))


def _pending_resource_group_name(chat_id: str) -> str:
    chat = chats.get_chat(chat_id)
    if not chat:
        return ""
    for message in reversed(chat.get("messages", [])):
        meta = message.get("meta") or {}
        if meta.get("pending_resource_group_name"):
            return str(meta["pending_resource_group_name"])
    # Recover the old text-only approval proposal once, so existing chats do
    # not lose the user's intended resource-group name after the migration.
    for message in reversed(chat.get("messages", [])):
        if message.get("role") != "assistant":
            continue
        match = re.search(
            r"az\s+group\s+(?:create|delete|show|exists)\s+--name\s+"
            r"([a-z0-9][a-z0-9._-]{0,89})",
            message.get("content", ""),
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
    return ""


def _pending_action_spec(chat_id: str) -> Optional[dict[str, Any]]:
    chat = chats.get_chat(chat_id)
    if not chat:
        return None
    for message in reversed(chat.get("messages", [])):
        spec = (message.get("meta") or {}).get("pending_action_spec")
        if isinstance(spec, dict):
            return spec
    return None


def _context_resource_group(chat_id: str) -> Optional[dict[str, str]]:
    """Recover a resource-group target from earlier turns in this chat."""
    name = _pending_resource_group_name(chat_id)
    chat = chats.get_chat(chat_id) or {}
    messages = chat.get("messages", [])
    content = "\n".join(str(item.get("content", "")) for item in messages)
    if not name:
        # Parse turns independently. A later child-resource turn may contain
        # the words "resource group" and must not suppress the earlier parent
        # group turn by triggering the compound-resource guard.
        for item in messages:
            recovered = _resource_group_request(str(item.get("content", "")))
            if recovered and recovered.get("name"):
                name = recovered["name"]
    if not name:
        return None
    candidates = re.findall(r"\b[a-z][a-z0-9-]{1,30}\b", content.lower())
    location = next((candidate for candidate in candidates if candidate in _REGION_NAMES), "")
    return {"name": name, "location": location} if location else {"name": name, "location": ""}


def _chat_mentions_nsg(chat_id: str) -> bool:
    chat = chats.get_chat(chat_id) or {}
    return "nsg" in "\n".join(
        str(item.get("content", "")) for item in chat.get("messages", [])
    ).lower() or "network security group" in "\n".join(
        str(item.get("content", "")) for item in chat.get("messages", [])
    ).lower()


def _context_nsg_name(chat_id: str) -> str:
    chat = chats.get_chat(chat_id) or {}
    content = "\n".join(str(item.get("content", "")) for item in chat.get("messages", []))
    suffix_match = re.findall(r"\b([a-z0-9][a-z0-9._-]{1,89}-nsg)\b", content.lower())
    if suffix_match:
        return suffix_match[-1]
    for line in reversed(content.splitlines()):
        match = re.search(
            r"(?:nsg|network\s+security\s+group)\s+(?:named|name|called)\s+"
            r"[`\"']?([a-z0-9][a-z0-9._-]{1,89})",
            line,
            re.IGNORECASE,
        )
        if match and match.group(1).lower() not in {"also", "in", "the", "same"}:
            return match.group(1)
    return ""


def _message_mentions_nsg(message: str) -> bool:
    lowered = message.lower()
    return (
        "nsg" in lowered
        or "network security group" in lowered
        or bool(re.fullmatch(r"\s*[a-z0-9][a-z0-9._-]{1,89}-nsg\s*", lowered))
    )


def _vnet_request(message: str) -> Optional[dict[str, str]]:
    """Extract a VNet request without guessing network address ranges."""
    lowered = message.lower()
    if not any(term in lowered for term in ("vnet", "virtual network")):
        return None
    name_match = re.search(
        r"(?:vnet|virtual\s+network)\s+(?:named|name|called)?\s*[:=]?\s*[`\"']?"
        r"([a-z0-9][a-z0-9._-]{1,79})",
        message,
        re.IGNORECASE,
    )
    name = name_match.group(1) if name_match else ""
    if name.lower() in _RESOURCE_NAME_STOPWORDS:
        name = ""
    prefixes = re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}/\d{1,2}\b", message)
    return {
        "name": name,
        "address_prefix": prefixes[0] if prefixes else "",
        "subnet_prefix": prefixes[1] if len(prefixes) > 1 else "",
    }


def _context_vnet_name(chat_id: str) -> str:
    """Recover the latest VNet name when a follow-up only supplies ranges."""
    chat = chats.get_chat(chat_id) or {}
    content = "\n".join(str(item.get("content", "")) for item in chat.get("messages", []))
    matches = re.findall(
        r"(?:vnet|virtual\s+network)\s+(?:named|name|called)?\s*[:=]?\s*[`\"']?"
        r"([a-z0-9][a-z0-9._-]{1,79})",
        content,
        re.IGNORECASE,
    )
    for match in reversed(matches):
        if match.lower() not in _RESOURCE_NAME_STOPWORDS:
            return match
    return ""


def _pending_action_reference(message: str, action: dict[str, Any]) -> bool:
    """Return true only for a direct reference to the pending action.

    A new request such as "create a VNet inside this resource group" must not
    be treated as approval for an earlier resource-group action. The pending
    action is reusable for an exact target or a short pronoun-only command.
    """
    lowered = " ".join((message or "").lower().split())
    target = str(action.get("target") or "").lower().rstrip("/")
    target_name = target.rsplit("/", 1)[-1] if target else ""
    if target_name and re.search(rf"(?<![a-z0-9._-]){re.escape(target_name)}(?![a-z0-9._-])", lowered):
        return True
    return bool(
        re.fullmatch(
            r"(?:please\s+)?(?:create|deploy|provision|apply|update|run|execute|approve|confirm|delete|remove|destroy)\s+"
            r"(?:this|it|that|the same)(?:\s+(?:now|again))?[.!]*",
            lowered,
        )
    )


def _is_compound_request(message: str) -> bool:
    """Keep multi-resource requests on the ordered structured planner path."""
    lowered = f" {(message or '').lower()} "
    return any(marker in lowered for marker in (" and ", " also ", " with "))


def _region_from_message(message: str) -> str:
    lowered = message.lower()
    candidates = re.findall(r"\b[a-z][a-z0-9-]{1,30}\b", lowered)
    return next((candidate for candidate in candidates if candidate in _REGION_NAMES), "")


def _resource_group_spec(name: str, location: str, subscription: str) -> dict[str, Any]:
    return {
        "project_id": "",
        "provider": "azure",
        "executable": "az",
        "args": ["group", "create", "--name", name, "--location", location, "--output", "json"],
        "target": f"subscription/{subscription}/resource-group/{name}",
        "access_scope": "write",
        "expected_result": f"Resource group {name} exists in {location}.",
        "risk": "Creates one Azure resource group. No resources are created inside it.",
        "rollback": "Delete the resource group only after explicit review; deletion is not automated.",
        "preflight": [
            "group", "list", "--query", f"[?name=='{name}'].name", "--output", "tsv"
        ],
        "preflight_expect": "__absent__",
        "verify": ["group", "show", "--name", name, "--output", "json"],
        "requested_by": "chat",
    }


def _resource_group_delete_spec(name: str, subscription: str) -> dict[str, Any]:
    """Build a safe delete operation from a resolved chat target."""
    return {
        "project_id": "",
        "provider": "azure",
        "executable": "az",
        "args": ["group", "delete", "--name", name, "--yes"],
        "target": f"subscription/{subscription}/resource-group/{name}",
        "access_scope": "write",
        "expected_result": f"Resource group deletion for {name} is complete.",
        "risk": "Deletes the Azure resource group and all resources inside it.",
        "rollback": "No automatic rollback; recovery requires restoring or recreating resources.",
        "preflight": ["group", "show", "--name", name, "--output", "json"],
        "preflight_expect": "",
        "verify": ["group", "show", "--name", name, "--output", "json"],
        "requested_by": "chat",
    }


def _resource_group_nsg_spec(
    resource_group: str, location: str, nsg_name: str, subscription: str
) -> dict[str, Any]:
    """Create an ordered parent-resource plus NSG operation."""
    group_target = f"subscription/{subscription}/resource-group/{resource_group}"
    return {
        "project_id": "",
        "provider": "azure",
        "executable": "az",
        "args": ["group", "create", "--name", resource_group, "--location", location, "--output", "json"],
        "target": group_target,
        "access_scope": "write",
        "expected_result": f"Resource group {resource_group} exists, then NSG {nsg_name} exists in {location}.",
        "risk": "Creates an Azure resource group and a network security group inside it.",
        "rollback": "No automatic rollback; review and remove each resource explicitly if needed.",
        "preflight": [
            "group", "list", "--query", f"[?name=='{resource_group}'].name", "--output", "tsv"
        ],
        "preflight_expect": "__absent__",
        "verify": ["group", "show", "--name", resource_group, "--output", "json"],
        "requested_by": "chat",
        "steps": [
            {
                "provider": "azure",
                "executable": "az",
                "args": ["group", "create", "--name", resource_group, "--location", location, "--output", "json"],
                "target": group_target,
                "access_scope": "write",
                "expected_result": f"Resource group {resource_group} exists in {location}.",
                "risk": "Creates one Azure resource group.",
                "rollback": "No automatic rollback.",
                "preflight": [
                    "group", "list", "--query", f"[?name=='{resource_group}'].name", "--output", "tsv"
                ],
                "preflight_expect": "__absent__",
                "skip_if_exists": True,
                "verify": ["group", "show", "--name", resource_group, "--output", "json"],
            },
            {
                "provider": "azure",
                "executable": "az",
                "args": [
                    "network", "nsg", "create", "--resource-group", resource_group,
                    "--name", nsg_name, "--location", location, "--output", "json",
                ],
                "target": f"{group_target}/network-security-group/{nsg_name}",
                "access_scope": "write",
                "expected_result": f"NSG {nsg_name} exists in resource group {resource_group}.",
                "risk": "Creates an empty Azure network security group; no rules are added.",
                "rollback": "No automatic rollback.",
                "preflight": [
                    "network", "nsg", "list", "--resource-group", resource_group,
                    "--query", f"[?name=='{nsg_name}'] | length(@)", "--output", "tsv",
                ],
                "preflight_expect": "0",
                "skip_if_exists": True,
                "verify": [
                    "network", "nsg", "show", "--resource-group", resource_group,
                    "--name", nsg_name, "--output", "json",
                ],
            },
        ],
    }


def _resource_group_vnet_spec(
    resource_group: str,
    location: str,
    vnet_name: str,
    address_prefix: str,
    subnet_prefix: str,
    subscription: str,
) -> dict[str, Any]:
    """Create an ordered resource-group plus VNet/default-subnet operation."""
    group_target = f"subscription/{subscription}/resource-group/{resource_group}"
    vnet_target = f"{group_target}/virtual-network/{vnet_name}"
    return {
        "project_id": "",
        "provider": "azure",
        "executable": "az",
        "args": [
            "network", "vnet", "create", "--resource-group", resource_group,
            "--name", vnet_name, "--location", location,
            "--address-prefixes", address_prefix, "--subnet-name", "default",
            "--subnet-prefixes", subnet_prefix, "--output", "json",
        ],
        "target": vnet_target,
        "access_scope": "write",
        "expected_result": f"Resource group {resource_group} exists, then VNet {vnet_name} with default subnet exists in {location}.",
        "risk": "Creates an Azure virtual network and default subnet inside the resource group; no public endpoints or NSG rules are added.",
        "rollback": "No automatic rollback; delete the VNet only after explicit review.",
        "preflight": [
            "network", "vnet", "list", "--resource-group", resource_group,
            "--query", f"[?name=='{vnet_name}'].name", "--output", "tsv",
        ],
        "preflight_expect": "__absent__",
        "verify": [
            "network", "vnet", "show", "--resource-group", resource_group,
            "--name", vnet_name, "--output", "json",
        ],
        "requested_by": "chat",
        "steps": [
            {
                "provider": "azure",
                "executable": "az",
                "args": ["group", "create", "--name", resource_group, "--location", location, "--output", "json"],
                "target": group_target,
                "access_scope": "write",
                "expected_result": f"Resource group {resource_group} exists in {location}.",
                "risk": "Creates one Azure resource group.",
                "rollback": "No automatic rollback.",
                "preflight": [
                    "group", "list", "--query", f"[?name=='{resource_group}'].name", "--output", "tsv"
                ],
                "preflight_expect": "__absent__",
                "skip_if_exists": True,
                "verify": ["group", "show", "--name", resource_group, "--output", "json"],
            },
            {
                "provider": "azure",
                "executable": "az",
                "args": [
                    "network", "vnet", "create", "--resource-group", resource_group,
                    "--name", vnet_name, "--location", location,
                    "--address-prefixes", address_prefix, "--subnet-name", "default",
                    "--subnet-prefixes", subnet_prefix, "--output", "json",
                ],
                "target": vnet_target,
                "access_scope": "write",
                "expected_result": f"VNet {vnet_name} with default subnet exists in resource group {resource_group}.",
                "risk": "Creates a virtual network and default subnet; no public endpoints or NSG rules are added.",
                "rollback": "No automatic rollback.",
                "preflight": [
                    "network", "vnet", "list", "--resource-group", resource_group,
                    "--query", f"[?name=='{vnet_name}'].name", "--output", "tsv",
                ],
                "preflight_expect": "__absent__",
                "skip_if_exists": True,
                "verify": [
                    "network", "vnet", "show", "--resource-group", resource_group,
                    "--name", vnet_name, "--output", "json",
                ],
            },
        ],
    }


def _pending_confirmation(message: str, action: dict[str, Any]) -> bool:
    """Resolve natural confirmations against the already reviewed action."""
    lowered = message.strip().lower()
    if _CONFIRMATION.fullmatch(lowered):
        return True
    if not _pending_action_reference(message, action):
        return False
    operation = action.get("operation") or {}
    command = " ".join(str(item) for item in operation.get("args", [])).lower()
    if "delete" in command:
        verb = "delete" in lowered or "remove" in lowered
    else:
        verb = any(term in lowered for term in ("create", "deploy", "apply", "update", "provision", "run"))
    if not verb:
        return False
    target = str(action.get("target") or "").lower()
    target_name = target.rsplit("/", 1)[-1] if target else ""
    return "this" in lowered or "it" in lowered or (target_name and target_name in lowered)


def _delete_requested(message: str) -> bool:
    lowered = message.lower()
    return any(term in lowered for term in ("delete", "remove", "destroy"))


def _compound_network_request(message: str) -> bool:
    lowered = message.lower()
    return "resource group" in lowered and any(
        term in lowered for term in ("vnet", "virtual network", "subnet")
    )


def _contains_vnet_operation(operation: dict[str, Any]) -> bool:
    parts = [operation]
    parts.extend(item for item in operation.get("steps", []) if isinstance(item, dict))
    text = " ".join(
        str(arg) for item in parts for arg in item.get("args", [])
    ).lower()
    return "vnet" in text or "virtual-network" in text


def _contains_resource_group_operation(operation: dict[str, Any]) -> bool:
    parts = [operation]
    parts.extend(item for item in operation.get("steps", []) if isinstance(item, dict))
    text = " ".join(
        str(arg) for item in parts for arg in item.get("args", [])
    ).lower()
    return "group" in text and ("create" in text or "show" in text or "exists" in text)


def _spec_for_project(spec: dict[str, Any], project_id: str, access_level: str = "ask_approval") -> dict[str, Any]:
    clean = {
        key: spec.get(key)
        for key in {
            "provider", "executable", "args", "target", "access_scope",
            "expected_result", "risk", "rollback", "preflight",
            "preflight_expect", "verify", "requested_by", "access_level", "steps",
        }
    }
    clean["project_id"] = project_id
    clean["access_level"] = access_level
    clean["requested_by"] = str(clean.get("requested_by") or "chat")[:120]
    clean["args"] = [str(item) for item in clean.get("args", [])]
    clean["preflight"] = [str(item) for item in clean.get("preflight", [])]
    clean["verify"] = [str(item) for item in clean.get("verify", [])]
    clean["preflight_expect"] = str(clean.get("preflight_expect") or "")
    if isinstance(clean.get("steps"), list):
        clean["steps"] = [item for item in clean["steps"] if isinstance(item, dict)][:16]
    else:
        clean["steps"] = []
    return clean


def _scope_required_reply(
    spec: dict[str, Any], project_id: str, action_scope: str, access_level: str, intro: str
) -> dict[str, Any]:
    preview = " ".join([spec["executable"], *spec["args"]])
    return {
        "reply": (
            f"{intro}\n\nExact command preview:\n`{preview}`\n\n"
            "This is a write action. I have kept it as a pending preview; "
            "the UI will enable Write actions for this project. Full access "
            "will use a two-step danger confirmation modal; normal access will "
            "use the single Approve action control.\n\n"
            + provider_status_text(project_id, action_scope)
        ),
        "action": None,
        "pending_action_spec": spec,
        "required_action_scope": "write",
    }


def _create_or_hold_action(
    spec: dict[str, Any], project_id: str, action_scope: str, intro: str,
    access_level: str = "ask_approval",
) -> dict[str, Any]:
    required = ("provider", "executable", "args", "target", "access_scope")
    missing = [key for key in required if not spec.get(key)]
    if missing:
        return {
            "reply": f"I understood the deployment request, but I still need: {', '.join(missing)}.",
            "action": None,
            "required_action_scope": "write" if spec.get("access_scope") == "write" else None,
        }
    spec = _spec_for_project(spec, project_id, access_level)
    if spec.get("access_scope") == "write" and action_scope != "write":
        return _scope_required_reply(spec, project_id, action_scope, access_level, intro)
    try:
        action = service.create_action(**spec)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "reply": f"I understood the request but could not prepare a safe provider action: {exc}\n\n{provider_status_text(project_id, action_scope)}",
            "action": None,
        }
    if action["access_scope"] == "read_only":
        return {
            "reply": (
                f"{intro}\n\nThe read-only CLI action has been queued:\n"
                f"`{action['command_preview']}`\n\n{provider_status_text(project_id, action_scope)}"
            ),
            "action": action,
            "event_type": "action_queued",
        }
    if access_level == "full_access":
        reply = (
            f"{intro}\n\nExact command:\n`{action['command_preview']}`\n\n"
            "This full-access action is ready in the danger confirmation modal. "
            "The chat will not request approval in text.\n\n"
        )
    else:
        reply = (
            f"{intro}\n\nExact command:\n`{action['command_preview']}`\n\n"
            "Use the Approve action button in the action panel, or reply `yes`.\n\n"
        )
    return {
        "reply": reply + provider_status_text(project_id, action_scope),
        "action": action,
        "event_type": "approval_required" if action["status"] == "awaiting_approval" else "action_queued",
    }


def _missing_location_reply(name: str, project_id: str, action_scope: str = "read_only", access_level: str = "ask_approval") -> dict[str, Any]:
    return {
        "reply": (
            f"I can prepare the Azure resource-group action for `{name or 'the requested name'}`, "
            "but Azure requires a location. Tell me the region, for example `eastus`, "
            "and I will show the exact command for the action confirmation.\n\n" + provider_status_text(project_id, action_scope)
        ),
        "action": None,
        "pending_resource_group_name": name,
        "required_action_scope": "write",
    }


def handle_turn(
    chat_id: str, project_id: str, message: str, action_scope: str,
    access_level: str = "ask_approval",
) -> Optional[dict[str, Any]]:
    """Handle supported explicit action intents; return None for normal chat."""
    pending = _pending_action(chat_id)
    if pending and _pending_confirmation(message, pending):
        if pending.get("access_level") == "full_access":
            return {
                "reply": "This full-access action is ready for the danger confirmation modal. Review the exact command and confirm it there.",
                "action": pending,
                "event_type": "approval_required",
            }
        try:
            action = service.approve_action(pending["id"], "user")
            return {
                "reply": f"Approval recorded for `{action['command_preview']}`. The Azure CLI action has been queued for this project.\n\n{provider_status_text(project_id, action_scope)}",
                "action": action,
                "event_type": "action_queued",
            }
        except ValueError as exc:
            return {"reply": f"I could not approve this action: {exc}", "action": pending, "event_type": "action_failed"}
        except Exception as exc:  # noqa: BLE001 - surface queue/control-plane failures in chat
            return {
                "reply": f"Approval was recorded, but the provider action could not be queued: {exc}",
                "action": pending,
                "event_type": "action_failed",
            }

    active = _latest_action(chat_id)
    if active and active.get("status") in {"queued", "running"}:
        diagnostic_text = action_diagnostic_context(chat_id)
        if _asks_for_action_diagnostics(message):
            return {
                "reply": f"Here is the current execution diagnosis for `{active['command_preview']}`:\n\n{diagnostic_text}\n\nI will not start a second copy while this action exists. Use Stop action to cancel it, or start the provider executor and ask me to check again.",
                "action": active,
                "event_type": "action_diagnostic",
            }

    if pending and _pending_action_reference(message, pending):
        return {
            "reply": (
                f"This deployment action is already prepared and is awaiting approval:\n"
                f"`{pending['command_preview']}`\n\nReply `yes` to approve it, or reject it before preparing a different action."
            ),
            "action": pending,
            "event_type": "approval_required",
        }

    if _CONFIRMATION.fullmatch(message.strip()) and not pending:
        spec = _pending_action_spec(chat_id)
        if spec:
            return _create_or_hold_action(spec, project_id, action_scope, "I recovered the pending deployment request from this conversation.", access_level)
        context_group = _context_resource_group(chat_id)
        if context_group and context_group.get("location"):
            fields = connections.get_secret_fields(project_id, "azure") or {}
            subscription = str(fields.get("subscription_id", ""))
            if subscription:
                spec = _resource_group_spec(context_group["name"], context_group["location"], subscription)
                return _create_or_hold_action(spec, project_id, action_scope, f"I recovered the Azure resource-group request for `{context_group['name']}` in `{context_group['location']}`.", access_level)
        legacy_name = _pending_resource_group_name(chat_id)
        if legacy_name:
            return _missing_location_reply(legacy_name, project_id, action_scope, access_level)

    request = _resource_group_request(message)
    pending_name = _pending_resource_group_name(chat_id)
    if request is None and pending_name:
        location = _region_from_message(message)
        if location:
            request = {"name": pending_name, "location": location}
    context_group = _context_resource_group(chat_id)
    vnet = _vnet_request(message)
    if vnet:
        if not vnet.get("name"):
            vnet["name"] = _context_vnet_name(chat_id)
        if not vnet.get("name"):
            return {
                "reply": "I found the Azure VNet request, but I need the VNet name before I can prepare it.",
                "action": None,
                "required_action_scope": "write",
            }
        if not context_group or not context_group.get("name"):
            return {
                "reply": f"I have the VNet name `{vnet['name']}`, but I need the target resource group name.",
                "action": None,
                "required_action_scope": "write",
            }
        if not context_group.get("location"):
            return {
                "reply": f"I have the VNet `{vnet['name']}` and resource group `{context_group['name']}`, but I still need the Azure region.",
                "action": None,
                "required_action_scope": "write",
            }
        if not vnet.get("address_prefix") or not vnet.get("subnet_prefix"):
            return {
                "reply": (
                    f"I resolved VNet `{vnet['name']}` in resource group `{context_group['name']}` "
                    f"and region `{context_group['location']}`. Tell me the VNet address space and "
                    "default subnet prefix, for example `10.0.0.0/16` and `10.0.0.0/24`; I will "
                    "then create the parent group first if needed, followed by the VNet and `default` subnet."
                ),
                "action": None,
                "required_action_scope": "write",
            }
        fields = connections.get_secret_fields(project_id, "azure") or {}
        subscription = str(fields.get("subscription_id", "")).strip()
        if not subscription:
            return {
                "reply": "Azure is connected, but this project has no subscription ID configured. Add the subscription ID in Settings before creating the VNet.\n\n" + provider_status_text(project_id, action_scope),
                "action": None,
            }
        spec = _resource_group_vnet_spec(
            context_group["name"],
            context_group["location"],
            vnet["name"],
            vnet["address_prefix"],
            vnet["subnet_prefix"],
            subscription,
        )
        intro = (
            f"I prepared the ordered Azure changes: ensure resource group `{context_group['name']}` "
            f"exists, then create VNet `{vnet['name']}` with the `default` subnet."
        )
        if action_scope != "write":
            return _scope_required_reply(spec, project_id, action_scope, access_level, intro)
        return _create_or_hold_action(spec, project_id, action_scope, intro, access_level)
    if _message_mentions_nsg(message):
        # A compound request must remain ordered: create the parent resource
        # group first, then create the child NSG in that same scope.
        nsg_name = _context_nsg_name(chat_id)
        if context_group and context_group.get("location") and nsg_name:
            fields = connections.get_secret_fields(project_id, "azure") or {}
            subscription = str(fields.get("subscription_id", ""))
            if subscription:
                spec = _resource_group_nsg_spec(
                    context_group["name"],
                    context_group["location"],
                    nsg_name,
                    subscription,
                )
                reply = (
                    f"I prepared the ordered Azure changes: create resource group "
                    f"`{context_group['name']}` in `{context_group['location']}`, "
                    f"then create NSG `{nsg_name}` in that resource group."
                )
                if action_scope != "write":
                    return _scope_required_reply(spec, project_id, action_scope, access_level, reply)
                return _create_or_hold_action(spec, project_id, action_scope, reply, access_level)
        if context_group and not nsg_name:
            return {
                "reply": (
                    f"I have the Azure resource group `{context_group['name']}`"
                    + (f" in `{context_group['location']}`" if context_group.get("location") else "")
                    + ". What should the network security group be named?"
                ),
                "action": None,
                "required_action_scope": "write",
            }
    if request is None and _delete_requested(message) and context_group:
        fields = connections.get_secret_fields(project_id, "azure") or {}
        subscription = str(fields.get("subscription_id", ""))
        if subscription:
            spec = _resource_group_delete_spec(context_group["name"], subscription)
            return _create_or_hold_action(
                spec,
                project_id,
                action_scope,
                f"I resolved the Azure resource-group target `{context_group['name']}` from this conversation.",
                access_level,
            )
    # A complete, single resource-group request is deterministic. Do not send
    # it through the generic LLM planner, which may ask for a subscription even
    # though the project-scoped Azure connection already contains one.
    if request and request.get("name") and request.get("location") and not _is_compound_request(message):
        fields = connections.get_secret_fields(project_id, "azure") or {}
        subscription = str(fields.get("subscription_id", "")).strip()
        if not subscription:
            return {
                "reply": "Azure is connected, but this project has no subscription ID configured. Add the subscription ID in Settings before creating a resource group.\n\n" + provider_status_text(project_id, action_scope),
                "action": None,
            }
        spec = _resource_group_spec(request["name"], request["location"], subscription)
        intro = f"I prepared the Azure resource-group action for `{request['name']}` in `{request['location']}`."
        if action_scope != "write":
            return _scope_required_reply(spec, project_id, action_scope, access_level, intro)
        return _create_or_hold_action(spec, project_id, action_scope, intro, access_level)

    history = chat_memory.get_model_context(
        chat_id, message, project_id=project_id
    )
    provider_context = provider_status_text(project_id, action_scope)
    if pending:
        provider_context += (
            "\n\nPENDING ACTION CONTEXT (historical; do not repeat it for a new request):\n"
            f"- Target: {pending.get('target', '')}\n"
            f"- Command: {pending.get('command_preview', '')}\n"
            "- Reuse this action only when the current user message is an explicit confirmation "
            "or a pronoun-only reference such as `create it`."
        )
    diagnostic_context = action_diagnostic_context(chat_id, message)
    if diagnostic_context:
        provider_context += "\n\n" + diagnostic_context
    planned = action_planner.plan_action(message, history, provider_context)
    if planned is not None and planned.get("kind") != "none":
        operation = planned.get("operation") or {}
        planned_operations = [
            item for item in planned.get("operations", []) if isinstance(item, dict)
        ]
        if len(planned_operations) > 1:
            providers = {str(item.get("provider") or "") for item in planned_operations}
            executables = {str(item.get("executable") or "") for item in planned_operations}
            scopes = {str(item.get("access_scope") or "") for item in planned_operations}
            if len(providers) != 1 or len(executables) != 1 or len(scopes) != 1:
                return {
                    "reply": "I understood multiple provider changes, but they must be approved as separate provider actions. Tell me which provider operation should run first.",
                    "action": None,
                    "required_action_scope": "write" if "write" in scopes else None,
                }
            operation = dict(planned_operations[0])
            operation["steps"] = planned_operations
            operation["expected_result"] = " Then ".join(
                str(item.get("expected_result") or "")
                for item in planned_operations
                if item.get("expected_result")
            )[:1000]
            operation["risk"] = " Multiple ordered provider changes: " + "; ".join(
                str(item.get("risk") or "")
                for item in planned_operations
                if item.get("risk")
            )[:1000]
        if (
            planned.get("kind") == "action"
            and _compound_network_request(message)
            and (
                not _contains_vnet_operation(operation)
                or not _contains_resource_group_operation(operation)
            )
        ):
            return {
                "reply": (
                    "I understood the resource-group and VNet request, but I will not "
                    "execute only the resource group. Tell me the VNet name and address "
                    "space, for example `testing-vnet` and `10.0.0.0/16`; the default "
                    "subnet can then be created in the same region."
                ),
                "action": None,
                "required_action_scope": "write",
            }
        if planned.get("kind") == "clarification":
            required_scope = "write" if operation.get("access_scope") == "write" or action_planner.looks_like_action(message, history) else None
            return {
                "reply": planned.get("question") or "I understand this as a provider action. Tell me the target resource and artifact so I can prepare the exact CLI operation.",
                "action": None,
                **({"required_action_scope": required_scope} if required_scope else {}),
            }
        return _create_or_hold_action(operation, project_id, action_scope, "I understood this as a provider action and prepared a structured CLI operation.", access_level)
    if request is None:
        return None
    if not request.get("name"):
        return {"reply": "Tell me the resource group name and Azure location, for example: `Create resource group testing in eastus`."}
    if not request.get("location"):
        return _missing_location_reply(request["name"], project_id, action_scope, access_level)

    fields = connections.get_secret_fields(project_id, "azure") or {}
    subscription = str(fields.get("subscription_id", ""))
    if not subscription:
        return {
            "reply": "Azure is connected, but this project has no subscription ID configured. Add the subscription ID in Settings before creating a resource group.\n\n" + provider_status_text(project_id, action_scope),
            "action": None,
        }

    name = request["name"]
    location = request["location"]
    if action_scope != "write":
        return _scope_required_reply(
            _resource_group_spec(name, location, subscription),
            project_id,
            action_scope,
            access_level,
            f"I understood the Azure resource-group request for `{name}` in `{location}`.",
        )
    return _create_or_hold_action(
        _resource_group_spec(name, location, subscription),
        project_id,
        action_scope,
        f"I prepared the Azure resource-group action for `{name}` in `{location}`.",
        access_level,
    )
