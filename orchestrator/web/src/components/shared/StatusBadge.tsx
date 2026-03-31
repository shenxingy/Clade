import { cn } from '../../lib/utils';

const variants: Record<string, string> = {
  pending:  'bg-yellow-400/10 text-yellow-400 border-yellow-400/20',
  running:  'bg-green-400/10  text-green-400  border-green-400/20',
  done:     'bg-slate-400/10  text-slate-400  border-slate-400/20',
  failed:   'bg-red-400/10    text-red-400    border-red-400/20',
  paused:   'bg-blue-400/10   text-blue-400   border-blue-400/20',
};

const icons: Record<string, string> = {
  pending: '●',
  running: '▶',
  done:    '✓',
  failed:  '✗',
  paused:  '⏸',
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-mono',
      variants[status] ?? 'bg-slate-400/10 text-slate-400 border-slate-400/20'
    )}>
      <span>{icons[status] ?? '?'}</span>
      {status}
    </span>
  );
}
