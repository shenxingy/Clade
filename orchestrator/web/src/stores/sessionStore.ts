import { create } from 'zustand';
import type { Task, Worker, Session, GlobalSettings } from '../lib/types';

interface SessionState {
  // Session management
  sessions: Session[];
  activeSessionId: string | null;
  setActiveSession: (id: string) => void;
  setSessions: (sessions: Session[]) => void;

  // Live data (updated via WebSocket)
  tasks: Task[];
  workers: Worker[];          // array, matching server's WS payload

  // Global settings and usage (fetched separately, not from WS)
  settings: GlobalSettings | null;
  costTotal: number;
  usage: { used_tokens: number; total_tokens: number; used_cost: number; total_cost: number } | null;

  // Worker log lines keyed by worker id (populated from log_tail each status tick)
  workerLogs: Record<string, string[]>;

  // Actions
  updateFromStatus: (tasks: Task[], workers: Worker[]) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessions: [],
  activeSessionId: null,
  setActiveSession: (id) => set({ activeSessionId: id }),
  setSessions: (sessions) => set({ sessions }),

  tasks: [],
  workers: [],
  settings: null,
  costTotal: 0,
  usage: null,
  workerLogs: {},

  updateFromStatus: (tasks, workers) => {
    // Rebuild workerLogs from each worker's log_tail snapshot
    const workerLogs: Record<string, string[]> = {};
    for (const w of workers) {
      workerLogs[w.id] = w.log_tail
        ? w.log_tail.split('\n').filter(l => l.trim())
        : [];
    }
    set({ tasks, workers, workerLogs });
  },
}));
