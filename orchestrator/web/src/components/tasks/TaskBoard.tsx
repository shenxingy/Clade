import { useSessionStore } from '../../stores/sessionStore';
import { TaskCard } from './TaskCard';
import type { TaskStatus } from '../../lib/types';
import { Plus } from 'lucide-react';
import { useState } from 'react';
import { tasks as api } from '../../lib/api';

const COLUMNS: { status: TaskStatus; label: string; icon: string }[] = [
  { status: 'pending', label: 'Pending', icon: '●' },
  { status: 'running', label: 'Running', icon: '▶' },
  { status: 'done',    label: 'Done',    icon: '✓' },
  { status: 'failed',  label: 'Failed',  icon: '✗' },
];

export function TaskBoard() {
  const { tasks, activeSessionId } = useSessionStore();
  const [newTask, setNewTask] = useState('');
  const [adding, setAdding] = useState(false);

  const byStatus = (status: TaskStatus) => tasks.filter(t => t.status === status);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTask.trim() || !activeSessionId) return;
    setAdding(true);
    try {
      await api.add(activeSessionId, { description: newTask.trim(), model: 'sonnet' });
      setNewTask('');
    } catch (err) {
      console.error(err);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="flex-1 overflow-hidden flex flex-col gap-3 p-4">
      {/* Add task form */}
      <form onSubmit={handleAdd} className="flex gap-2">
        <input
          type="text"
          value={newTask}
          onChange={e => setNewTask(e.target.value)}
          placeholder="Add a task..."
          className="flex-1 px-3 py-1.5 text-sm rounded-lg bg-secondary border border-border focus:outline-none focus:border-accent text-foreground placeholder:text-muted-foreground"
        />
        <button
          type="submit"
          disabled={adding || !newTask.trim()}
          className="px-3 py-1.5 rounded-lg bg-accent hover:bg-accent/80 text-foreground text-sm flex items-center gap-1 disabled:opacity-50"
        >
          <Plus size={14} />
          Add
        </button>
      </form>

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
