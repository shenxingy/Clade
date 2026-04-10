import { useState } from 'react';
import { Worker } from '../../lib/types';
import { ModelBadge } from '../shared/ModelBadge';
import { formatDuration, formatCost } from '../../lib/utils';
import { ChevronDown, ChevronUp, Square, PauseCircle } from 'lucide-react';
import { workers as api } from '../../lib/api';

export function WorkerCard({ worker }: { worker: Worker }) {
  const [expanded, setExpanded] = useState(false);
  // log_tail is a raw string from the server; split into lines for display
  const logLines = worker.log_tail
    ? worker.log_tail.split('\n').filter(l => l.trim())
    : [];

  const handleStop = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await api.stop(worker.id).catch(console.error);
  };

  const handlePause = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await api.pause(worker.id).catch(console.error);
  };

  return (
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
          {worker.last_commit && (
            <span className="font-mono opacity-60">{worker.last_commit.slice(0, 7)}</span>
          )}
        </div>
        <div className="flex gap-1" onClick={e => e.stopPropagation()}>
          <button onClick={handlePause} className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Pause">
            <PauseCircle size={14} />
          </button>
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
  );
}
