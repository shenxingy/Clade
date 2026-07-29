// ─── Core Types (mirrors FastAPI response shapes) ─────────────────

export type TaskStatus = 'pending' | 'running' | 'done' | 'failed' | 'paused';
export type TaskType = 'AUTO' | 'HORIZONTAL' | 'VERTICAL';
export type AgentRuntime = 'claude' | 'codex';
export type Effort = 'low' | 'medium' | 'high' | 'xhigh' | 'max';

export interface ExecutionEnvelope {
  schema_version: 'clade.execution/v1';
  run_id: string;
  created_at: string;
  request: {
    profile: string;
    runtime: AgentRuntime;
    connection: string;
    model: string | null;
    effort: Effort | null;
    requirements: Array<{ capability: string; level: string }>;
    preferences: Record<string, unknown>;
  };
  resolved: {
    surface: string;
    runtime: { id: AgentRuntime; version: string | null };
    inference: {
      connection: string;
      provider: string;
      protocol: string;
      endpoint_identity: string;
      model: string | null;
    };
    controls: { effort: Effort | null };
    resume: string;
    capabilities: Record<string, { state: string; source: string }>;
  };
  degradations: Array<{
    capability: string;
    requested: string;
    resolved: string;
    reason: string;
  }>;
  provenance: Record<string, string>;
}

export interface StatusSnapshot {
  schema_version: 'clade.status/v1';
  observed_at: string;
  task: {
    id: string;
    state: string;
    progress: {
      completed: number | null;
      total: number | null;
      source: string;
    };
  };
  git: {
    branch: string | null;
    dirty: boolean | null;
    checkpoint_sha: string | null;
  };
  execution: ExecutionEnvelope | null;
  limits: Array<Record<string, unknown>>;
  freshness: Record<string, string>;
}

export interface RuntimeConnection {
  agent_runtime: AgentRuntime;
  inference_provider: string;
  wire_protocol: string;
  endpoint_identity: string;
  models: Record<string, string>;
  pinned_models?: string[];
  discovery?: {
    adapter: 'anthropic' | 'openai' | 'minimax' | 'moonshot' | 'custom-openai' | 'native-static';
    store: 'claude-providers' | 'codex-config';
    profile: string;
    ttl_seconds?: number;
    timeout_seconds?: number;
    default_model?: string;
  };
  capabilities: Record<string, string>;
}

export interface ProviderRegistryConnection {
  id: string;
  agent_runtime: AgentRuntime;
  inference_provider: string;
  wire_protocol: string;
  endpoint_identity: string;
  models: string[];
  capabilities: Record<string, string>;
  catalog: {
    state: 'fresh' | 'stale' | 'unavailable' | 'declared';
    source: string;
    observed_at: string | null;
    expires_at: string | null;
    digest: string | null;
    last_error: string | null;
    model_capabilities: Record<string, Record<string, string>>;
  };
  health: { state: 'healthy' | 'degraded' | 'unreachable' | 'unknown' };
  selection: {
    pinned_models: string[];
    stale_fallback: boolean;
  };
}

export interface ProviderRegistrySnapshot {
  schema_version: 'clade.provider_registry/v1';
  observed_at: string;
  connections: ProviderRegistryConnection[];
}

export interface Task {
  id: string;
  description: string;
  model: string;
  agent_runtime: AgentRuntime | null;
  /** @deprecated Compatibility alias for agent_runtime. */
  provider: AgentRuntime | null;
  connection: string | null;
  execution_profile: string | null;
  execution_requirements: Record<string, string>;
  execution_envelope: ExecutionEnvelope | null;
  effort: Effort | null;
  route_reason: string | null;
  timeout: number;
  status: TaskStatus;
  worker_id: string | null;
  started_at: string | null;
  elapsed_s: number | null;
  last_commit: string | null;
  log_file: string | null;
  failed_reason: string | null;
  created_at: number;
  depends_on: string[];
  score: number | null;
  score_note: string | null;
  own_files: string[];
  forbidden_files: string[];
  gh_issue_number: number | null;
  is_critical_path: number | boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: number | null;
  task_type: TaskType;
  priority_score: number | null;
}

