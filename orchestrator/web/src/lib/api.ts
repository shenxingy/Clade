import { authHeaders } from './auth';
import type {
  Session,
  Task,
  EvalMetrics,
  EvidenceAttemptsResponse,
  ProviderRegistrySnapshot,
} from './types';

// ─── API Base ─────────────────────────────────────────────────────

const BASE = '/api';

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      ...authHeaders(),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail) && detail.every(item => typeof item === 'string') ? detail.join('. ')
      : `Request failed (${res.status}). Please try again.`;
    throw new ApiError(message, res.status);
  }
  // Action endpoints can report a refusal in a successful HTTP response.
  if (typeof data?.error === 'string') throw new ApiError(data.error, res.status);
  return data as T;
}

// ─── Sessions ────────────────────────────────────────────────────

export const sessions = {
  list:   ()                    => req<Session[]>('GET', '/sessions'),
  create: (path: string)        => req<Session>('POST', '/sessions', { path, reuse_existing: true }),
  delete: (sessionId: string)   => req<void>('DELETE', `/sessions/${sessionId}`),
};

// ─── Tasks (task IDs are strings, e.g. "85c92be0") ───────────────

export const tasks = {
  list:        (sessionId: string)                     => req<Task[]>('GET', `/tasks?session=${sessionId}`),
  add:         (sessionId: string, data: Record<string, unknown>) => req<Task>('POST', `/tasks?session=${sessionId}`, data),
  update:      (taskId: string, sessionId: string, data: Record<string, unknown>) => req<unknown>('POST', `/tasks/${taskId}?session=${sessionId}`, data),
  delete:      (taskId: string, sessionId: string)     => req<void>('DELETE', `/tasks/${taskId}?session=${sessionId}`),
  run:         (taskId: string, sessionId: string)     => req<unknown>('POST', `/tasks/${taskId}/run?session=${sessionId}`),
  retry:       (taskId: string, sessionId: string)     => req<unknown>('POST', `/tasks/${taskId}/retry?session=${sessionId}`),
  startAll:    (sessionId: string)                     => req<unknown>('POST', `/tasks/start-all?session=${sessionId}`),
  retryFailed: (sessionId: string)                     => req<unknown>('POST', `/tasks/retry-failed?session=${sessionId}`),
  mergeAllDone:(sessionId: string)                     => req<unknown>('POST', `/tasks/merge-all-done?session=${sessionId}`),
  sendMessage: (taskId: string, sessionId: string, content: string) => req<unknown>('POST', `/tasks/${taskId}/messages?session=${sessionId}`, { content }),
  evidence:    (taskId: string, sessionId: string)     => req<EvidenceAttemptsResponse>('GET', `/tasks/${taskId}/evidence?session=${sessionId}`),
  log:         (taskId: string, sessionId: string)     => req<{ log: string; path?: string }>('GET', `/tasks/${taskId}/log?session=${sessionId}`),
};

// ─── Workers ─────────────────────────────────────────────────────

export const workers = {
  list:   (sessionId: string) => req<unknown[]>('GET', `/workers?session=${sessionId}`),
  pause:  (workerId: string, sessionId: string)  => req<unknown>('POST', `/workers/${workerId}/pause?session=${sessionId}`),
  resume: (workerId: string, sessionId: string)  => req<unknown>('POST', `/workers/${workerId}/resume?session=${sessionId}`),
  stop:   (workerId: string, sessionId: string)  => req<unknown>('POST', `/workers/${workerId}/stop?session=${sessionId}`),
  log:    (workerId: string, sessionId: string)  => req<{ log: string; path?: string }>('GET', `/workers/${workerId}/log?session=${sessionId}`),
};

// ─── Ideas ───────────────────────────────────────────────────────

export const ideas = {
  list:    (sessionId: string)                   => req<unknown[]>('GET', `/ideas?session=${sessionId}`),
  add:     (sessionId: string, content: string)  => req<unknown>('POST', `/ideas?session=${sessionId}`, { content }),
  delete:  (ideaId: number, sessionId: string)   => req<void>('DELETE', `/ideas/${ideaId}?session=${sessionId}`),
  evaluate:(ideaId: number, sessionId: string)   => req<unknown>('POST', `/ideas/${ideaId}/evaluate?session=${sessionId}`),
  execute: (ideaId: number, sessionId: string)   => req<unknown>('POST', `/ideas/${ideaId}/execute?session=${sessionId}`),
};

export const evals = {
  metrics: (sessionId: string) =>
    req<EvalMetrics>('GET', `/eval-candidates/metrics?session=${sessionId}`),
};

// ─── Settings ────────────────────────────────────────────────────

export const settings = {
  get:    ()              => req<unknown>('GET', '/settings'),
  update: (data: unknown) => req<unknown>('POST', '/settings', data),
};

export const providerRegistry = {
  get:     () => req<ProviderRegistrySnapshot>('GET', '/provider-registry'),
  refresh: () => req<ProviderRegistrySnapshot>('POST', '/provider-registry/refresh'),
};
