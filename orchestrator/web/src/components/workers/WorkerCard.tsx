import { useState } from 'react';
import { Worker } from '../../lib/types';
import { ModelBadge } from '../shared/ModelBadge';
import { formatDuration, formatCost } from '../../lib/utils';
import { ChevronDown, ChevronUp, Square, PauseCircle, PlayCircle, ScrollText, X, ExternalLink } from 'lucide-react';
import { workers as api } from '../../lib/api';
import { useSessionStore } from '../../stores/sessionStore';

export function WorkerCard({ worker }: { worker: Worker }) {
  const [expanded, setExpanded] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [fullLog, setFullLog] = useState<string | null>(null);
  const [logLoading, setLogLoading] = useState(false);
  const activeSessionId = useSessionStore(s => s.activeSessionId) ?? '';

  // log_tail is a raw string from the server; split into lines for display
  const logLines = worker.log_tail
    ? worker.log_tail.split('\n').filter(l => l.trim())
    : [];

  const handleStop = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await api.stop(worker.id, activeSessionId).catch(console.error);
  };

  const handlePause = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await api.pause(worker.id, activeSessionId).catch(console.error);
  };

  const handleResume = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await api.resume(worker.id, activeSessionId).catch(console.error);
  };

  const handleViewLog = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setShowLog(true);
    if (!fullLog) {
      setLogLoading(true);
      api.log(worker.id, activeSessionId)
        .then(data => setFullLog(data.log || '(empty log)'))
        .catch(() => setFullLog('(error loading log)'))
        .finally(() => setLogLoading(false));
    }
  };

  const isPaused = worker.status === 'paused';

  return (
    <>
      <div className="border border-green-400/20 bg-green-400/5 rounded-lg overflow-hidden">
        {/* Header */}
        <div
          className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-green-400/10 transition-colors"
          onClick={() => setExpanded(!expanded)}
        >
          <span className="text-green-400 text-xs font-mono">{worker.id.slice(0, 8)}</span>
          <ModelBadge model={worker.model} />
          <span className="flex-1 text-sm text-foreground truncate">{worker.description}</span>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{formatDuration(worker.elapsed_s)}</span>
            {worker.estimated_cost != null && <span>{formatCost(worker.estimated_cost)}</span>}
            {worker.pr_url && (
              <a href={worker.pr_url} target="_blank" rel="noreferrer"
                className="text-blue-400 hover:text-blue-300"
                onClick={e => e.stopPropagation()}
                title="View PR">
                <ExternalLink size={11} />
              </a>
            )}
            {worker.last_commit && (
              <span className="font-mono opacity-60">{worker.last_commit.slice(0, 7)}</span>
            )}
            {isPaused && <span className="text-yellow-400 text-xs">paused</span>}
          </div>
          <div className="flex gap-1" onClick={e => e.stopPropagation()}>
            <button onClick={handleViewLog} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Full log">
              <ScrollText size={14} />
            </button>
            {isPaused ? (
              <button onClick={handleResume} className="p-1 rounded hover:bg-green-400/20 text-muted-foreground hover:text-green-400" title="Resume">
                <PlayCircle size={14} />
              </button>
            ) : (
              <button onClick={handlePause} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Pause">
                <PauseCircle size={14} />
              </button>
            )}
            <button onClick={handleStop} className="p-1 rounded hover:bg-destructive/20 text-muted-foreground hover:text-red-400" title="Kill">
              <Square size={14} />
            </button>
          </div>
          {expanded ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
        </div>

        {/* Log tail (always visible, 3 lines) */}
        {!expanded && logLines.length > 0 && (
          <div className="px-3 pb-2">
            {logLines.slice(-3).map((line, i) => (
              <p key={i} className="text-xs font-mono text-muted-foreground truncate leading-relaxed">{line}</p>
            ))}
          </div>
        )}

        {/* Expanded log */}
        {expanded && (
          <div className="border-t border-green-400/20 max-h-64 overflow-y-auto bg-background/50">
            <div className="p-3">
              {worker.oracle_result && (
                <div className="mb-2 p-2 rounded bg-accent/30 border border-accent text-xs text-foreground">
                  <span className="font-semibold text-muted-foreground">Oracle: </span>{worker.oracle_result}
                </div>
              )}
              {logLines.length === 0 ? (
                <p className="text-xs text-muted-foreground">No log output yet...</p>
              ) : (
                logLines.map((line, i) => (
                  <p key={i} className="text-xs font-mono text-muted-foreground leading-relaxed whitespace-pre-wrap">{line}</p>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* Full Log Modal */}
      {showLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60" onClick={() => setShowLog(false)} />
          <div className="relative w-full max-w-3xl max-h-[80vh] flex flex-col bg-background border border-border rounded-lg overflow-hidden shadow-2xl">
            <div className="flex items-center gap-2 px-4 py-2 border-b border-border shrink-0">
              <span className="text-xs font-mono text-muted-foreground">{worker.id.slice(0, 8)}</span>
              <span className="flex-1 text-xs text-foreground truncate">{worker.description}</span>
              <button onClick={() => setShowLog(false)} className="p-1 rounded hover:bg-secondary text-muted-foreground">
                <X size={14} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 bg-background/50">
              {logLoading ? (
                <p className="text-xs text-muted-foreground">Loading…</p>
              ) : (
                <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap leading-relaxed">
                  {fullLog || '(empty)'}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
