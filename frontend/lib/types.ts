export type JsonObject = Record<string, unknown>;

export type Project = { id: string; name: string; is_default?: boolean };

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
  project_id?: string;
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
  modules: { key: string; label: string; description?: string; skills?: string[] }[];
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
  fingerprint?: string | null;
  occurrence_count?: number;
  last_seen_at?: string | null;
  created_at?: string | null;
};

export type Approval = {
  id: string;
  gate?: string;
  gate_label?: string;
  gate_rationale?: string;
  expired?: boolean;
  expires_in_seconds?: number;
  blast_radius?: string;
  evidence?: string;
  recommended_action?: string;
  rollback?: string;
  min_role?: string;
  min_role_label?: string;
  break_glass_applied?: boolean;
  preflight?: { summary?: string; checks?: string[] };
  precedent?: { summary?: string; outcome?: string; created_at?: string }[];
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
  actions_available?: boolean;
  action_scope?: "read_only" | "write";
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
  tier?: string;
  architect_mode?: string;
  action_id?: string;
  action?: Action;
  required_action_scope?: "read_only" | "write";
};

export type Action = {
  id: string;
  project_id?: string;
  provider: "azure" | "aws" | "github";
  target?: string;
  access_scope?: "read_only" | "write";
  access_level?: "ask_approval" | "auto_approve" | "full_access";
  status: string;
  command_preview?: string;
  operation_hash?: string;
  expected_result?: string;
  risk?: string;
  rollback?: string;
  why?: string;
  blast_radius?: string;
  degrade_plan?: string;
  preflight_summary?: JsonObject;
  error?: string;
  approval?: {
    decision?: string;
    confirmation_count?: number;
  } | null;
};

export type ActionEvent = {
  id: string;
  type: string;
  payload: JsonObject;
  created_at?: string;
};
