"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, apiUrl, consumeSse } from "../lib/api";
import { authHeaders, clearSession } from "../lib/auth";
import { displayBrandText } from "../lib/branding";
import { copyText } from "../lib/clipboard";
import type { Action, ActionEvent, ChatDetail, ChatMessage, ChatSummary, ConnectionStatus, MetricChart, Project, Skill, StreamEvent } from "../lib/types";
import { MarkdownContent } from "./markdown";
import { MetricCharts } from "./metric-charts";
import { Modal } from "./modal";
import { ProjectModal } from "./project-modal";
import { Shell } from "./shell";
import { ThemedSelect } from "./themed-select";

type ChatMode = "agent" | "plan";
type UiMessage = ChatMessage & { plan?: { skill: string; objective: string }[]; charts?: MetricChart[]; displayMode?: ChatMode; streaming?: boolean; error?: boolean };

function prettyName(value: string) {
  return value.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function capitalize(value: string) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function scoreSkill(item: Skill, text: string) {
  const terms = [item.name.replaceAll("_", " "), ...(item.triggers || []), item.category || ""];
  const haystack = text.toLowerCase();
  return terms.reduce((score, term) => score + term.toLowerCase().split(/[\s,]+/).filter((word) => word.length > 3 && haystack.includes(word)).length, 0);
}

function messageMeta(message: ChatMessage) {
  return message.metadata || message.meta || {};
}

function actionEventText(event: ActionEvent) {
  const payload = event.payload || {};
  const phase = String(payload.phase || event.type.replace(/^action_/, "").replaceAll("_", " "));
  const status = payload.status ? ` · ${String(payload.status)}` : "";
  const output = String(payload.stdout || payload.stderr || payload.message || payload.recommendation || "").trim();
  const queueState = payload.queue_depth !== undefined
    ? ` · queue depth ${String(payload.queue_depth)} · executor ${payload.executor_available ? "available" : "unavailable"}`
    : "";
  const jobId = payload.rq_job_id ? ` · RQ ${String(payload.rq_job_id)}` : "";
  return `${phase}${status}${queueState}${jobId}${output ? `: ${output}` : ""}`;
}

export function ChatPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<ChatMode>("agent");
  const [skill, setSkill] = useState("");
  const [actionScope, setActionScope] = useState<"read_only" | "write">("read_only");
  const [accessLevel, setAccessLevel] = useState<"ask_approval" | "auto_approve" | "full_access">("ask_approval");
  const [providerConnections, setProviderConnections] = useState<ConnectionStatus[]>([]);
  const [status, setStatus] = useState("Checking…");
  const [configured, setConfigured] = useState(false);
  const [sending, setSending] = useState(false);
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);
  const [pendingPlan, setPendingPlan] = useState<{ messageId: string; steps: { skill: string; objective: string }[] } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ChatSummary | null>(null);
  const [deletingChat, setDeletingChat] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [activeAction, setActiveAction] = useState<Action | null>(null);
  const [actionEvents, setActionEvents] = useState<ActionEvent[]>([]);
  const [cancelingAction, setCancelingAction] = useState(false);
  const [fullAccessModalOpen, setFullAccessModalOpen] = useState(false);
  const [fullAccessStep, setFullAccessStep] = useState<1 | 2>(1);
  const [fullAccessBusy, setFullAccessBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);

  const resizeInput = useCallback(() => {
    const element = inputRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 240)}px`;
  }, []);

  const loadProjects = useCallback(async () => {
    const list = await api<Project[]>("/api/projects");
    setProjects(list);
    const saved = window.localStorage.getItem("projectId");
    const selected = (saved && list.some((project) => project.id === saved))
      ? saved
      : list.find((project) => project.is_default)?.id || list[0]?.id || null;
    setProjectId(selected);
    if (selected) {
      const savedScope = window.localStorage.getItem(`actionScope:${selected}`);
      setActionScope(savedScope === "write" ? "write" : "read_only");
    }
  }, []);

  const loadChats = useCallback(async (selectedProject?: string) => {
    const selected = selectedProject || projectId;
    if (!selected) return;
    const list = await api<ChatSummary[]>(`/api/chats?project_id=${encodeURIComponent(selected)}`);
    setChats(list);
  }, [projectId]);

  const loadProviderStatus = useCallback(async (selectedProject: string, scope: "read_only" | "write") => {
    try {
      const list = await api<ConnectionStatus[]>(`/api/projects/${selectedProject}/provider-status?action_scope=${scope}`);
      setProviderConnections(list);
    } catch {
      setProviderConnections([]);
    }
  }, []);

  const selectChat = useCallback(async (id: string) => {
    const chat = await api<ChatDetail>(`/api/chats/${id}`);
    setChatId(id);
    setMessages((chat.messages || []).map((message) => ({
      ...message,
      displayMode: messageMeta(message).mode === "plan" ? "plan" : "agent",
      charts: Array.isArray(messageMeta(message).charts) ? messageMeta(message).charts as MetricChart[] : undefined,
    })));
    setPendingPlan(null);
    const actionId = [...(chat.messages || [])].reverse().map((message) => String(messageMeta(message).action_id || "")).find(Boolean);
    if (actionId) {
      try {
        const action = await api<Action>(`/api/actions/${actionId}`);
        if (["queued", "running"].includes(action.status)) {
          await api(`/api/actions/${actionId}/diagnostics`);
        }
        const events = await api<ActionEvent[]>(`/api/actions/${actionId}/events`);
        setActiveAction(action);
        setActionEvents(events);
      } catch { setActiveAction(null); setActionEvents([]); }
    } else {
      setActiveAction(null);
      setActionEvents([]);
    }
    setEditingMessageId(null);
  }, []);

  useEffect(() => {
    let active = true;
    void Promise.all([
      api<{ azure_configured: boolean }>("/api/health").then((health) => {
        if (!active) return;
        setConfigured(health.azure_configured);
        setStatus(health.azure_configured ? "Connected" : "Not configured");
      }).catch(() => active && setStatus("Unavailable")),
      api<Skill[]>("/api/skills").then((list) => active && setSkills(list)).catch(() => undefined),
      loadProjects(),
    ]);
    const pending = window.localStorage.getItem("pendingPrompt");
    if (pending) {
      window.localStorage.removeItem("pendingPrompt");
      setInput(pending);
    }
    return () => { active = false; };
  }, [loadProjects]);

  useEffect(() => {
    void loadChats(projectId || undefined);
    setChatId(null);
    setMessages([]);
    setActiveAction(null);
    setActionEvents([]);
    setFullAccessModalOpen(false);
  }, [projectId, loadChats]);

  useEffect(() => {
    if (projectId) void loadProviderStatus(projectId, actionScope);
    else setProviderConnections([]);
  }, [projectId, actionScope, loadProviderStatus]);

  useEffect(() => {
    messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, actionEvents, activeAction?.status]);

  const activeActionId = activeAction?.id;
  const activeActionStatus = activeAction?.status;
  useEffect(() => {
    if (!activeActionId) return;
    let active = true;
    const refresh = async () => {
      try {
        const latest = await api<Action>(`/api/actions/${activeActionId}`);
        if (["queued", "running"].includes(latest.status)) {
          await api(`/api/actions/${activeActionId}/diagnostics`);
        }
        const events = await api<ActionEvent[]>(`/api/actions/${activeActionId}/events`);
        if (active) {
          setActiveAction(latest);
          setActionEvents(events);
        }
      } catch {
        // Keep the last known state while the executor is unavailable.
      }
    };
    void refresh();
    if (!["queued", "running"].includes(activeActionStatus || "")) return () => { active = false; };
    const timer = window.setInterval(() => void refresh(), 900);
    return () => { active = false; window.clearInterval(timer); };
  }, [activeActionId, activeActionStatus]);

  useEffect(() => {
    resizeInput();
  }, [input, resizeInput]);

  const slashMatches = useMemo(() => {
    if (!slashOpen) return [];
    const query = input.slice(input.lastIndexOf("/") + 1).toLowerCase();
    return skills.filter((item) => item.name.includes(query) || item.category.toLowerCase().includes(query)).slice(0, 8);
  }, [input, slashOpen, skills]);

  const suggestedSkill = useMemo<Skill | null>(() => {
    const text = input.trim();
    if (skill || slashOpen || text.startsWith("/") || text.length < 8) return null;
    let best: Skill | null = null;
    let bestScore = 0;
    skills.forEach((item) => {
      const score = scoreSkill(item, text);
      if (score > bestScore) {
        best = item;
        bestScore = score;
      }
    });
    return bestScore > 0 ? best : null;
  }, [input, skill, slashOpen, skills]);

  const emptyStateSuggestions = useMemo(() => skills.map((item) => capitalize(item.triggers?.[0] || item.description)).slice(0, 4), [skills]);

  const providerLabel = (provider: string) => ({ azure: "Azure", aws: "AWS", github: "GitHub" }[provider] || provider);

  const chooseSkill = (name: string) => {
    setSkill(name === "auto" ? "" : name);
    const slash = input.lastIndexOf("/");
    setInput(`${input.slice(0, slash)}${name === "auto" ? "" : `/${name} `}`);
    setSlashOpen(false);
    inputRef.current?.focus();
  };

  const acceptSuggestion = () => {
    if (!suggestedSkill) return;
    setSkill(suggestedSkill.name);
    inputRef.current?.focus();
  };

  const createProject = async (name: string) => {
    const project = await api<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name }) });
    setProjects((current) => [...current, project]);
    setProjectId(project.id);
    window.localStorage.setItem("projectId", project.id);
    setActionScope("read_only");
    window.localStorage.setItem(`actionScope:${project.id}`, "read_only");
  };

  const selectProject = (value: string) => {
    setProjectId(value);
    window.localStorage.setItem("projectId", value);
    const savedScope = window.localStorage.getItem(`actionScope:${value}`);
    setActionScope(savedScope === "write" ? "write" : "read_only");
  };

  const selectActionScope = (value: string) => {
    const scope = value as "read_only" | "write";
    setActionScope(scope);
    if (projectId) window.localStorage.setItem(`actionScope:${projectId}`, scope);
  };

  const newChat = async () => {
    if (!projectId) return;
    const chat = await api<ChatSummary>(`/api/chats?project_id=${encodeURIComponent(projectId)}`, { method: "POST" });
    setChatId(chat.id);
    setMessages([]);
    setEditingMessageId(null);
    setChats((current) => [chat, ...current]);
    inputRef.current?.focus();
  };

  const startEdit = (message: UiMessage) => {
    if (!message.id || sending) return;
    setEditingMessageId(message.id);
    setInput(message.content);
    setSlashOpen(false);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const copyMessage = async (message: UiMessage) => {
    if (!message.content) return;
    try {
      await copyText(message.content);
      setCopiedMessageId(message.id || null);
      window.setTimeout(() => setCopiedMessageId(null), 1600);
    } catch {
      setStatus("Clipboard unavailable");
    }
  };

  const copyConversation = async () => {
    if (!messages.length) return;
    const transcript = messages.filter((message) => message.content).map((message) => `${message.role === "user" ? "You" : "Assistant"}:\n${message.content}`).join("\n\n");
    try {
      await copyText(transcript);
      setCopiedMessageId("conversation");
      window.setTimeout(() => setCopiedMessageId(null), 1600);
    } catch {
      setStatus("Clipboard unavailable");
    }
  };

  const confirmDeleteChat = async () => {
    if (!deleteTarget || deletingChat) return;
    const id = deleteTarget.id;
    setDeletingChat(true);
    try {
      await api(`/api/chats/${id}`, { method: "DELETE" });
      setChats((current) => current.filter((chat) => chat.id !== id));
      if (chatId === id) {
        setChatId(null);
        setMessages([]);
      }
      setDeleteTarget(null);
    } finally {
      setDeletingChat(false);
    }
  };

  const selectMode = (nextMode: ChatMode) => {
    setMode(nextMode);
    if (nextMode === "agent") setPendingPlan(null);
  };

  const showPlanApproval = (message: UiMessage) => (
    mode === "plan" && message.displayMode === "plan" && Boolean(message.plan?.length) && pendingPlan?.messageId === message.id
  );

  const runStream = async (url: string, body: Record<string, unknown>, messageId: string) => {
    const response = await fetch(apiUrl(url), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });
    if (response.status === 401) {
      clearSession();
      window.location.replace("/login");
      throw new Error("Not authenticated");
    }
    if (!response.ok) throw new Error("The stream failed to start.");
    let accumulated = "";
    await consumeSse(response, (event: StreamEvent) => {
      if (event.chat_id) setChatId(String(event.chat_id));
      if (event.action_id || event.action) {
        const action = event.action || ({ id: String(event.action_id), provider: String(event.provider || "azure"), status: String(event.type || "planned") } as Action);
        setActiveAction((current) => ({ ...current, ...action, id: action.id || String(event.action_id) }));
      }
      if (event.type === "action_planned" || event.type === "approval_required" || event.type === "action_queued" || event.type === "action_started" || event.type === "action_output" || event.type === "action_verified" || event.type === "action_succeeded" || event.type === "action_failed") {
        setActiveAction((current) => current ? { ...current, status: String(event.type || "planned").replace("action_", "") } : current);
      }
      if (event.type === "status") setStatus(String(event.text || "Working…"));
      if (event.type === "delta") {
        accumulated += String(event.text || "");
        setMessages((current) => current.map((message) => message.id === messageId ? { ...message, content: accumulated, streaming: true } : message));
      }
      if (event.type === "final") {
        if (event.required_action_scope === "write" && projectId) {
          setActionScope("write");
          window.localStorage.setItem(`actionScope:${projectId}`, "write");
        }
        accumulated = String(event.reply || accumulated);
        const responseMode: ChatMode = event.mode === "plan" ? "plan" : "agent";
        const plan = responseMode === "plan" && Array.isArray(event.plan) ? event.plan : undefined;
        const charts = Array.isArray(event.charts) ? event.charts : undefined;
        setMessages((current) => current.map((message) => message.id === messageId ? { ...message, content: accumulated, streaming: false, displayMode: responseMode, plan, charts } : message));
        if (responseMode === "plan" && plan?.length) setPendingPlan({ messageId, steps: plan });
        else setPendingPlan(null);
        setStatus(configured ? "Connected" : "Not configured");
      }
    });
    await loadChats(projectId || undefined);
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending || !projectId) return;
    const editId = editingMessageId;
    setSlashOpen(false);
    setInput("");
    setEditingMessageId(null);
    setPendingPlan(null);
    setActiveAction(null);
    setActionEvents([]);
    setSending(true);
    const userMessage: UiMessage = { id: `user-${Date.now()}`, role: "user", content: text };
    const assistantId = `assistant-${Date.now()}`;
    setMessages((current) => {
      if (!editId) return [...current, userMessage, { id: assistantId, role: "assistant", content: "", streaming: true }];
      const index = current.findIndex((message) => message.id === editId);
      if (index < 0) return [...current, userMessage, { id: assistantId, role: "assistant", content: "", streaming: true }];
      return [...current.slice(0, index), { ...current[index], content: text }, { id: assistantId, role: "assistant", content: "", streaming: true }];
    });
    try {
      await runStream("/api/chat/stream", { chat_id: chatId, project_id: projectId, message: text, edit_message_id: editId, mode, skill: skill || null, action_scope: actionScope, access_level: accessLevel }, assistantId);
    } catch (error) {
      setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, content: error instanceof Error ? error.message : "Something went wrong reaching the server.", streaming: false, error: true } : message));
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const executePlan = async () => {
    if (!pendingPlan || !chatId || sending) return;
    setSending(true);
    setPendingPlan(null);
    const assistantId = `assistant-${Date.now()}`;
    setMessages((current) => [...current, { id: assistantId, role: "assistant", content: "", streaming: true }]);
    try {
      await runStream("/api/chat/execute-plan", { chat_id: chatId, project_id: projectId, steps: pendingPlan.steps, action_scope: actionScope, access_level: accessLevel }, assistantId);
    } catch (error) {
      setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, content: error instanceof Error ? error.message : "The plan failed.", streaming: false, error: true } : message));
    } finally {
      setSending(false);
    }
  };

  const approveActiveAction = async () => {
    if (!activeAction) return;
    try {
      const action = await api<Action>(`/api/actions/${activeAction.id}/approve`, { method: "POST", body: JSON.stringify({ approver: "user" }) });
      setActiveAction(action);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Approval failed");
    }
  };

  const openFullAccessModal = () => {
    if (!activeAction) return;
    setFullAccessStep(activeAction.approval?.confirmation_count && activeAction.approval.confirmation_count > 0 ? 2 : 1);
    setFullAccessModalOpen(true);
  };

  const confirmFullAccess = async () => {
    if (!activeAction || fullAccessBusy) return;
    setFullAccessBusy(true);
    try {
      const action = await api<Action>(`/api/actions/${activeAction.id}/approve`, { method: "POST", body: JSON.stringify({ approver: "user" }) });
      setActiveAction(action);
      if (action.status === "queued") {
        setFullAccessModalOpen(false);
      } else {
        setFullAccessStep(2);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Full-access confirmation failed");
    } finally {
      setFullAccessBusy(false);
    }
  };

  const rejectActiveAction = async () => {
    if (!activeAction) return;
    try {
      const action = await api<Action>(`/api/actions/${activeAction.id}/reject`, { method: "POST", body: JSON.stringify({ approver: "user", reason: "Rejected in chat" }) });
      setActiveAction(action);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Rejection failed");
    }
  };

  const cancelActiveAction = async () => {
    if (!activeAction || cancelingAction) return;
    setCancelingAction(true);
    try {
      const action = await api<Action>(`/api/actions/${activeAction.id}/cancel`, { method: "POST", body: JSON.stringify({ approver: "user" }) });
      setActiveAction(action);
      setActionEvents(await api<ActionEvent[]>(`/api/actions/${action.id}/events`));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not cancel action");
    } finally {
      setCancelingAction(false);
    }
  };

  const onInput = (value: string) => {
    setInput(value);
    const slash = value.lastIndexOf("/");
    setSlashOpen(slash >= 0 && !value.slice(slash).includes(" "));
    setSlashIndex(0);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (slashOpen && slashMatches.length) {
      if (event.key === "ArrowDown") { event.preventDefault(); setSlashIndex((index) => (index + 1) % slashMatches.length); return; }
      if (event.key === "ArrowUp") { event.preventDefault(); setSlashIndex((index) => (index - 1 + slashMatches.length) % slashMatches.length); return; }
      if (event.key === "Enter" || event.key === "Tab") { event.preventDefault(); chooseSkill(slashMatches[slashIndex].name); return; }
      if (event.key === "Escape") { setSlashOpen(false); return; }
    }
    if (event.key === "Tab" && suggestedSkill) { event.preventDefault(); acceptSuggestion(); return; }
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); }
  };

  return (
    <Shell>
      <div className="workspace">
        <aside className="chat-sidebar">
          <div className="project-bar"><span className="project-label">Project</span><div className="project-row">
            <ThemedSelect className="project-select" value={projectId || ""} ariaLabel="Project" onChange={selectProject} options={projects.map((project) => ({ value: project.id, label: `${displayBrandText(project.name)}${project.is_default ? " (default)" : ""}` }))} />
            <button className="icon-btn" title="New project" onClick={() => setProjectModalOpen(true)}>+</button>
          </div></div>
          <button className="new-chat" onClick={() => void newChat()}>+ New chat</button>
          <div className="chat-list scroll">
            {chats.map((chat) => <div className={`chat-item${chat.id === chatId ? " active" : ""}`} key={chat.id}>
              <button className="chat-item-title" onClick={() => void selectChat(chat.id)}>{chat.title || "New chat"}</button>
              <button className="chat-item-del" title="Delete chat" onClick={() => setDeleteTarget(chat)}>×</button>
            </div>)}
          </div>
        </aside>
        <main className="chat">
          <div className="chat-toolbar">
            <div className="mode-toggle">
              <button className={`mode-btn${mode === "agent" ? " active" : ""}`} onClick={() => selectMode("agent")}>Agent</button>
              <button className={`mode-btn${mode === "plan" ? " active" : ""}`} onClick={() => selectMode("plan")}>Plan</button>
            </div>
            <div className="toolbar-right"><div className="status"><span className={`dot${configured ? " ok" : ""}`} /><span>{status}</span></div>
              <div className="provider-statuses" aria-label="Project provider connections">
                {providerConnections.map((connection) => <span className={`provider-status ${connection.connected ? "connected" : "disconnected"}`} key={connection.provider} title={connection.connected ? `${providerLabel(connection.provider)} is connected for this project` : `${providerLabel(connection.provider)} is not connected for this project`}><span className="provider-status-dot" />{providerLabel(connection.provider)} {connection.connected ? "connected" : "not connected"}</span>)}
              </div>
              <button type="button" className="chat-tool-btn" onClick={() => void copyConversation()} disabled={!messages.length}>{copiedMessageId === "conversation" ? "Copied" : "Copy chat"}</button>
              <div className="active-skill"><span className="active-skill-label">{skill ? prettyName(skill) : "Auto · multi-agent"}</span></div>
            </div>
          </div>
          <div className="messages scroll" ref={messagesRef}>
            {!messages.length && <div className="empty-state"><div className="empty-eyebrow">Secure-by-design delivery</div><h3>What can I help you secure today?</h3><p>Let the agent plan a multi-skill task, or type <code>/</code> to pick a skill inline.</p><div className="suggestions">
              {emptyStateSuggestions.map((suggestion) => <button className="suggestion" key={suggestion} onClick={() => { onInput(suggestion); inputRef.current?.focus(); }}>{suggestion}</button>)}
            </div></div>}
            {messages.map((message) => <div className={`message ${message.role}${message.error ? " error" : ""}`} key={message.id}>
              <div className="message-role">{message.role === "user" ? "You" : "Assistant"}</div>
              <div className="message-content">{message.role === "assistant" ? <MarkdownContent text={message.content || (message.streaming ? "Working…" : "")} /> : <span className="plain-message">{displayBrandText(message.content)}</span>}</div>
              {message.role === "assistant" && <MetricCharts charts={message.charts} />}
              {!message.streaming && <div className="message-actions">
                <button type="button" className="message-action" onClick={() => void copyMessage(message)}>{copiedMessageId === message.id ? "Copied" : "Copy"}</button>
                {message.role === "user" && <button type="button" className="message-action" onClick={() => startEdit(message)} disabled={sending}>Edit</button>}
              </div>}
              {showPlanApproval(message) && <div className="plan-actions"><div className="plan-list">{message.plan?.map((step) => <div className="plan-step" key={`${step.skill}-${step.objective}`}><strong>{prettyName(step.skill)}</strong><span>{step.objective}</span></div>)}</div><button className="primary" onClick={() => void executePlan()} disabled={sending}>Approve and execute</button></div>}
            </div>)}
            {activeAction && <section className="action-activity" aria-live="polite">
              <div className="action-activity-head"><div className="action-activity-title"><span className="activity-icon">›_</span><div><span className="message-role">Provider activity</span><strong>{activeAction.target || "Provider operation"}</strong></div></div><div className="action-activity-meta"><span className={`activity-status ${activeAction.status}`}>{activeAction.status.replaceAll("_", " ")}</span><span className="action-provider">{activeAction.provider}</span></div></div>
              {activeAction.command_preview && <code className="action-command">{activeAction.command_preview}</code>}
              {activeAction.expected_result && <p className="action-activity-expect"><b>Expected:</b> {activeAction.expected_result}</p>}
              {(actionEvents.length > 0 || ["queued", "running"].includes(activeAction.status)) && <div className="action-log" aria-label="Live deployment logs">{actionEvents.slice(-12).map((event) => <div className="action-log-line" key={event.id}><span>{event.created_at ? new Date(event.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--:--"}</span><code>{actionEventText(event)}</code></div>)}{!actionEvents.length && <div className="action-log-empty">Waiting for the provider executor…</div>}</div>}
              {activeAction.error && <p className="error-text">{activeAction.error}</p>}
              <div className="action-actions">{["queued", "running"].includes(activeAction.status) && <button type="button" className="secondary cancel-action" onClick={() => void cancelActiveAction()} disabled={cancelingAction}>{cancelingAction ? "Stopping…" : "Stop action"}</button>}{["approval_required", "awaiting_approval"].includes(activeAction.status) && <><button type="button" className="secondary" onClick={() => void rejectActiveAction()}>Reject</button>{activeAction.access_level === "full_access" ? <button type="button" className="primary" onClick={openFullAccessModal}>Review danger action</button> : <button type="button" className="primary" onClick={() => void approveActiveAction()}>Approve action</button>}</>}</div>
            </section>}
          </div>
          <form className="composer" onSubmit={(event) => { event.preventDefault(); void sendMessage(); }}>
            {slashOpen && slashMatches.length > 0 && <div className="slash-menu scroll">{slashMatches.map((item, index) => <button type="button" className={`slash-item${index === slashIndex ? " active" : ""}`} key={item.name} onClick={() => chooseSkill(item.name)}><strong>/{item.name}</strong><span>{item.description}</span></button>)}</div>}
            {suggestedSkill && <div className="suggest-bar"><span className="suggest-label">Suggested skill</span><button type="button" className="suggest-pill" onClick={acceptSuggestion}>{prettyName(suggestedSkill.name)}</button><span className="suggest-hint">Press Tab</span></div>}
            {editingMessageId && <div className="edit-context"><span>Editing your question</span><button type="button" onClick={() => { setEditingMessageId(null); setInput(""); inputRef.current?.focus(); }}>Cancel</button></div>}
            <div className="composer-row"><textarea id="input" ref={inputRef} value={input} rows={1} onChange={(event) => onInput(event.target.value)} onKeyDown={onKeyDown} placeholder="Describe your task, paste a pipeline / IaC / scan output, or type / to pick a skill…" /><button id="send-btn" type="submit" disabled={sending}>{sending ? "…" : "Send"}</button></div>
            <div className="composer-controls"><label className="control"><span>Actions</span><ThemedSelect className="control-select" value={actionScope} ariaLabel="Actions" onChange={selectActionScope} options={[{ value: "read_only", label: "Read-only actions" }, { value: "write", label: "Write actions" }]} /></label><label className="control"><span>Access</span><ThemedSelect className="control-select" value={accessLevel} ariaLabel="Access" onChange={(value) => setAccessLevel(value as typeof accessLevel)} options={[{ value: "ask_approval", label: "Ask for approval" }, { value: "auto_approve", label: "Approve for me" }, { value: "full_access", label: "Full access" }]} /></label><span className={`action-scope-note${actionScope === "write" ? " write" : ""}`}>{actionScope === "write" ? "Write actions enabled for this request" : "Read-only actions"}</span><span className="composer-hint">{mode === "plan" ? "Plans are read-only until approved." : "Shift+Enter for a new line."}</span></div>
          </form>
        </main>
      </div>
      {projectModalOpen && <ProjectModal onClose={() => setProjectModalOpen(false)} onCreate={createProject} />}
      {fullAccessModalOpen && activeAction && <Modal eyebrow="Dangerous full-access action" title={fullAccessStep === 1 ? "Confirm this live change" : "Confirm execution a second time"} description="Full access can change the connected provider. The exact command, target, and risk are shown below. Two confirmations are required before queueing it." onClose={() => { if (!fullAccessBusy) setFullAccessModalOpen(false); }}><div className="full-access-review"><div><span className="modal-label">Target</span><code>{activeAction.target || "Provider operation"}</code></div><div><span className="modal-label">Command</span><code>{activeAction.command_preview || "Unavailable"}</code></div>{activeAction.risk && <div><span className="modal-label">Risk</span><p>{activeAction.risk}</p></div>}{activeAction.rollback && <div><span className="modal-label">Recovery</span><p>{activeAction.rollback}</p></div>}<div className="full-access-warning">{fullAccessStep === 1 ? "First confirmation: I understand this action can change live infrastructure." : "Second confirmation: execute the exact command shown above."}</div></div><div className="modal-actions"><button type="button" className="modal-btn ghost" onClick={() => setFullAccessModalOpen(false)} disabled={fullAccessBusy}>Cancel</button><button type="button" className="modal-btn danger" onClick={() => void confirmFullAccess()} disabled={fullAccessBusy}>{fullAccessBusy ? "Confirming…" : fullAccessStep === 1 ? "I understand, continue" : "Confirm and queue action"}</button></div></Modal>}
      {deleteTarget && <Modal eyebrow="Delete chat" title="Delete this conversation?" description={`This permanently removes “${deleteTarget.title || "New chat"}” and its messages.`} onClose={() => { if (!deletingChat) setDeleteTarget(null); }}><div className="modal-actions"><button type="button" className="modal-btn ghost" onClick={() => setDeleteTarget(null)} disabled={deletingChat}>Cancel</button><button type="button" className="modal-btn danger" onClick={() => void confirmDeleteChat()} disabled={deletingChat}>{deletingChat ? "Deleting…" : "Delete chat"}</button></div></Modal>}
    </Shell>
  );
}
