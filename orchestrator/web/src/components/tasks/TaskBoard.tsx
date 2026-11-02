import { useState } from 'react';
import { Plus } from 'lucide-react';
import { useSessionStore } from '../../stores/sessionStore';
import { TaskCard } from './TaskCard';
import { TaskComposer } from './TaskComposer';
import { TaskDetailModal } from './TaskDetailModal';
import type { TaskStatus } from '../../lib/types';

const GROUPS: { label: string; statuses: TaskStatus[] }[] = [
  { label: 'Needs attention', statuses: ['failed', 'blocked', 'interrupted', 'paused'] },
  { label: 'In progress', statuses: ['starting', 'running'] },
  { label: 'Queued', statuses: ['pending', 'queued'] },
  { label: 'Completed', statuses: ['done'] },
  { label: 'Cancelled', statuses: ['cancelled'] },
];

export function TaskBoard() {
  const { tasks, sessions, activeSessionId, settings } = useSessionStore();
  const [composing, setComposing] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const session = sessions.find(s => s.session_id === activeSessionId);
  const known = new Set(GROUPS.flatMap(group => group.statuses));
  const groups = [...GROUPS, { label: 'Other tasks', statuses: tasks.map(t => t.status).filter(s => !known.has(s)) }];
  return <div className="task-workspace">
    <div className="board-heading">
      <div className="min-w-0">
        <p className="eyebrow">Project workspace</p>
        <h1>{session?.name || session?.path.split('/').pop() || 'Tasks'}</h1>
        <p className="text-sm text-muted-foreground break-all">{session?.path}</p>
      </div>
      <button className="ui-button ui-primary" onClick={() => setComposing(true)}><Plus size={18} />New task</button>
    </div>
    <div className="queue-summary">
      <span>{tasks.length} {tasks.length === 1 ? 'task' : 'tasks'}</span>
      <span>{settings?.auto_start ? 'Automatic execution on' : 'Manual execution'}</span>
      <span>{settings?.agent_runtime === 'codex' ? 'Codex' : 'Claude Code'}</span>
    </div>
    {tasks.length === 0 ? <section className="empty-queue">
      <h2>What would you like to work on?</h2>
      <p className="prose-copy text-muted-foreground">Use New task to describe a fix, feature or review. Include what a successful result should look like.</p>
      <p className="text-sm text-muted-foreground">Progress and results will appear here. Open any task to inspect its logs and verification evidence.</p>
    </section> : groups.map(group => {
      const items = tasks.filter(t => group.statuses.includes(t.status));
      if (!items.length) return null;
      return <section className="task-group" key={group.label} aria-label={group.label}>
        <h2>{group.label}<span>{items.length}</span></h2>
        <div className="task-list">{items.map(task => <TaskCard key={task.id} task={task} onOpen={() => setSelectedId(task.id)} />)}</div>
      </section>;
    })}
    {composing && activeSessionId && <TaskComposer sessionId={activeSessionId} onClose={() => setComposing(false)} />}
    {selectedId && activeSessionId && <TaskDetailModal task={tasks.find(t => t.id === selectedId) ?? null}
      sessionId={activeSessionId} onClose={() => setSelectedId(null)} />}
  </div>;
}
