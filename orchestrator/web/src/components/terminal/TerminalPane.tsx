import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { useSessionStore } from '../../stores/sessionStore';

interface Props {
  workerId: string;
  workerDesc: string;
  isActive: boolean;
  onClick: () => void;
  onClose: () => void;
}

// ─── TerminalPane ─────────────────────────────────────────────────
export function TerminalPane({ workerId, workerDesc, isActive, onClick, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const writtenRef = useRef(0);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      theme: {
        background: '#0a0a0a',
        foreground: '#e2e8f0',
        cursor: '#94a3b8',
        selectionBackground: '#334155',
        black: '#1e293b',
        red: '#f87171',
        green: '#4ade80',
        yellow: '#fbbf24',
        blue: '#60a5fa',
        magenta: '#c084fc',
        cyan: '#22d3ee',
        white: '#e2e8f0',
      },
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 12,
      lineHeight: 1.4,
      scrollback: 5000,
      convertEol: true,
      disableStdin: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);

    requestAnimationFrame(() => {
      try { fitAddon.fit(); } catch (_) { /* ignore */ }
    });

    termRef.current = term;
    fitRef.current = fitAddon;

    // Write existing lines
    const existingLogs = useSessionStore.getState().workerLogs[workerId] ?? [];
    existingLogs.forEach((line: string) => term.writeln(line));
    writtenRef.current = existingLogs.length;

    // Subscribe to new log lines
    const unsub = useSessionStore.subscribe((state, prevState) => {
      const logs = state.workerLogs[workerId] ?? [];
      const prevLogs = prevState.workerLogs[workerId] ?? [];
      if (logs.length > prevLogs.length) {
        const newLines = logs.slice(writtenRef.current);
        newLines.forEach((line: string) => term.writeln(line));
        writtenRef.current = logs.length;
      }
    });

    const ro = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        try { fitAddon.fit(); } catch (_) { /* ignore */ }
      });
    });
    ro.observe(containerRef.current);

    return () => {
      unsub();
      ro.disconnect();
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      writtenRef.current = 0;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workerId]);

  return (
    <div
      className={`flex flex-col border rounded-sm overflow-hidden cursor-default ${
        isActive ? 'border-primary/70' : 'border-border'
      }`}
      onClick={onClick}
    >
      {/* Header bar */}
      <div
        className={`flex items-center gap-2 px-2 py-0.5 text-xs font-mono shrink-0 select-none ${
          isActive ? 'bg-primary/15 border-b border-primary/30' : 'bg-secondary/50 border-b border-border'
        }`}
      >
        <span className="text-green-400">{workerId.slice(0, 8)}</span>
        <span className="flex-1 text-muted-foreground truncate">{workerDesc}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onClose(); }}
          className="text-muted-foreground hover:text-red-400 transition-colors leading-none"
          title="Close pane (Ctrl+Shift+W)"
        >
          ✕
        </button>
      </div>
      {/* xterm.js mount point */}
      <div ref={containerRef} className="flex-1 overflow-hidden min-h-0" />
    </div>
  );
}
