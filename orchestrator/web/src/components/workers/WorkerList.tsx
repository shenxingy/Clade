import { useSessionStore } from '../../stores/sessionStore';
import { WorkerCard } from './WorkerCard';

export function WorkerList() {
  const workers = useSessionStore(s => s.workers);
  const running = workers.filter(w => w.status === 'running' || w.status === 'paused');

  if (running.length === 0) {
    return (
      <div className="p-4 text-center text-xs text-muted-foreground">
        No active workers
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-4">
      {running.map(worker => (
        <WorkerCard key={worker.id} worker={worker} />
      ))}
    </div>
  );
}
