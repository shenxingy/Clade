// ─── Core Types (mirrors FastAPI response shapes) ─────────────────

export type TaskStatus = 'pending' | 'running' | 'done' | 'failed' | 'paused';
export type TaskType = 'AUTO' | 'HORIZONTAL' | 'VERTICAL';

export interface Task {
  id: string;
  description: string;
  model: string;
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

export interface Worker {
  id: string;
  task_id: string;
  description: string;
  model: string;
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
  cost_budget: number | null;
  auto_start: boolean;
  auto_scale: boolean;
  auto_oracle: boolean;
}

// ─── WebSocket Message Types ──────────────────────────────────────

export interface StatusMessage {
  type: 'status';
  session_id: string;
  queue: Task[];              // server sends 'queue', not 'tasks'
  workers: Worker[];          // server sends array, not Record
  loop_state: Record<string, unknown> | null;
  progress_pct: number;
  eta_seconds: number;
  success_rate: number;
  run_complete: boolean;
  budget_exceeded: boolean;
  budget_limit: number;
}

export type WsMessage = StatusMessage | { type: string; [key: string]: unknown };
