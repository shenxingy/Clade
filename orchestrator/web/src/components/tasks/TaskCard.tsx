import type { Task } from '../../lib/types';
import { ArrowUpRight } from 'lucide-react';
import { StatusBadge } from '../shared/StatusBadge';
import { formatDuration, formatCost } from '../../lib/utils';

export function TaskCard({ task, onOpen }: { task: Task; onOpen: () => void }) {
  return <button className="task-row" onClick={onOpen}>
    <StatusBadge status={task.status} />
    <span className="task-row-content">
      <span className="task-description">{task.description}</span>
      <span className="task-meta">
        <span>{task.model}</span>
        {task.elapsed_s != null && <span>{formatDuration(task.elapsed_s)}</span>}
        {task.estimated_cost != null && <span>{formatCost(task.estimated_cost)}</span>}
        {task.last_commit && <span className="font-mono">{task.last_commit.slice(0, 7)}</span>}
      </span>
      {task.failed_reason && <span className="text-sm text-red-300 line-clamp-2">{task.failed_reason}</span>}
    </span>
    <ArrowUpRight size={16} className="text-muted-foreground shrink-0" aria-hidden="true" />
  </button>;
}
