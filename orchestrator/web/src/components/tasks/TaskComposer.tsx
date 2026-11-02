import { useState, type FormEvent } from 'react';
import { tasks as api, errorMessage } from '../../lib/api';
import { useSessionStore } from '../../stores/sessionStore';
import { Modal } from '../shared/Modal';

export function TaskComposer({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const settings = useSessionStore(s => s.settings);
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || description.trim().length < 10) return;
    setBusy(true); setError('');
    try {
      const task = await api.add(sessionId, { description: description.trim() });
      const store = useSessionStore.getState();
      store.setTasks(sessionId, [...store.tasks.filter(t => t.id !== task.id), task]);
      onClose();
    } catch (error) { setError(errorMessage(error)); }
    finally { setBusy(false); }
  };
  return <Modal title="New task" onClose={onClose}>
    <form className="flow-form" onSubmit={submit}>
      <div className="field">
        <label htmlFor="task-description">What should the agent do?</label>
        <textarea id="task-description" className="ui-input" rows={6} required minLength={10}
          value={description} onChange={e => setDescription(e.target.value)} aria-describedby="task-help"
          placeholder="Describe the change, any constraints, and how to check that it works." />
        <p id="task-help" className="text-sm text-muted-foreground">Include an expected result and a way to verify it. At least 10 characters.</p>
      </div>
      <div className="text-sm text-muted-foreground space-y-2">
        <p>Uses your configured {settings?.agent_runtime === 'codex' ? 'Codex' : 'Claude Code'} agent and model routing.</p>
        <p>{settings?.auto_start
          ? 'Automatic execution is on. Adding this task allows an agent to start when capacity is available.'
          : 'Automatic execution is off. Add the task, then open it and choose Run task.'}</p>
        <p>Automatic push: {settings?.auto_push ? 'on' : 'off'} · Automatic merge: {settings?.auto_merge ? 'on' : 'off'}. You can change these in Settings before adding work.</p>
      </div>
      {error && <p role="alert" className="error-note">{error}</p>}
      <div className="form-actions">
        <button type="button" className="ui-button" onClick={onClose}>Cancel</button>
        <button className="ui-button ui-primary" disabled={busy || description.trim().length < 10}>
          {busy ? 'Adding…' : 'Add to queue'}
        </button>
      </div>
    </form>
  </Modal>;
}
