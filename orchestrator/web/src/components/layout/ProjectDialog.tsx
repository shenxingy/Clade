import { useState, type FormEvent } from 'react';
import { sessions as api, errorMessage } from '../../lib/api';
import { useSessionStore } from '../../stores/sessionStore';
import { Modal } from '../shared/Modal';

export function ProjectDialog({ onClose }: { onClose: () => void }) {
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || !path.trim()) return;
    setBusy(true); setError('');
    try {
      const store = useSessionStore.getState();
      const existing = store.sessions.find(s => s.path.replace(/\/$/, '') === path.trim().replace(/\/$/, ''));
      const session = existing ?? await api.create(path.trim());
      const current = useSessionStore.getState();
      if (!current.sessions.some(s => s.session_id === session.session_id)) {
        current.setSessions([...current.sessions, session]);
      }
      current.setActiveSession(session.session_id);
      onClose();
    } catch (error) { setError(errorMessage(error)); }
    finally { setBusy(false); }
  };
  return <Modal title="Open a project" onClose={onClose}>
    <form onSubmit={submit} className="flow-form">
      <p className="prose-copy text-muted-foreground">Choose an existing project folder on the computer running Clade. Your tasks and agents stay with this project.</p>
      <div className="field">
        <label htmlFor="project-path">Project folder</label>
        <input id="project-path" className="ui-input" value={path} onChange={e => setPath(e.target.value)} required
          placeholder="/path/to/your/project" autoComplete="off" spellCheck={false} aria-describedby="project-help" />
        <p id="project-help" className="text-sm text-muted-foreground">Use the full folder path, or a path starting with ~/. Opening starts the project’s configured agent session.</p>
      </div>
      {error && <p role="alert" className="error-note">{error}</p>}
      <div className="form-actions">
        <button type="button" className="ui-button" onClick={onClose}>Cancel</button>
        <button className="ui-button ui-primary" disabled={busy || !path.trim()}>{busy ? 'Opening…' : 'Open project'}</button>
      </div>
    </form>
  </Modal>;
}
