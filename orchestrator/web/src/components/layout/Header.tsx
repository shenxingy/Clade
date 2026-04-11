import { useState } from 'react';
import { useSessionStore } from '../../stores/sessionStore';
import { X, Settings, Plus } from 'lucide-react';
import { cn } from '../../lib/utils';
import { sessions as sessionsApi } from '../../lib/api';
import type { Session } from '../../lib/types';

interface Props {
  onSettingsOpen: () => void;
}

export function Header({ onSettingsOpen }: Props) {
  const { sessions, activeSessionId, setActiveSession, setSessions } = useSessionStore();
  const [adding, setAdding] = useState(false);
  const [newPath, setNewPath] = useState('');

  const deleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    await sessionsApi.delete(sessionId).catch(console.error);
    const updated = sessions.filter(s => s.session_id !== sessionId);
    setSessions(updated);
    if (activeSessionId === sessionId && updated.length > 0) {
      setActiveSession(updated[0].session_id);
    }
  };

  const addSession = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPath.trim()) return;
    try {
      const s = await sessionsApi.create(newPath.trim()) as Session;
      setSessions([...sessions, s]);
      setActiveSession(s.session_id);
      setNewPath('');
      setAdding(false);
    } catch (err) {
      console.error(err);
    }
  };

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
                onClick={(e) => deleteSession(e, session.session_id)}
                title="Close session"
              >
                <X size={10} />
              </span>
            </button>
          );
        })}

        {/* Add session */}
        {adding ? (
          <form onSubmit={addSession} className="flex items-center gap-1">
            <input
              autoFocus
              type="text"
              value={newPath}
              onChange={e => setNewPath(e.target.value)}
              onKeyDown={e => e.key === 'Escape' && setAdding(false)}
              placeholder="/path/to/project"
              className="px-2 py-0.5 text-xs rounded bg-secondary border border-border focus:outline-none focus:border-accent text-foreground placeholder:text-muted-foreground w-48"
            />
            <button type="submit" className="px-2 py-0.5 text-xs rounded bg-accent hover:bg-accent/80 text-foreground">Add</button>
            <button type="button" onClick={() => setAdding(false)} className="px-1.5 py-0.5 text-xs rounded hover:bg-secondary text-muted-foreground">✕</button>
          </form>
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            title="Add project session"
          >
            <Plus size={10} />
          </button>
        )}
      </div>

      <button onClick={onSettingsOpen} className="p-2 rounded hover:bg-secondary text-muted-foreground hover:text-foreground">
        <Settings size={16} />
      </button>
    </header>
  );
}
