import { useSessionStore } from '../../stores/sessionStore';
import { TaskCard } from './TaskCard';
import type { TaskStatus } from '../../lib/types';

const COLUMNS: { status: TaskStatus; label: string; icon: string }[] = [
  { status: 'pending', label: 'Pending', icon: '●' },
  { status: 'running', label: 'Running', icon: '▶' },
  { status: 'done',    label: 'Done',    icon: '✓' },
  { status: 'failed',  label: 'Failed',  icon: '✗' },
];

export function TaskBoard() {
  const { tasks } = useSessionStore();

  const byStatus = (status: TaskStatus) => tasks.filter(t => t.status === status);

  return (
    <div className="flex-1 overflow-hidden flex flex-col gap-3 p-4">
      {/* Kanban columns */}
      <div className="flex-1 overflow-y-auto">
        {COLUMNS.map(col => {
          const colTasks = byStatus(col.status);
          if (col.status === 'done' && colTasks.length === 0) return null;
          return (
            <div key={col.status} className="mb-4">
              <div className="flex items-center gap-2 mb-2">
                <span className={`status-${col.status} text-xs`}>{col.icon}</span>
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  {col.label}
                </span>
                <span className="text-xs text-muted-foreground bg-secondary px-1.5 rounded-full">
                  {colTasks.length}
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                {colTasks.map(task => (
                  <TaskCard key={task.id} task={task} />
                ))}
                {colTasks.length === 0 && col.status === 'pending' && (
                  <p className="text-xs text-muted-foreground py-4 text-center">
                    No pending tasks
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
