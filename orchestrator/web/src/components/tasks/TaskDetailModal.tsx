import { useState, useEffect } from 'react';
import { X, FileText } from 'lucide-react';
import { Task } from '../../lib/types';
import { StatusBadge } from '../shared/StatusBadge';
import { ModelBadge } from '../shared/ModelBadge';
import { formatDuration, formatCost } from '../../lib/utils';
import { tasks as api } from '../../lib/api';

interface Props {
  task: Task | null;
  onClose: () => void;
}

export function TaskDetailModal({ task, onClose }: Props) {
  const [log, setLog] = useState<string | null>(null);
  const [logLoading, setLogLoading] = useState(false);

  useEffect(() => {
    if (!task) { setLog(null); return; }
    // Auto-load log for done/failed/interrupted tasks
    if (['done', 'failed'].includes(task.status) && task.log_file) {
      setLogLoading(true);
      api.log(task.id)
        .then(r => setLog(r.log))
        .catch(() => setLog('(error loading log)'))
        .finally(() => setLogLoading(false));
    } else {
      setLog(null);
    }
  }, [task?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!task) return null;

  const loadLog = () => {
    if (logLoading) return;
    setLogLoading(true);
    api.log(task.id)
      .then(r => setLog(r.log))
      .catch(() => setLog('(error loading log)'))
      .finally(() => setLogLoading(false));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-2xl max-h-[80vh] flex flex-col bg-background border border-border rounded-lg overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="flex items-start gap-3 px-4 py-3 border-b border-border shrink-0">
          <StatusBadge status={task.status} />
          <p className="flex-1 text-sm text-foreground leading-snug">{task.description}</p>
          <button onClick={onClose} className="p-1 rounded hover:bg-secondary text-muted-foreground shrink-0">
            <X size={14} />
          </button>
        </div>

        {/* Metadata grid */}
        <div className="px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-1.5 border-b border-border shrink-0">
          <Meta label="Model"><ModelBadge model={task.model} /></Meta>
          <Meta label="Task ID"><span className="font-mono text-xs">{task.id}</span></Meta>
          {task.elapsed_s != null && <Meta label="Duration">{formatDuration(task.elapsed_s)}</Meta>}
          {task.estimated_cost != null && <Meta label="Cost">{formatCost(task.estimated_cost)}</Meta>}
          {task.input_tokens != null && <Meta label="In tokens">{task.input_tokens.toLocaleString()}</Meta>}
          {task.output_tokens != null && <Meta label="Out tokens">{task.output_tokens.toLocaleString()}</Meta>}
          {task.last_commit && (
            <Meta label="Last commit">
              <span className="font-mono text-xs opacity-70">{task.last_commit.slice(0, 7)}</span>
            </Meta>
          )}
          {task.score != null && (
            <Meta label="Score">
              <span className={task.score >= 7 ? 'text-green-400' : task.score >= 4 ? 'text-yellow-400' : 'text-red-400'}>
                {task.score}/10
              </span>
            </Meta>
          )}
          {task.gh_issue_number && (
            <Meta label="GitHub issue">#{task.gh_issue_number}</Meta>
          )}
          {task.task_type && task.task_type !== 'AUTO' && (
            <Meta label="Type">{task.task_type}</Meta>
          )}
          {task.worker_id && (
            <Meta label="Worker"><span className="font-mono text-xs">{task.worker_id.slice(0, 8)}</span></Meta>
          )}
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
          {/* Score note */}
          {task.score_note && (
            <section>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Oracle note</p>
              <p className="text-xs text-foreground whitespace-pre-wrap">{task.score_note}</p>
            </section>
          )}

          {/* PR link */}
          {/* (pr_url lives on the Worker not the Task; shown if worker is available) */}

          {/* Failed reason */}
          {task.failed_reason && (
            <section>
              <p className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-1">Failure reason</p>
              <p className="text-xs text-red-300 whitespace-pre-wrap">{task.failed_reason}</p>
            </section>
          )}

          {/* Log */}
          <section className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Log</p>
              {!log && !logLoading && (
                <button
                  onClick={loadLog}
                  className="flex items-center gap-1 text-xs text-accent-foreground hover:text-foreground"
                >
                  <FileText size={11} /> Load log
                </button>
              )}
              {task.log_file && (
                <span className="text-xs text-muted-foreground font-mono opacity-50 truncate">{task.log_file}</span>
              )}
            </div>
            {logLoading && (
              <p className="text-xs text-muted-foreground">Loading…</p>
            )}
            {log && (
              <div className="bg-secondary rounded p-2 max-h-64 overflow-y-auto">
                <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap leading-relaxed">{log}</pre>
              </div>
            )}
            {!log && !logLoading && !task.log_file && (
              <p className="text-xs text-muted-foreground">(no log file)</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground w-24 shrink-0">{label}</span>
      <span className="text-xs text-foreground">{children}</span>
    </div>
  );
}
