"use client";

import { useEffect, useRef, useState } from "react";
import { PageHead, Panel, Pill } from "@/components/ui";
import { dangerBtn, fieldClass, ghostBtn, primaryBtn, SuiteDown, SuiteGate, SuiteProjectBar, useSuiteProject } from "@/components/suite/SuiteScreen";
import { consumeSse, isSuiteDown, prettyName, suiteFetch, suiteJson, SUITE_DOWN } from "@/lib/suite";

function ChatBody() {
  const project = useSuiteProject();
  const [skills, setSkills] = useState([]);
  const [chats, setChats] = useState([]);
  const [chatId, setChatId] = useState("");
  const [messages, setMessages] = useState([]);
  const [mode, setMode] = useState("agent");
  const [skill, setSkill] = useState("");
  const [scope, setScope] = useState("read_only");
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("");
  const [sending, setSending] = useState(false);
  const [plan, setPlan] = useState(null);
  const [action, setAction] = useState(null);
  const [error, setError] = useState("");
  const abortRef = useRef(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const pending = window.localStorage.getItem("suiteSkill");
      if (pending) {
        setSkill(pending);
        window.localStorage.removeItem("suiteSkill");
      }
      const prompt = window.localStorage.getItem("suitePrompt");
      if (prompt) {
        setInput(prompt);
        window.localStorage.removeItem("suitePrompt");
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    let cancel = false;
    suiteJson("/api/skills")
      .then((list) => {
        if (!cancel) setSkills(Array.isArray(list) ? list : []);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      });
    return () => {
      cancel = true;
    };
  }, []);

  useEffect(() => {
    if (!project.projectId) return undefined;
    let cancel = false;
    suiteJson(`/api/chats?project_id=${encodeURIComponent(project.projectId)}`)
      .then((list) => {
        if (!cancel) setChats(Array.isArray(list) ? list : []);
      })
      .catch((err) => {
        if (!cancel) setError(err.message);
      });
    return () => {
      cancel = true;
    };
  }, [project.projectId]);

  async function openChat(id) {
    setChatId(id);
    setPlan(null);
    setAction(null);
    if (!id) {
      setMessages([]);
      return;
    }
    const detail = await suiteJson(`/api/chats/${id}`);
    setMessages(detail.messages || []);
  }

  function applyEvent(event, assistantId) {
    if (event.type === "status") setStatus(event.text || "");
    if (event.type === "chat" && event.chat_id) setChatId(event.chat_id);
    if (event.action) setAction(event.action);
    if (event.type === "delta") {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? { ...message, content: `${message.content || ""}${event.text || ""}` } : message,
        ),
      );
    }
    if (event.type === "final") {
      const nextPlan = event.mode === "plan" && Array.isArray(event.plan) ? event.plan : null;
      setPlan(nextPlan);
      setStatus("");
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? { ...message, content: event.reply || message.content, streaming: false } : message,
        ),
      );
    }
  }

  async function runStream(path, payload, assistantId) {
    const controller = new AbortController();
    abortRef.current = controller;
    const response = await suiteFetch(path, { method: "POST", body: payload, signal: controller.signal });
    if (response.status === 503) throw Object.assign(new Error(SUITE_DOWN), { status: 503 });
    await consumeSse(response, (event) => applyEvent(event, assistantId));
  }

  async function send() {
    const text = input.trim();
    if (!text || sending || !project.projectId) return;
    setSending(true);
    setError("");
    setPlan(null);
    setAction(null);
    setInput("");
    let activeId = chatId;
    try {
      if (!activeId) {
        const created = await suiteJson(`/api/chats?project_id=${encodeURIComponent(project.projectId)}`, { method: "POST" });
        activeId = created.id;
        setChatId(created.id);
        setChats((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      }
      const assistantId = `assistant-${Date.now()}`;
      setMessages((current) => [
        ...current,
        { id: `user-${Date.now()}`, role: "user", content: text },
        { id: assistantId, role: "assistant", content: "", streaming: true },
      ]);
      await runStream(
        "/api/chat/stream",
        {
          chat_id: activeId,
          project_id: project.projectId,
          message: text,
          mode,
          skill: skill || null,
          action_scope: scope,
          access_level: "ask_approval",
        },
        assistantId,
      );
    } catch (err) {
      if (err?.name === "AbortError") setStatus("Stopped.");
      else setError(err.message || "The chat request failed.");
    } finally {
      setSending(false);
      setMessages((current) => current.map((message) => (message.streaming ? { ...message, streaming: false } : message)));
    }
  }

  async function executePlan() {
    if (!plan?.length || !chatId || sending) return;
    setSending(true);
    setError("");
    const assistantId = `assistant-${Date.now()}`;
    setMessages((current) => [...current, { id: assistantId, role: "assistant", content: "", streaming: true }]);
    const steps = plan;
    setPlan(null);
    try {
      await runStream(
        "/api/chat/execute-plan",
        {
          chat_id: chatId,
          project_id: project.projectId,
          steps,
          action_scope: scope,
          access_level: "ask_approval",
        },
        assistantId,
      );
    } catch (err) {
      setError(err.message || "The plan failed.");
    } finally {
      setSending(false);
    }
  }

  async function decideAction(kind) {
    if (!action?.id) return;
    try {
      const path = kind === "approve" ? "approve" : "reject";
      const body = kind === "approve" ? { approver: "user" } : { approver: "user", reason: "Rejected in chat" };
      setAction(await suiteJson(`/api/actions/${action.id}/${path}`, { method: "POST", body }));
    } catch (err) {
      setError(err.message);
    }
  }

  if (project.down || isSuiteDown({ message: error, status: error === SUITE_DOWN ? 503 : 0 })) return <SuiteDown />;

  return (
    <div className="space-y-4">
      <PageHead
        eyebrow="Agentic"
        title="Chat"
        description="Agent runs a skill. Plan returns steps you can execute. The default scope is read-only."
        action={
          <SuiteProjectBar loading={project.loading} loadError={project.error}
            projects={project.projects}
            projectId={project.projectId}
            onChange={(id) => {
              project.selectProject(id);
              setChatId("");
              setMessages([]);
            }}
            onCreated={(created) => {
              project.setProjects((current) => [...current, created]);
              project.selectProject(created.id);
            }}
          />
        }
      />
      {error && error !== SUITE_DOWN && <p className="text-sm text-danger">{error}</p>}
      <Panel>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="flex rounded-2xl bg-sidebar p-1">
            {["agent", "plan"].map((value) => (
              <button key={value} type="button" onClick={() => setMode(value)} className={`rounded-xl px-3 py-1.5 text-xs font-semibold ${mode === value ? "bg-white text-ink shadow-sm" : "text-muted"}`}>
                {value === "agent" ? "Agent" : "Plan"}
              </button>
            ))}
          </div>
          <select className="h-10 rounded-2xl border border-line bg-white px-3 text-sm" value={skill} onChange={(event) => setSkill(event.target.value)} aria-label="Skill">
            <option value="">Auto</option>
            {skills.map((item) => (
              <option key={item.name} value={item.name}>
                {prettyName(item.name)}
              </option>
            ))}
          </select>
          <div className="flex rounded-2xl bg-sidebar p-1">
            {[
              ["read_only", "Read"],
              ["write", "Write"],
            ].map(([value, label]) => (
              <button key={value} type="button" onClick={() => setScope(value)} className={`rounded-xl px-3 py-1.5 text-xs font-semibold ${scope === value ? "bg-white text-ink shadow-sm" : "text-muted"}`}>
                {label}
              </button>
            ))}
          </div>
          <select className="h-10 min-w-[180px] rounded-2xl border border-line bg-white px-3 text-sm" value={chatId} onChange={(event) => void openChat(event.target.value)} aria-label="Chat">
            <option value="">New chat</option>
            {chats.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title || item.id}
              </option>
            ))}
          </select>
          {status && <span className="text-xs text-muted">{status}</span>}
        </div>
        <div className="max-h-[480px] space-y-3 overflow-y-auto">
          {messages.length === 0 && <p className="text-sm text-muted">Send a message to start a chat in this skills project.</p>}
          {messages.map((message) => (
            <div key={message.id} className={`rounded-2xl px-3 py-2 text-sm ${message.role === "user" ? "bg-orange-50" : "bg-canvas"}`}>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{message.role}</div>
              <div className="whitespace-pre-wrap text-ink">{message.content || (message.streaming ? "…" : "")}</div>
            </div>
          ))}
        </div>
        {plan?.length > 0 && (
          <div className="mt-3 rounded-2xl border border-line p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">Plan</div>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
              {plan.map((step, index) => (
                <li key={`${step.skill}-${index}`}>
                  {prettyName(step.skill)}
                  {step.objective ? ` — ${step.objective}` : ""}
                </li>
              ))}
            </ol>
            <button type="button" className={`${primaryBtn} mt-3`} disabled={sending} onClick={() => void executePlan()}>
              Execute plan
            </button>
          </div>
        )}
        {action && (
          <div className="mt-3 rounded-2xl border border-line p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone={action.status === "queued" ? "ok" : "warn"}>{action.status}</Pill>
              <span className="font-semibold">{action.provider}</span>
              <span className="text-muted">{action.target}</span>
            </div>
            {action.command_preview && <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-xl bg-canvas p-3 text-xs">{action.command_preview}</pre>}
            {action.why && <p className="mt-2 text-muted">{action.why}</p>}
            <div className="mt-3 flex gap-2">
              <button type="button" className={primaryBtn} onClick={() => void decideAction("approve")}>Approve</button>
              <button type="button" className={dangerBtn} onClick={() => void decideAction("reject")}>Reject</button>
            </div>
          </div>
        )}
        <form
          className="mt-3 flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <input className={fieldClass} value={input} onChange={(event) => setInput(event.target.value)} placeholder="Message the agent" disabled={!project.projectId || sending} />
          <button type="submit" className={primaryBtn} disabled={!project.projectId || sending || !input.trim()}>
            {sending ? "Sending…" : "Send"}
          </button>
          {sending && (
            <button
              type="button"
              className={ghostBtn}
              onClick={() => abortRef.current?.abort()}
            >
              Stop
            </button>
          )}
        </form>
      </Panel>
    </div>
  );
}

export default function ChatPage() {
  return (
    <SuiteGate>
      <ChatBody />
    </SuiteGate>
  );
}
