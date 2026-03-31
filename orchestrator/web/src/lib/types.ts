// ─── Core Types (mirrors FastAPI response shapes) ─────────────────

export type TaskStatus = 'pending' | 'running' | 'done' | 'failed' | 'paused';
export type TaskType = 'AUTO' | 'HORIZONTAL' | 'VERTICAL';

export interface Task {
  id: number;
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
  created_at: string;
  depends_on: number[];
  score: number | null;
  score_note: string | null;
  own_files: string[];
  forbidden_files: string[];
  gh_issue_number: number | null;
  is_critical_path: boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: number | null;
  task_type: TaskType;
  priority_score: number | null;
}

export interface Worker {
  worker_id: string;
  task_id: number;
  description: string;
  model: string;
  status: string;
  log_tail: string[];
  log_delta?: string[];
  elapsed_s: number;
  last_commit: string | null;
  estimated_cost: number | null;
  oracle_result: string | null;
  pr_url: string | null;
}

export interface Session {
  session_id: string;
  project_dir: string;
  created_at: string;
  worker_count: number;
  task_counts: {
    pending: number;
    running: number;
    done: number;
    failed: number;
  };
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
  tasks: Task[];
  workers: Record<string, Worker>;
  loop_state: Record<string, unknown> | null;
  settings: GlobalSettings;
  cost_total: number;
  usage?: {
    used_tokens: number;
    total_tokens: number;
    used_cost: number;
    total_cost: number;
  };
}

export type WsMessage = StatusMessage | { type: string; [key: string]: unknown };
