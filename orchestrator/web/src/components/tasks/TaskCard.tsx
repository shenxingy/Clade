import { useState } from 'react';
import { Task } from '../../lib/types';
import { StatusBadge } from '../shared/StatusBadge';
import { ModelBadge } from '../shared/ModelBadge';
import { formatDuration, formatCost, truncate, cn } from '../../lib/utils';
import { useSessionStore } from '../../stores/sessionStore';
import { TaskDetailModal } from './TaskDetailModal';

interface Props {
  task: Task;
}

export function TaskCard({ task }: Props) {
  const [showDetail, setShowDetail] = useState(false);
  const activeSessionId = useSessionStore(s => s.activeSessionId) ?? '';

  return (
    <>
      <div
        className={cn(
          'px-3 py-2.5 rounded-lg border transition-colors cursor-pointer',
          'bg-card border-border hover:border-accent',
          task.status === 'running' && 'border-green-400/30 bg-green-400/5',
          task.status === 'failed'  && 'border-red-400/20',
        )}
        onClick={() => setShowDetail(true)}
      >
        <div className="flex items-start gap-2">
          <StatusBadge status={task.status} />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-foreground leading-snug truncate">
              {task.description}
            </p>
            <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
              <ModelBadge model={task.model} />
              {task.elapsed_s != null && (
                <span>{formatDuration(task.elapsed_s)}</span>
              )}
              {task.estimated_cost != null && (
                <span className="text-muted-foreground">{formatCost(task.estimated_cost)}</span>
              )}
              {task.score != null && (
                <span className={task.score >= 7 ? 'text-green-400' : task.score >= 4 ? 'text-yellow-400' : 'text-red-400'}>
                  {task.score}/10
                </span>
              )}
              {task.last_commit && (
                <span className="font-mono opacity-60">{task.last_commit.slice(0, 7)}</span>
              )}
            </div>
            {task.failed_reason && (
              <p className="mt-1 text-xs text-red-400 truncate">{truncate(task.failed_reason, 80)}</p>
            )}
          </div>
        </div>
      </div>

      <TaskDetailModal task={showDetail ? task : null} sessionId={activeSessionId} onClose={() => setShowDetail(false)} />
    </>
  );
}
