export type JsonObject = Record<string, unknown>;

export type Project = { id: string; name: string };

export type Skill = {
  name: string;
  category: string;
  description: string;
  triggers?: string[];
  wiki?: string;
  parameters?: JsonObject;
};

export type ChatSummary = {
  id: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
};

export type ChatMessage = {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: JsonObject;
  meta?: JsonObject;
  created_at?: string;
};

export type MetricPoint = { t?: string; v: number };
export type MetricSeries = { name: string; points: MetricPoint[] };
export type MetricChart = {
  title: string;
  unit?: string;
  type?: "line" | "bar";
  series: MetricSeries[];
};

export type ChatDetail = ChatSummary & { messages: ChatMessage[] };

export type Catalog = {
  skills: Skill[];
  modules: { key: string; label: string; description?: string }[];
};

export type Finding = {
  id: string;
  title: string;
  severity: string;
  status: "open" | "acknowledged" | "resolved";
  skill?: string;
  resource?: string;
  category?: string;
  blast_radius?: string;
  gate_decision?: string;
  gate_label?: string;
  gate_rationale?: string;
  module_label?: string;
  evidence?: string;
  recommended_action?: string;
};

export type Approval = {
  id: string;
  gate?: string;
  gate_label?: string;
  expired?: boolean;
  expires_in_seconds?: number;
  finding?: Finding;
};

export type Workflow = {
  id: string;
  name: string;
  objective?: string;
  skills: string[];
  module?: string;
  module_label?: string;
  environment: "dev" | "staging" | "prod";
  schedule_cron?: string;
  enabled: boolean;
  last_run?: Run;
};

export type Run = {
  id: string;
  workflow_name?: string;
  trigger?: string;
  status: string;
  created_at?: string;
  finding_count?: number;
  error?: string;
  findings?: Finding[];
};

export type ConnectionStatus = {
  provider: string;
  connected: boolean;
  method?: string;
  identity?: string;
  hint?: string;
  connected_at?: string;
  project_id?: string;
};

export type StreamEvent = JsonObject & {
  type?: string;
  chat_id?: string;
  text?: string;
  reply?: string;
  mode?: string;
  plan?: { skill: string; objective: string }[];
  charts?: MetricChart[];
};
