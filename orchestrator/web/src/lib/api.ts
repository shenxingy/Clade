// ─── API Base ─────────────────────────────────────────────────────

const BASE = '/api';

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${method} ${path}: ${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

// ─── Sessions ────────────────────────────────────────────────────

export const sessions = {
  list:   ()                    => req<unknown[]>('GET', '/sessions'),
  create: (path: string)        => req<unknown>('POST', '/sessions', { path }),
  delete: (sessionId: string)   => req<void>('DELETE', `/sessions/${sessionId}`),
};

// ─── Tasks (task IDs are strings, e.g. "85c92be0") ───────────────

export const tasks = {
  list:        (sessionId: string)                     => req<unknown[]>('GET', `/tasks?session=${sessionId}`),
  add:         (sessionId: string, data: Record<string, unknown>) => req<unknown>('POST', `/tasks?session=${sessionId}`, data),
  update:      (taskId: string, sessionId: string, data: Record<string, unknown>) => req<unknown>('POST', `/tasks/${taskId}?session=${sessionId}`, data),
  delete:      (taskId: string, sessionId: string)     => req<void>('DELETE', `/tasks/${taskId}?session=${sessionId}`),
  run:         (taskId: string, sessionId: string)     => req<unknown>('POST', `/tasks/${taskId}/run?session=${sessionId}`),
  retry:       (taskId: string, sessionId: string)     => req<unknown>('POST', `/tasks/${taskId}/retry?session=${sessionId}`),
  startAll:    (sessionId: string)                     => req<unknown>('POST', `/tasks/start-all?session=${sessionId}`),
  retryFailed: (sessionId: string)                     => req<unknown>('POST', `/tasks/retry-failed?session=${sessionId}`),
  mergeAllDone:(sessionId: string)                     => req<unknown>('POST', `/tasks/merge-all-done?session=${sessionId}`),
  sendMessage: (taskId: string, sessionId: string, content: string) => req<unknown>('POST', `/tasks/${taskId}/messages?session=${sessionId}`, { content }),
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

// ─── Settings ────────────────────────────────────────────────────

export const settings = {
  get:    ()              => req<unknown>('GET', '/settings'),
  update: (data: unknown) => req<unknown>('POST', '/settings', data),
};
