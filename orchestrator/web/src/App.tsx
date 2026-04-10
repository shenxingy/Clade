import { useEffect, useState, useCallback } from 'react';
import { Header } from './components/layout/Header';
import { Sidebar } from './components/layout/Sidebar';
import { TaskBoard } from './components/tasks/TaskBoard';
import { WorkerList } from './components/workers/WorkerList';
import { PaneManager } from './components/terminal/PaneManager';
import { UsageBar } from './components/layout/UsageBar';
import { SettingsPanel } from './components/settings/SettingsPanel';
import { useWebSocket } from './hooks/useWebSocket';
import { useSessionStore } from './stores/sessionStore';
import { sessions as sessionsApi, settings as settingsApi } from './lib/api';
import type { StatusMessage, Session, GlobalSettings } from './lib/types';

type ActiveTab = 'tasks' | 'workers' | 'terminal';

export default function App() {
  const {
    activeSessionId,
    setSessions,
    setActiveSession,
    setSettings,
    updateFromStatus,
  } = useSessionStore();

  const [tab, setTab] = useState<ActiveTab>('tasks');
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Load sessions and settings on mount
  useEffect(() => {
    sessionsApi.list().then((data) => {
      const typed = data as Session[];
      setSessions(typed);
      if (typed.length > 0 && !activeSessionId) {
        setActiveSession(typed[0].session_id);
      }
    }).catch(console.error);

    settingsApi.get().then(data => setSettings(data as GlobalSettings)).catch(console.error);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Handle WebSocket status messages
  const handleStatus = useCallback((msg: StatusMessage) => {
    updateFromStatus(msg.queue, msg.workers, msg.budget_limit);
  }, [updateFromStatus]);

  const { connected } = useWebSocket({ sessionId: activeSessionId, onStatus: handleStatus });

  return (
    <div className="h-screen flex flex-col bg-background text-foreground overflow-hidden">
      <Header onSettingsOpen={() => setSettingsOpen(true)} />

      <div className="flex-1 flex overflow-hidden">
        <Sidebar />

        <main className="flex-1 flex flex-col overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-border px-4 gap-0 shrink-0">
            {(['tasks', 'workers', 'terminal'] as ActiveTab[]).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2 text-xs font-medium capitalize border-b-2 -mb-px transition-colors ${
                  tab === t
                    ? 'border-primary text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
              >
                {t}
              </button>
            ))}
            <div className="flex-1" />
            <div className={`self-center px-2 py-0.5 rounded-full text-xs font-mono ${connected ? 'text-green-400' : 'text-red-400'}`}>
              {connected ? '● live' : '○ connecting...'}
            </div>
          </div>

          {/* Tab content */}
          <div className={`flex-1 ${tab === 'terminal' ? 'flex flex-col overflow-hidden' : 'overflow-y-auto'}`}>
            {tab === 'tasks' && <TaskBoard />}
            {tab === 'workers' && <WorkerList />}
            {tab === 'terminal' && <PaneManager />}
          </div>
        </main>
      </div>

      <UsageBar />
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
