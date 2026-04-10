import { useSessionStore } from '../../stores/sessionStore';
import { X, Settings } from 'lucide-react';
import { cn } from '../../lib/utils';

interface Props {
  onSettingsOpen: () => void;
}

export function Header({ onSettingsOpen }: Props) {
  const { sessions, activeSessionId, setActiveSession } = useSessionStore();

  return (
    <header className="h-14 border-b border-border flex items-center px-4 gap-4 shrink-0">
      <div className="flex items-center gap-2">
        <span className="text-primary font-bold text-lg">◆</span>
        <span className="font-bold text-foreground">Clade</span>
      </div>

      {/* Session tabs */}
      <div className="flex items-center gap-1 flex-1 overflow-x-auto">
        {sessions.map(session => {
          const name = session.path?.split('/').pop() ?? session.name ?? session.session_id.slice(0, 8);
          return (
            <button
              key={session.session_id}
              onClick={() => setActiveSession(session.session_id)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1 rounded text-xs font-mono whitespace-nowrap transition-colors',
                activeSessionId === session.session_id
                  ? 'bg-accent text-foreground'
                  : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
              )}
            >
              <span>{name}</span>
              <span
                className="text-muted-foreground/50 hover:text-destructive"
                onClick={(e) => {
                  e.stopPropagation();
                  // TODO: delete session
                }}
              >
                <X size={10} />
              </span>
            </button>
          );
        })}
      </div>

      <button onClick={onSettingsOpen} className="p-2 rounded hover:bg-secondary text-muted-foreground hover:text-foreground">
        <Settings size={16} />
      </button>
    </header>
  );
}
