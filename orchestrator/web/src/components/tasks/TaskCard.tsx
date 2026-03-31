import { Task } from '../../lib/types';
import { StatusBadge } from '../shared/StatusBadge';
import { ModelBadge } from '../shared/ModelBadge';
import { formatDuration, formatCost, truncate, cn } from '../../lib/utils';
import { Trash2, Play, RotateCcw } from 'lucide-react';
import { tasks as api } from '../../lib/api';

interface Props {
  task: Task;
  onAction?: () => void;
}

export function TaskCard({ task, onAction }: Props) {
  const handleRun = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await api.run(task.id).catch(console.error);
    onAction?.();
  };

  const handleRetry = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await api.retry(task.id).catch(console.error);
    onAction?.();
  };

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this task?')) return;
    await api.delete(task.id).catch(console.error);
    onAction?.();
  };

  return (
    <div className={cn(
      'group px-3 py-2.5 rounded-lg border transition-colors cursor-pointer',
      'bg-card border-border hover:border-accent',
      task.status === 'running' && 'border-green-400/30 bg-green-400/5',
      task.status === 'failed'  && 'border-red-400/20',
    )}>
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
            {task.last_commit && (
              <span className="font-mono opacity-60">{task.last_commit.slice(0, 7)}</span>
            )}
          </div>
          {task.failed_reason && (
            <p className="mt-1 text-xs text-red-400 truncate">{truncate(task.failed_reason, 80)}</p>
          )}
        </div>
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {task.status === 'pending' && (
            <button onClick={handleRun} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Run">
              <Play size={12} />
            </button>
          )}
          {task.status === 'failed' && (
            <button onClick={handleRetry} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Retry">
              <RotateCcw size={12} />
            </button>
          )}
          <button onClick={handleDelete} className="p-1 rounded hover:bg-destructive/20 text-muted-foreground hover:text-red-400" title="Delete">
            <Trash2 size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}
