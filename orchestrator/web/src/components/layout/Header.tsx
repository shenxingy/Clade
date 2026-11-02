import { useSessionStore } from '../../stores/sessionStore';
import { Plus, Settings } from 'lucide-react';

export function Header({ onSettingsOpen, onProjectOpen, ready }: {
  onSettingsOpen: () => void; onProjectOpen: () => void; ready: boolean;
}) {
  const { sessions, activeSessionId, setActiveSession } = useSessionStore();
  return <header className="app-header">
    <a href="#main-content" className="skip-link">Skip to workspace</a>
    <span className="brand"><span aria-hidden="true">◆</span> Clade</span>
    {ready && sessions.length > 0 && <>
      <label htmlFor="active-project" className="sr-only">Active project</label>
      <select id="active-project" className="ui-input project-select" value={activeSessionId ?? ''}
        onChange={e => setActiveSession(e.target.value)}>
        {sessions.map(s => <option key={s.session_id} value={s.session_id}>{s.name || s.path.split('/').pop()} — {s.path}</option>)}
      </select>
      <button className="ui-button" onClick={onProjectOpen}><Plus size={16} /><span>Open project</span></button>
    </>}
    <span className="flex-1" />
    {ready && <button onClick={onSettingsOpen} className="ui-button ui-icon" aria-label="Settings"><Settings size={18} /></button>}
  </header>;
}
