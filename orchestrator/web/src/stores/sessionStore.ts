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
  workers: Record<string, Worker>;
  settings: GlobalSettings | null;
  costTotal: number;
  usage: { used_tokens: number; total_tokens: number; used_cost: number; total_cost: number } | null;

  // Actions
  updateFromStatus: (tasks: Task[], workers: Record<string, Worker>, settings: GlobalSettings, costTotal: number, usage?: { used_tokens: number; total_tokens: number; used_cost: number; total_cost: number }) => void;

  // Worker log accumulation
  workerLogs: Record<string, string[]>;
  appendWorkerLog: (workerId: string, lines: string[]) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessions: [],
  activeSessionId: null,
  setActiveSession: (id) => set({ activeSessionId: id }),
  setSessions: (sessions) => set({ sessions }),

  tasks: [],
  workers: {},
  settings: null,
  costTotal: 0,
  usage: null,

  updateFromStatus: (tasks, workers, settings, costTotal, usage) =>
    set({ tasks, workers, settings, costTotal, usage: usage ?? null }),

  workerLogs: {},
  appendWorkerLog: (workerId, lines) =>
    set((state) => ({
      workerLogs: {
        ...state.workerLogs,
        [workerId]: [...(state.workerLogs[workerId] ?? []).slice(-500), ...lines],
      },
    })),
}));
