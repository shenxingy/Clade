import { useState, useEffect, useCallback } from 'react';
import { TerminalPane } from './TerminalPane';
import { useSessionStore } from '../../stores/sessionStore';
import type { Worker } from '../../lib/types';

// ─── Types ────────────────────────────────────────────────────────
interface Pane {
  id: string;
  workerId: string;
}

let _paneCounter = 0;
const newPaneId = () => `pane-${++_paneCounter}`;

// ─── PaneManager ─────────────────────────────────────────────────
// Manages up to 4 xterm.js terminal panes in a responsive grid.
// Keyboard shortcuts: Ctrl+\ (add pane), Ctrl+Shift+W (close), Ctrl+Shift+←/→ (cycle)
export function PaneManager() {
  const workers = useSessionStore(s => s.workers);
  const [panes, setPanes] = useState<Pane[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showPicker, setShowPicker] = useState(false);

  // ─── Pane operations ──────────────────────────────────────────
  const addPane = useCallback((workerId: string) => {
    setPanes(prev => {
      if (prev.length >= 4) return prev;
      const id = newPaneId();
      setActiveId(id);
      return [...prev, { id, workerId }];
    });
  }, []);

  const removePane = useCallback((paneId: string) => {
    setPanes(prev => {
      const idx = prev.findIndex(p => p.id === paneId);
      const next = prev.filter(p => p.id !== paneId);
      // Focus previous pane or last
      setActiveId(next[Math.max(0, idx - 1)]?.id ?? null);
      return next;
    });
  }, []);

  const cyclePanes = useCallback((dir: 1 | -1) => {
    setPanes(prev => {
      if (prev.length === 0) return prev;
      setActiveId(curr => {
        const idx = prev.findIndex(p => p.id === curr);
        const next = prev[(idx + dir + prev.length) % prev.length];
        return next?.id ?? null;
      });
      return prev;
    });
  }, []);

  const pickAndAddPane = useCallback(() => {
    const workerIds = Object.keys(workers);
    const usedIds = new Set(panes.map(p => p.workerId));
    const next = workerIds.find(id => !usedIds.has(id));
    if (next) {
      addPane(next);
    } else {
      setShowPicker(true);
    }
  }, [workers, panes, addPane]);

  // ─── Keyboard shortcuts ───────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === '\\') {
        e.preventDefault();
        pickAndAddPane();
      } else if (e.ctrlKey && e.shiftKey && e.key === 'W') {
        e.preventDefault();
        if (activeId) removePane(activeId);
      } else if (e.ctrlKey && e.shiftKey && e.key === 'ArrowRight') {
        e.preventDefault();
        cyclePanes(1);
      } else if (e.ctrlKey && e.shiftKey && e.key === 'ArrowLeft') {
        e.preventDefault();
        cyclePanes(-1);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [activeId, pickAndAddPane, removePane, cyclePanes]);

  // ─── Layout helpers ───────────────────────────────────────────
  // 1 pane: 1-col × 1-row | 2: 2-col × 1-row | 3-4: 2-col × 2-row
  const gridCols = panes.length <= 1 ? 'grid-cols-1' : 'grid-cols-2';

  const runningWorkers: Worker[] = Object.values(workers);
  const availableWorkers = runningWorkers.filter(
    w => !panes.some(p => p.workerId === w.worker_id)
  );

  // ─── Empty state ──────────────────────────────────────────────
  if (panes.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 text-muted-foreground">
        <div className="text-center">
          <p className="text-sm mb-1">No terminal panes open</p>
          <p className="text-xs opacity-60">Ctrl+\ to open a worker · Ctrl+Shift+W to close</p>
        </div>
        {runningWorkers.length > 0 ? (
          <div className="flex flex-col items-center gap-2">
            <p className="text-xs text-muted-foreground">Open worker terminal:</p>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg">
              {runningWorkers.map(w => (
                <button
                  key={w.worker_id}
                  onClick={() => addPane(w.worker_id)}
                  className="px-2 py-1 text-xs font-mono bg-secondary rounded hover:bg-accent text-foreground transition-colors"
                  title={w.description}
                >
                  <span className="text-green-400">{w.worker_id.slice(0, 8)}</span>
                  <span className="text-muted-foreground ml-1">
                    {w.description.length > 35 ? w.description.slice(0, 35) + '…' : w.description}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-xs">No workers running</p>
        )}
      </div>
    );
  }

  // ─── Pane grid ────────────────────────────────────────────────
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1 border-b border-border shrink-0">
        <span className="text-xs text-muted-foreground font-mono">
          {panes.length}/{4} panes
        </span>
        <div className="flex-1" />
        {panes.length < 4 && (
          <div className="relative">
            <button
              onClick={() => setShowPicker(v => !v)}
              className="px-2 py-0.5 text-xs bg-secondary rounded hover:bg-accent transition-colors"
            >
              + Pane
            </button>
            {showPicker && (
              <div
                className="absolute right-0 top-full mt-1 bg-background border border-border rounded shadow-xl z-50 min-w-56 max-h-64 overflow-y-auto"
                onBlur={() => setShowPicker(false)}
              >
                {availableWorkers.length > 0 ? (
                  availableWorkers.map(w => (
                    <button
                      key={w.worker_id}
                      onClick={() => { addPane(w.worker_id); setShowPicker(false); }}
                      className="block w-full text-left px-3 py-1.5 text-xs font-mono hover:bg-secondary transition-colors"
                    >
                      <span className="text-green-400">{w.worker_id.slice(0, 8)}</span>
                      <span className="text-muted-foreground ml-2">
                        {w.description.length > 45 ? w.description.slice(0, 45) + '…' : w.description}
                      </span>
                    </button>
                  ))
                ) : (
                  <p className="px-3 py-2 text-xs text-muted-foreground">All workers open</p>
                )}
              </div>
            )}
          </div>
        )}
        <span className="text-xs text-muted-foreground opacity-50 hidden sm:block">
          Ctrl+\ split · Ctrl+Shift+W close · Ctrl+Shift+←/→ cycle
        </span>
      </div>

      {/* Pane grid — CSS grid adapts to pane count */}
      <div className={`flex-1 grid ${gridCols} gap-1 p-1 overflow-hidden min-h-0`}
           onClick={() => setShowPicker(false)}>
        {panes.map(pane => {
          const worker = workers[pane.workerId];
          return (
            <TerminalPane
              key={pane.id}
              workerId={pane.workerId}
              workerDesc={worker?.description ?? pane.workerId}
              isActive={pane.id === activeId}
              onClick={() => setActiveId(pane.id)}
              onClose={() => removePane(pane.id)}
            />
          );
        })}
      </div>
    </div>
  );
}
