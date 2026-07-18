"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, consumeSse } from "../lib/api";
import type { ChatDetail, ChatMessage, ChatSummary, Project, Skill, StreamEvent } from "../lib/types";
import { Shell } from "./shell";

type UiMessage = ChatMessage & { plan?: { skill: string; objective: string }[]; streaming?: boolean; error?: boolean };

const defaultProject = "default";

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

function renderText(text: string) {
  return text.split("\n").map((line, index) => <span key={`${index}-${line}`}>{line}{index < text.split("\n").length - 1 && <br />}</span>);
}

export function ChatPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(defaultProject);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<"agent" | "plan">("agent");
  const [skill, setSkill] = useState("");
  const [actionScope, setActionScope] = useState<"read_only" | "write">("read_only");
  const [accessLevel, setAccessLevel] = useState<"ask_approval" | "auto_approve" | "full_access">("ask_approval");
  const [status, setStatus] = useState("Checking…");
  const [configured, setConfigured] = useState(false);
  const [sending, setSending] = useState(false);
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);
  const [pendingPlan, setPendingPlan] = useState<{ messageId: string; steps: { skill: string; objective: string }[] } | null>(null);
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
    const saved = window.localStorage.getItem("projectId") || defaultProject;
    setProjectId(list.some((project) => project.id === saved) ? saved : list[0]?.id || defaultProject);
  }, []);

  const loadChats = useCallback(async (selectedProject = projectId) => {
    const list = await api<ChatSummary[]>(`/api/chats?project_id=${encodeURIComponent(selectedProject)}`);
    setChats(list);
  }, [projectId]);

  const selectChat = useCallback(async (id: string) => {
    const chat = await api<ChatDetail>(`/api/chats/${id}`);
    setChatId(id);
    setMessages(chat.messages || []);
    setPendingPlan(null);
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
    void loadChats(projectId);
    setChatId(null);
    setMessages([]);
  }, [projectId, loadChats]);

  useEffect(() => {
    messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

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

  const createProject = async () => {
    const name = window.prompt("Project name");
    if (!name?.trim()) return;
    const project = await api<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
    setProjects((current) => [...current, project]);
    setProjectId(project.id);
    window.localStorage.setItem("projectId", project.id);
  };

  const newChat = async () => {
    const chat = await api<ChatSummary>(`/api/chats?project_id=${encodeURIComponent(projectId)}`, { method: "POST" });
    setChatId(chat.id);
    setMessages([]);
    setChats((current) => [chat, ...current]);
    inputRef.current?.focus();
  };

  const deleteChat = async (id: string) => {
    await api(`/api/chats/${id}`, { method: "DELETE" });
    setChats((current) => current.filter((chat) => chat.id !== id));
    if (chatId === id) {
      setChatId(null);
      setMessages([]);
    }
  };

  const runStream = async (url: string, body: Record<string, unknown>, messageId: string) => {
    const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error("The stream failed to start.");
    let accumulated = "";
    await consumeSse(response, (event: StreamEvent) => {
      if (event.chat_id) setChatId(String(event.chat_id));
      if (event.type === "status") setStatus(String(event.text || "Working…"));
      if (event.type === "delta") {
        accumulated += String(event.text || "");
        setMessages((current) => current.map((message) => message.id === messageId ? { ...message, content: accumulated, streaming: true } : message));
      }
      if (event.type === "final") {
        accumulated = String(event.reply || accumulated);
        const plan = Array.isArray(event.plan) ? event.plan : undefined;
        setMessages((current) => current.map((message) => message.id === messageId ? { ...message, content: accumulated, streaming: false, plan } : message));
        if (plan?.length) setPendingPlan({ messageId, steps: plan });
        setStatus(configured ? "Connected" : "Not configured");
      }
    });
    await loadChats(projectId);
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSlashOpen(false);
    setInput("");
    setSending(true);
    const userMessage: UiMessage = { id: `user-${Date.now()}`, role: "user", content: text };
    const assistantId = `assistant-${Date.now()}`;
    setMessages((current) => [...current, userMessage, { id: assistantId, role: "assistant", content: "", streaming: true }]);
    try {
      await runStream("/api/chat/stream", { chat_id: chatId, project_id: projectId, message: text, mode, skill: skill || null, action_scope: actionScope, access_level: accessLevel }, assistantId);
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
            <select className="project-select" value={projectId} onChange={(event) => { setProjectId(event.target.value); window.localStorage.setItem("projectId", event.target.value); }}>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
            <button className="icon-btn" title="New project" onClick={() => void createProject()}>+</button>
          </div></div>
          <button className="new-chat" onClick={() => void newChat()}>+ New chat</button>
          <div className="chat-list scroll">
            {chats.map((chat) => <div className={`chat-item${chat.id === chatId ? " active" : ""}`} key={chat.id}>
              <button className="chat-item-title" onClick={() => void selectChat(chat.id)}>{chat.title || "New chat"}</button>
              <button className="chat-item-del" title="Delete chat" onClick={() => void deleteChat(chat.id)}>×</button>
            </div>)}
          </div>
        </aside>
        <main className="chat">
          <div className="chat-toolbar">
            <div className="mode-toggle">
              <button className={`mode-btn${mode === "agent" ? " active" : ""}`} onClick={() => setMode("agent")}>Agent</button>
              <button className={`mode-btn${mode === "plan" ? " active" : ""}`} onClick={() => setMode("plan")}>Plan</button>
            </div>
            <div className="toolbar-right"><div className="status"><span className={`dot${configured ? " ok" : ""}`} /><span>{status}</span></div>
              <div className="active-skill"><span className="active-skill-label">{skill ? prettyName(skill) : "Auto · multi-agent"}</span></div>
            </div>
          </div>
          <div className="messages scroll" ref={messagesRef}>
            {!messages.length && <div className="empty-state"><div className="empty-eyebrow">Secure-by-design delivery</div><h3>What can I help you secure today?</h3><p>Let the agent plan a multi-skill task, or type <code>/</code> to pick a skill inline.</p><div className="suggestions">
              {emptyStateSuggestions.map((suggestion) => <button className="suggestion" key={suggestion} onClick={() => { onInput(suggestion); inputRef.current?.focus(); }}>{suggestion}</button>)}
            </div></div>}
            {messages.map((message) => <div className={`message ${message.role}${message.error ? " error" : ""}`} key={message.id}>
              <div className="message-role">{message.role === "user" ? "You" : "Assistant"}</div>
              <div className="message-content">{renderText(message.content || (message.streaming ? "Working…" : ""))}</div>
              {message.plan?.length && pendingPlan?.messageId === message.id && <div className="plan-actions"><div className="plan-list">{message.plan.map((step) => <div className="plan-step" key={`${step.skill}-${step.objective}`}><strong>{prettyName(step.skill)}</strong><span>{step.objective}</span></div>)}</div><button className="primary" onClick={() => void executePlan()} disabled={sending}>Approve and execute</button></div>}
            </div>)}
          </div>
          <form className="composer" onSubmit={(event) => { event.preventDefault(); void sendMessage(); }}>
            {slashOpen && slashMatches.length > 0 && <div className="slash-menu scroll">{slashMatches.map((item, index) => <button type="button" className={`slash-item${index === slashIndex ? " active" : ""}`} key={item.name} onClick={() => chooseSkill(item.name)}><strong>/{item.name}</strong><span>{item.description}</span></button>)}</div>}
            {suggestedSkill && <div className="suggest-bar"><span className="suggest-label">Suggested skill</span><button type="button" className="suggest-pill" onClick={acceptSuggestion}>{prettyName(suggestedSkill.name)}</button><span className="suggest-hint">Press Tab</span></div>}
            <div className="composer-row"><textarea id="input" ref={inputRef} value={input} rows={1} onChange={(event) => onInput(event.target.value)} onKeyDown={onKeyDown} placeholder="Describe your task, paste a pipeline / IaC / scan output, or type / to pick a skill…" /><button id="send-btn" type="submit" disabled={sending}>{sending ? "…" : "Send"}</button></div>
            <div className="composer-controls"><label className="control"><span>Actions</span><select value={actionScope} onChange={(event) => setActionScope(event.target.value as typeof actionScope)}><option value="read_only">Read-only actions</option><option value="write">Write actions</option></select></label><label className="control"><span>Access</span><select value={accessLevel} onChange={(event) => setAccessLevel(event.target.value as typeof accessLevel)}><option value="ask_approval">Ask for approval</option><option value="auto_approve">Approve for me</option><option value="full_access">Full access</option></select></label><span className="composer-hint">{mode === "plan" ? "Plans are read-only until approved." : "Shift+Enter for a new line."}</span></div>
          </form>
        </main>
      </div>
    </Shell>
  );
}
