import { useSessionStore } from '../../stores/sessionStore';

export function Sidebar() {
  const { tasks } = useSessionStore();

  const counts = {
    pending: tasks.filter(t => t.status === 'pending').length,
    running: tasks.filter(t => t.status === 'running').length,
    done:    tasks.filter(t => t.status === 'done').length,
    failed:  tasks.filter(t => t.status === 'failed').length,
  };

  return (
    <aside className="w-[200px] border-r border-border flex flex-col shrink-0">
      <nav className="p-3 flex flex-col gap-1">
        <div className="px-2 py-1 text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
          Queue
        </div>
        {[
          { label: 'Pending', count: counts.pending, color: 'text-yellow-400', icon: '●' },
          { label: 'Running', count: counts.running, color: 'text-green-400',  icon: '▶' },
          { label: 'Done',    count: counts.done,    color: 'text-slate-400',  icon: '✓' },
          { label: 'Failed',  count: counts.failed,  color: 'text-red-400',    icon: '✗' },
        ].map(item => (
          <div key={item.label} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-secondary cursor-pointer">
            <span className={`${item.color} text-xs`}>{item.icon}</span>
            <span className="text-sm text-muted-foreground flex-1">{item.label}</span>
            <span className="text-xs text-muted-foreground bg-secondary px-1.5 rounded-full">
              {item.count}
            </span>
          </div>
        ))}
      </nav>
    </aside>
  );
}
