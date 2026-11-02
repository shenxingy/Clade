import { useState, useEffect } from 'react';
import type { EvidenceBundle, Task } from '../../lib/types';
import { StatusBadge } from '../shared/StatusBadge';
import { Modal } from '../shared/Modal';
import { formatDuration, formatCost } from '../../lib/utils';
import { tasks as api, errorMessage } from '../../lib/api';
import { useSessionStore } from '../../stores/sessionStore';

export function TaskDetailModal({ task, sessionId, onClose }: {
  task: Task | null; sessionId: string; onClose: () => void;
}) {
  const [log, setLog] = useState<string | null>(null);
  const [attempts, setAttempts] = useState<EvidenceBundle[]>([]);
  const [loading, setLoading] = useState(false);
  const [readError, setReadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [notice, setNotice] = useState('');
  const worker = useSessionStore(s => s.workers.find(w => w.id === task?.worker_id));

  useEffect(() => {
    if (!task) return;
    let cancelled = false;
    setLoading(true); setReadError(''); setLog(null); setAttempts([]);
    Promise.allSettled([api.evidence(task.id, sessionId), api.log(task.id, sessionId)])
      .then(([evidence, logResult]) => {
        if (cancelled) return;
        if (evidence.status === 'fulfilled') setAttempts(evidence.value.attempts);
        if (logResult.status === 'fulfilled') setLog(logResult.value.log);
        const errors = [evidence, logResult].filter(r => r.status === 'rejected');
        setReadError(errors.map(r => errorMessage((r as PromiseRejectedResult).reason)).join(' '));
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [task?.id, task?.status, task?.last_commit, sessionId, refresh]);

  if (!task) return null;
  const canRun = ['pending', 'queued'].includes(task.status);
  const canRetry = ['failed', 'blocked', 'interrupted'].includes(task.status);
  const act = async () => {
    if (busy) return;
    setBusy(true); setActionError(''); setNotice('');
    try {
      if (canRetry) await api.retry(task.id, sessionId);
      else await api.run(task.id, sessionId);
      setNotice(canRetry ? 'Task returned to the queue.' : 'Execution requested. Waiting for agent status.');
      const tasks = await api.list(sessionId);
      useSessionStore.getState().setTasks(sessionId, tasks);
    } catch (error) { setActionError(errorMessage(error)); }
    finally { setBusy(false); }
  };
  return <Modal title="Task details" onClose={onClose}>
    <div className="flow-form">
      <div className="flex flex-wrap items-center gap-3"><StatusBadge status={task.status} />
        <span className="text-sm text-muted-foreground font-mono">{task.id}</span></div>
      <p className="whitespace-pre-wrap break-words">{task.description}</p>
      {(canRun || canRetry) && <div className="flex flex-wrap items-center gap-3">
        <button className="ui-button ui-primary" disabled={busy} onClick={act}>
          {busy ? 'Updating…' : canRetry ? 'Retry task' : 'Run task'}
        </button>
        <span className="text-sm text-muted-foreground">{canRetry ? 'Returns this task to the queue.' : 'Starts an agent for this task.'}</span>
      </div>}
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {actionError && <p role="alert" className="error-note">{actionError}</p>}
      <dl className="task-facts">
        <div><dt>Agent</dt><dd>{task.agent_runtime ?? 'Configured default'}</dd></div>
        <div><dt>Model</dt><dd>{task.model}</dd></div>
        {task.elapsed_s != null && <div><dt>Duration</dt><dd>{formatDuration(task.elapsed_s)}</dd></div>}
        {task.estimated_cost != null && <div><dt>Estimated cost</dt><dd>{formatCost(task.estimated_cost)}</dd></div>}
        {task.last_commit && <div><dt>Commit</dt><dd className="font-mono break-all">{task.last_commit}</dd></div>}
      </dl>
      <details className="evidence-details"><summary>Execution details</summary>
        <dl className="task-facts mt-3">
          {task.effort && <div><dt>Effort</dt><dd>{task.effort}</dd></div>}
          {task.route_reason && <div><dt>Routing</dt><dd>{task.route_reason}</dd></div>}
          {task.score != null && <div><dt>Readiness score</dt><dd>{task.score}</dd></div>}
          {task.gh_issue_number && <div><dt>GitHub issue</dt><dd>#{task.gh_issue_number}</dd></div>}
          {task.input_tokens != null && <div><dt>Input tokens</dt><dd>{task.input_tokens.toLocaleString()}</dd></div>}
          {task.output_tokens != null && <div><dt>Output tokens</dt><dd>{task.output_tokens.toLocaleString()}</dd></div>}
        </dl>
        {task.execution_envelope && <pre className="mt-3">{JSON.stringify(task.execution_envelope, null, 2)}</pre>}
      </details>
      {task.failed_reason && <section><h2 className="section-title">What needs attention</h2>
        <p className="error-note whitespace-pre-wrap">{task.failed_reason}</p></section>}
      {task.score_note && <section><h2 className="section-title">Review notes</h2>
        <p className="text-sm whitespace-pre-wrap">{task.score_note}</p></section>}
      {worker?.pr_url && /^https:\/\//.test(worker.pr_url) && <a className="ui-button self-start" href={worker.pr_url}
        target="_blank" rel="noreferrer">Review pull request ↗</a>}
      <section>
        <div className="flex items-center justify-between gap-3"><h2 className="section-title">Results and evidence</h2>
          <button className="ui-button" disabled={loading} onClick={() => setRefresh(n => n + 1)}>{loading ? 'Loading…' : 'Refresh results'}</button></div>
        {task.status === 'done' && <p className="text-sm text-muted-foreground mt-3">Execution is complete. Check the recorded evidence before accepting or publishing the work.</p>}
        {readError && <p className="error-note mt-3" role="alert">{readError} Use Refresh results to try again.</p>}
        {!loading && attempts.length === 0 && <p className="text-sm text-muted-foreground mt-3">No verification evidence recorded yet.</p>}
        <div className="flex flex-col gap-3 mt-3">{attempts.map(attempt => <details key={attempt.attempt_id} className="evidence-details">
          <summary>Attempt {attempt.attempt_index} · {attempt.lifecycle_state}</summary>
          <p className="text-xs text-muted-foreground break-all">Revision {attempt.revision} · {attempt.digest}</p>
          {attempt.redaction_metadata?.count > 0 && <p className="text-xs text-muted-foreground">{attempt.redaction_metadata.count} fields redacted</p>}
          <pre>{JSON.stringify(attempt.evidence, null, 2)}</pre>
        </details>)}</div>
      </section>
      <section><h2 className="section-title">Execution log</h2>
        {loading ? <p className="text-sm text-muted-foreground" role="status">Loading results…</p>
          : log ? <pre className="execution-log">{log}</pre>
          : <p className="text-sm text-muted-foreground">No log output yet.</p>}
      </section>
    </div>
  </Modal>;
}
