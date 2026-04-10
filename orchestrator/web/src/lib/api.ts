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
  list:        (sessionId: string)                     => req<unknown[]>('GET', `/tasks?session_id=${sessionId}`),
  add:         (sessionId: string, data: Record<string, unknown>) => req<unknown>('POST', '/tasks', { ...data, session_id: sessionId }),
  update:      (taskId: string, data: Record<string, unknown>)    => req<unknown>('POST', `/tasks/${taskId}`, data),
  delete:      (taskId: string)                        => req<void>('DELETE', `/tasks/${taskId}`),
  run:         (taskId: string)                        => req<unknown>('POST', `/tasks/${taskId}/run`),
  retry:       (taskId: string)                        => req<unknown>('POST', `/tasks/${taskId}/retry`),
  startAll:    (sessionId: string)                     => req<unknown>('POST', '/tasks/start-all', { session_id: sessionId }),
  retryFailed: (sessionId: string)                     => req<unknown>('POST', '/tasks/retry-failed', { session_id: sessionId }),
  mergeAllDone:(sessionId: string)                     => req<unknown>('POST', '/tasks/merge-all-done', { session_id: sessionId }),
  sendMessage: (taskId: string, content: string)       => req<unknown>('POST', `/tasks/${taskId}/messages`, { content }),
};

// ─── Workers ─────────────────────────────────────────────────────

export const workers = {
  list:   (sessionId: string) => req<unknown[]>('GET', `/workers?session_id=${sessionId}`),
  pause:  (workerId: string)  => req<unknown>('POST', `/workers/${workerId}/pause`),
  resume: (workerId: string)  => req<unknown>('POST', `/workers/${workerId}/resume`),
  stop:   (workerId: string)  => req<unknown>('POST', `/workers/${workerId}/stop`),
  log:    (workerId: string)  => req<string>('GET', `/workers/${workerId}/log`),
};

// ─── Ideas ───────────────────────────────────────────────────────

export const ideas = {
  list:    (sessionId: string)                   => req<unknown[]>('GET', `/ideas?session_id=${sessionId}`),
  add:     (sessionId: string, content: string)  => req<unknown>('POST', '/ideas', { session_id: sessionId, content }),
  delete:  (ideaId: number)                      => req<void>('DELETE', `/ideas/${ideaId}`),
  evaluate:(ideaId: number)                      => req<unknown>('POST', `/ideas/${ideaId}/evaluate`),
  execute: (ideaId: number)                      => req<unknown>('POST', `/ideas/${ideaId}/execute`),
};

// ─── Settings ────────────────────────────────────────────────────

export const settings = {
  get:    ()              => req<unknown>('GET', '/settings'),
  update: (data: unknown) => req<unknown>('POST', '/settings', data),
};