export type EvidenceLifecycle =
  | 'created'
  | 'running'
  | 'verifying'
  | 'delivery_pending'
  | 'delivered'
  | 'failed'
  | 'cancelled'
  | 'reverted';

export interface EvidenceBundle {
  schema_version: 'clade.evidence/v1';
  bundle_id: string;
  attempt_id: string;
  task_id: string;
  attempt_index: number;
  revision: number;
  lifecycle_state: EvidenceLifecycle;
  recorded_at: number;
  evidence: Record<string, unknown>;
  redaction_metadata: {
    schema_version: 'clade.redaction/v1';
    count: number;
    kinds: Record<string, number>;
    fields: string[];
  };
  previous_digest: string | null;
  digest: string;
}

export interface EvidenceAttemptsResponse {
  task_id: string;
  attempts: EvidenceBundle[];
}

export interface EvalMetricRatio {
  rate: number | null;
}

export interface EvalMetrics {
  schema_version: 'clade.eval_metrics/v1';
  candidates: {
    total: number;
    quarantined: number;
    promoted: number;
    rejected: number;
    expired: number;
  };
  evidence_completeness: EvalMetricRatio & {
    complete: number;
    terminal_attempts: number;
  };
  source_integrity: EvalMetricRatio & {
    valid: number;
    candidates: number;
  };
  false_approvals: EvalMetricRatio & {
    confirmed: number;
    oracle_approved_attempts: number;
  };
  human_overrides: EvalMetricRatio & {
    count: number;
    comparable_promotions: number;
  };
  accepted_regression_coverage: EvalMetricRatio & {
    covered: number;
    promoted: number;
  };
}

export interface Worker {
  id: string;
  task_id: string;
  description: string;
  model: string;
  agent_runtime?: AgentRuntime;
  /** @deprecated Compatibility alias for agent_runtime. */
  provider?: AgentRuntime;
  effort?: Effort | null;
  route_reason?: string | null;
  execution_envelope?: ExecutionEnvelope | null;
  status_snapshot?: StatusSnapshot;
  status: string;
  log_tail: string;           // raw string from server (split on \n to display)
  elapsed_s: number;
  last_commit: string | null;
  estimated_cost: number | null;
  oracle_result: string | null;
  pr_url: string | null;
  pid?: number | null;
  verified?: boolean;
  branch_name?: string | null;
}

export interface Session {
  session_id: string;
  name: string;
  path: string;               // server sends 'path', not 'project_dir'
  worker_count: number;
  running_count: number;
  alive: boolean;
  schedule: unknown;
}

export interface Idea {
  id: number;
  content: string;
  status: string;
  ai_evaluation: string | null;
  priority: string | null;
  source: string | null;
  created_at: string;
}

export interface GlobalSettings {
  max_workers: number;
  default_model: string;
  cost_budget: number;
  auto_start: boolean;
  auto_push: boolean;
  auto_merge: boolean;
  auto_review: boolean;
  auto_oracle: boolean;
  auto_scale: boolean;
  auto_model_routing: boolean;
  verifier_cascade_enabled: boolean;
  stuck_timeout_minutes: number;
  github_issues_sync: boolean;
  github_issues_label: string;
  min_workers: number;
  loop_supervisor_model: string;
  loop_max_iterations: number;
  notification_webhook: string;
  usage_provider: string;
  agent_runtime: AgentRuntime;
  /** @deprecated Compatibility alias for agent_runtime. */
  worker_provider?: AgentRuntime;
  runtime_connections: Record<AgentRuntime, string>;
  connections: Record<string, RuntimeConnection>;
  codex_cheap_model?: string;
  codex_strong_model?: string;
}

// ─── WebSocket Message Types ──────────────────────────────────────

export interface StatusMessage {
  type: 'status';
  session_id: string;
  queue: Task[];              // server sends 'queue', not 'tasks'
  workers: Worker[];          // server sends array, not Record
  loop_state: Record<string, unknown> | null;
  progress_pct: number | null;
  eta_seconds: number | null;
  success_rate: number | null;
  run_complete: boolean;
  budget_exceeded: boolean;
  budget_limit: number;
}

export type WsMessage = StatusMessage | { type: string; [key: string]: unknown };
