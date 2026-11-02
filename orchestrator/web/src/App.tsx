import { useEffect, useState, useCallback, useRef } from 'react';
import { FolderOpen } from 'lucide-react';
import { Header } from './components/layout/Header';
import { ProjectDialog } from './components/layout/ProjectDialog';
import { TaskBoard } from './components/tasks/TaskBoard';
import { WorkerList } from './components/workers/WorkerList';
import { PaneManager } from './components/terminal/PaneManager';
import { UsageBar } from './components/layout/UsageBar';
import { SettingsPanel } from './components/settings/SettingsPanel';
import { EvalDashboard } from './components/evals/EvalDashboard';
import { useWebSocket } from './hooks/useWebSocket';
import { useSessionStore } from './stores/sessionStore';
import { sessions as sessionsApi, settings as settingsApi, tasks as tasksApi, ApiError, errorMessage } from './lib/api';
import { setToken } from './lib/auth';
import type { StatusMessage, GlobalSettings } from './lib/types';

type ActiveTab = 'tasks' | 'workers' | 'evals' | 'terminal';

export default function App() {
  const { activeSessionId, setSessions, setActiveSession, setSettings, updateFromStatus } = useSessionStore();
  const [tab, setTab] = useState<ActiveTab>('tasks');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [needsToken, setNeedsToken] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [taskError, setTaskError] = useState('');
  const [tasksLoading, setTasksLoading] = useState(false);
  const loadedSession = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setLoadError('');
    Promise.all([sessionsApi.list(), settingsApi.get()]).then(([sessions, settings]) => {
      if (cancelled) return;
      setSessions(sessions); setSettings(settings as GlobalSettings);
      let previous: string | null = null;
      try { previous = localStorage.getItem('clade.activeSession'); } catch { /* Optional storage. */ }
      const selected = sessions.find(s => s.session_id === previous) ?? sessions[0];
      setActiveSession(selected?.session_id ?? null);
      setNeedsToken(false);
    }).catch(error => {
      if (cancelled) return;
      setLoadError(errorMessage(error));
      setNeedsToken(error instanceof ApiError && (error.status === 401 || error.status === 403));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [attempt, setSessions, setActiveSession, setSettings]);

  const handleStatus = useCallback((msg: StatusMessage) => {
    if (useSessionStore.getState().activeSessionId !== msg.session_id) return;
    updateFromStatus(msg.queue, msg.workers, msg.budget_limit);
  }, [updateFromStatus]);
  const { connected } = useWebSocket({ sessionId: loadError ? null : activeSessionId, onStatus: handleStatus });

  useEffect(() => {
    if (!activeSessionId) return;
    let cancelled = false;
    let inFlight = false;
    setTasksLoading(loadedSession.current !== activeSessionId); setTaskError('');
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const tasks = await tasksApi.list(activeSessionId);
        if (!cancelled) {
          useSessionStore.getState().setTasks(activeSessionId, tasks);
          setTaskError('');
        }
      } catch (error) { if (!cancelled) setTaskError(errorMessage(error)); }
      finally {
        inFlight = false;
        if (!cancelled) { loadedSession.current = activeSessionId; setTasksLoading(false); }
      }
    };
    void refresh();
    // Keep the queue usable while the live connection reconnects.
    const poll = !connected ? setInterval(refresh, 5_000) : undefined;
    return () => { cancelled = true; clearInterval(poll); };
  }, [activeSessionId, connected, attempt]);

  return <div className="app-shell">
    <Header onSettingsOpen={() => setSettingsOpen(true)} onProjectOpen={() => setProjectOpen(true)}
      ready={!loading && !loadError} />
    <main id="main-content" className="workspace-main">
      {loading ? <div className="welcome" role="status">Connecting to Clade…</div>
        : loadError ? <div className="welcome">
          <p className="eyebrow">Connection</p>
          <h1>{needsToken ? 'Connect to your workspace' : 'Clade is unavailable'}</h1>
          <p className="prose-copy text-muted-foreground">{needsToken
            ? 'Open the sign-in link printed when Clade starts, or enter its access token below.'
            : 'Check that Clade is running, then try again. Your projects are still on your computer.'}</p>
          <p className="error-note" role="alert">{loadError}</p>
          <form className="flow-form" onSubmit={e => {
            e.preventDefault();
            if (needsToken) { setToken(tokenInput.trim()); setTokenInput(''); }
            setAttempt(n => n + 1);
          }}>
            {needsToken && <div className="field"><label htmlFor="access-token">Access token</label>
              <input id="access-token" type="password" autoComplete="off" className="ui-input" required
                value={tokenInput} onChange={e => setTokenInput(e.target.value)} /></div>}
            <button className="ui-button ui-primary">{needsToken ? 'Connect' : 'Try again'}</button>
          </form>
        </div>
        : !activeSessionId ? <div className="welcome">
          <p className="eyebrow">Your local workspace</p>
          <h1>From a task to<br />work you can review.</h1>
          <p className="prose-copy text-muted-foreground">Open a project, describe what you need, and follow your coding agents here. Your repository stays on your computer.</p>
          <button className="ui-button ui-primary self-start" onClick={() => setProjectOpen(true)}><FolderOpen size={18} />Open project</button>
          <ol className="welcome-steps">
            <li><span>01</span><strong>Choose a project</strong><p>Connect an existing folder.</p></li>
            <li><span>02</span><strong>Describe the work</strong><p>Add a task and its expected result.</p></li>
            <li><span>03</span><strong>Review the outcome</strong><p>Inspect progress, logs and evidence.</p></li>
          </ol>
          <p className="text-sm text-muted-foreground">You can keep using your terminal alongside this workspace.</p>
        </div>
        : <>
          <nav className="workspace-tabs" aria-label="Project views">
            {(['tasks', 'workers', 'evals', 'terminal'] as ActiveTab[]).map(t => <button key={t}
              onClick={() => setTab(t)} aria-current={tab === t ? 'page' : undefined}
              className={tab === t ? 'selected' : ''}>{t === 'evals' ? 'Evidence' : t === 'workers' ? 'Agents' : t === 'tasks' ? 'Tasks' : 'Terminal'}</button>)}
            <span className="connection-state" role="status">{connected ? 'Live' : 'Reconnecting · queue refreshes every 5s'}</span>
          </nav>
          <div className={`workspace-content ${tab === 'terminal' ? 'terminal-content' : ''}`} key={activeSessionId}>
            {taskError && <div className="error-banner" role="alert">{taskError}<button className="ui-button" onClick={() => setAttempt(n => n + 1)}>Reconnect</button></div>}
            {tab === 'tasks' && (tasksLoading ? <p className="p-6 text-muted-foreground" role="status">Loading tasks…</p> : <TaskBoard />)}
            {tab === 'workers' && <WorkerList />}
            {tab === 'evals' && <EvalDashboard />}
            {tab === 'terminal' && <PaneManager />}
          </div>
        </>}
    </main>
    <UsageBar />
    {projectOpen && <ProjectDialog onClose={() => { setProjectOpen(false); setTab('tasks'); }} />}
    <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
  </div>;
}
