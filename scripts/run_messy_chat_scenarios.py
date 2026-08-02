"""Multi-turn messy/typo chats to stress scope-loop and routing."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

BASE = "http://127.0.0.1:8000"
PROJECT_ID = "5310f26d-911a-47f6-b7ab-4376d8ab78bd"
USERNAME = "admin"
PASSWORD = "infralens"
TIMEOUT_S = 240.0

SCOPE_BUG_RE = re.compile(
    r"which (github )?(repo|repository|repos)|which azure scope|"
    r"subscription,? resource group|resource group,? or specific|"
    r"tell me (the |which )?(repo|repository|subscription|scope)",
    re.IGNORECASE,
)
TF_HIJACK_RE = re.compile(
    r"I (can prepare|prepared) Terraform|write actions are not enabled|"
    r"Switch the chat to Write",
    re.IGNORECASE,
)

# Each thread is one chat with multiple confusing turns.
THREADS: list[dict[str, Any]] = [
    {
        "id": "M01",
        "title": "Drift + posture, slang follow-ups",
        "turns": [
            "hey can u look at our azur stuff vs whats in githb? feels like things drifted idk",
            "also any public exposur / risky open stuff?",
            "evrything bro just check all of it",
            "same for the code too not just cloud",
        ],
    },
    {
        "id": "M02",
        "title": "Metrics then vague scope",
        "turns": [
            "hows the apps doing lately cpu mem whatever",
            "container app",
            "all of them",
            "ok what about errors / 5xx too?",
        ],
    },
    {
        "id": "M03",
        "title": "Pipelines + cost topic-switch",
        "turns": [
            "our ci cd looks sketchy can u audit pipelines",
            "wait also are we burning money on azure rn?",
            "and are dependabot / vulns even on?",
            "pls just summarise the worst 5 things",
        ],
    },
    {
        "id": "M04",
        "title": "IaC review with typos + confusing 'tf'",
        "turns": [
            "reviw the terrafom / bicep / dockerfiles if we even have them",
            "if theres no tf then just say whats missing in iac",
            "dont apply anything just tell me",
            "ok now compare that to live azur inventry",
        ],
    },
    {
        "id": "M05",
        "title": "Project dump then random asks",
        "turns": [
            "whats even in this eqip project bro repos apps etc",
            "which one is backend vs frontend?",
            "any hardning gaps on github branches?",
            "cool write a short exec report of all that",
        ],
    },
    {
        "id": "M06",
        "title": "Incident / unhealthy confusion",
        "turns": [
            "i think one of the container apps is acting weird maybe unhealthy?",
            "can u check logs and metrics both",
            "if its fine then tell me what would break a deploy next time",
            "also is acr / image pull usually the issue?",
        ],
    },
    {
        "id": "M07",
        "title": "Mixed create-language but read-only intent",
        "turns": [
            "dont create anything — just tell me if we should create tf for container apps",
            "propose only, no apply, what modules would we need",
            "and how would rollback work if apply failed later",
            "stick to read only pls",
        ],
    },
    {
        "id": "M08",
        "title": "Scope bait (should NOT interview)",
        "turns": [
            "check drift between azure and github for eqip",
            "idk which repo just use whatever is mapped",
            "subscription is fine whole thing",
            "every service present in code vs not",
        ],
    },
]


def login(client: httpx.Client) -> str:
    resp = client.post(
        f"{BASE}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    resp.raise_for_status()
    return str(resp.json()["token"])


def classify_reply(reply: str) -> dict[str, Any]:
    text = reply or ""
    scope_bug = bool(SCOPE_BUG_RE.search(text)) and len(text) < 900
    tf_hijack = bool(TF_HIJACK_RE.search(text)) and len(text) < 700
    empty = not text.strip()
    if scope_bug:
        status = "fail_scope_loop"
    elif tf_hijack:
        status = "fail_tf_hijack"
    elif empty:
        status = "fail_empty"
    else:
        status = "ok"
    return {
        "status": status,
        "scope_bug": scope_bug,
        "tf_hijack": tf_hijack,
        "reply_chars": len(text),
        "reply_preview": text[:320].replace("\n", " "),
    }


def run_thread(token: str, thread: dict[str, Any]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    chat_id: str | None = None
    turns_out: list[dict[str, Any]] = []
    with httpx.Client(timeout=TIMEOUT_S) as client:
        for index, message in enumerate(thread["turns"], start=1):
            started = time.time()
            payload = {
                "message": message,
                "project_id": PROJECT_ID,
                "mode": "agent",
                "action_scope": "read_only",
                "access_level": "ask_approval",
            }
            if chat_id:
                payload["chat_id"] = chat_id
            try:
                resp = client.post(f"{BASE}/api/chat", headers=headers, json=payload)
                elapsed = round(time.time() - started, 1)
                if resp.status_code >= 400:
                    turns_out.append(
                        {
                            "turn": index,
                            "user": message,
                            "status": "fail_http",
                            "error": f"HTTP {resp.status_code}: {resp.text[:400]}",
                            "elapsed_s": elapsed,
                        }
                    )
                    break
                body = resp.json()
                chat_id = str(body.get("chat_id") or chat_id or "")
                reply = str(body.get("reply") or "")
                skills = list(body.get("skills_used") or [])
                classified = classify_reply(reply)
                turns_out.append(
                    {
                        "turn": index,
                        "user": message,
                        "skills_used": skills,
                        "elapsed_s": elapsed,
                        "needs_clarification": bool(body.get("needs_clarification")),
                        **classified,
                    }
                )
                print(
                    f"[{thread['id']} T{index}] {classified['status']} "
                    f"skills={skills} {elapsed}s",
                    flush=True,
                )
                # Stop early if scope-loop — remaining turns would just repeat.
                if classified["status"] == "fail_scope_loop":
                    break
            except Exception as exc:  # noqa: BLE001
                turns_out.append(
                    {
                        "turn": index,
                        "user": message,
                        "status": "fail_exception",
                        "error": str(exc),
                        "elapsed_s": round(time.time() - started, 1),
                    }
                )
                break
    statuses = [t.get("status") for t in turns_out]
    thread_status = "ok"
    if any(s == "fail_scope_loop" for s in statuses):
        thread_status = "fail_scope_loop"
    elif any(str(s).startswith("fail_") for s in statuses):
        thread_status = "fail_partial"
    return {
        "id": thread["id"],
        "title": thread["title"],
        "chat_id": chat_id,
        "status": thread_status,
        "turns": turns_out,
    }


def render_md(results: list[dict[str, Any]], out: Path) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ok = sum(1 for r in results if r.get("status") == "ok")
    scope = sum(1 for r in results if r.get("status") == "fail_scope_loop")
    lines = [
        "# EQIP messy multi-turn chat scenarios",
        "",
        f"Generated: {now}",
        f"Project: EQIP (`{PROJECT_ID}`)",
        "Mode: Agent · Read-only · Ask for approval · User: `admin`",
        "",
        "These chats intentionally use typos, slang, topic switches, and vague "
        "follow-ups in a **single chat thread** to stress memory + routing.",
        "",
        f"## Summary: {ok}/{len(results)} threads clean · "
        f"{scope} scope-loop failures",
        "",
        "| Thread | Title | Status | Chat id |",
        "|--------|-------|--------|---------|",
    ]
    for r in results:
        lines.append(
            f"| {r['id']} | {r['title']} | `{r.get('status')}` | "
            f"`{r.get('chat_id') or '—'}` |"
        )
    lines += ["", "## Threads", ""]
    for r in results:
        lines += [f"### {r['id']}. {r['title']}", ""]
        for turn in r.get("turns") or []:
            lines += [
                f"**Turn {turn.get('turn')} — user:**",
                "",
                turn.get("user", ""),
                "",
                f"- Result: `{turn.get('status')}`",
                f"- Skills: {', '.join(turn.get('skills_used') or []) or '—'}",
                f"- Seconds: {turn.get('elapsed_s', '?')}",
            ]
            if turn.get("error"):
                lines.append(f"- Error: {turn['error']}")
            if turn.get("reply_preview"):
                lines.append(f"- Preview: {turn['reply_preview']}")
            lines.append("")
    lines += [
        "## Pass criteria",
        "",
        "- Must **not** ask which GitHub repo / Azure subscription-vs-RG when connected.",
        "- Vague follow-ups (`all of it`, `evrything bro`, `container app`) must continue prior intent.",
        "- Read-only propose/explain must not bounce into Terraform write prompts.",
        "",
        "JSON: `scripts/messy_chat_scenario_results.json`",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    results_path = root / "scripts" / "messy_chat_scenario_results.json"
    md_path = root / "docs" / "eqip-messy-chat-scenarios.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)

    # Write questions first.
    render_md(
        [
            {
                "id": t["id"],
                "title": t["title"],
                "chat_id": None,
                "status": "pending",
                "turns": [
                    {"turn": i, "user": m, "status": "pending"}
                    for i, m in enumerate(t["turns"], start=1)
                ],
            }
            for t in THREADS
        ],
        md_path,
    )
    print(f"Wrote question pack -> {md_path}", flush=True)

    with httpx.Client(timeout=30.0) as client:
        token = login(client)

    results: list[dict[str, Any]] = []
    # Sequential — each thread is already multi-turn and heavy.
    for thread in THREADS:
        print(f"=== {thread['id']} {thread['title']} ===", flush=True)
        results.append(run_thread(token, thread))

    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    render_md(results, md_path)
    ok = sum(1 for r in results if r.get("status") == "ok")
    scope = sum(1 for r in results if r.get("status") == "fail_scope_loop")
    print(f"Done: {ok}/{len(results)} clean, {scope} scope-loops -> {md_path}", flush=True)


if __name__ == "__main__":
    main()
