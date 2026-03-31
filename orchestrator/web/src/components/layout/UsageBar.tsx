import { useSessionStore } from '../../stores/sessionStore';
import { cn } from '../../lib/utils';

export function UsageBar() {
  const { usage, costTotal, settings } = useSessionStore();

  if (!usage && !costTotal) return null;

  const budget = settings?.cost_budget;
  const pct = budget ? Math.min(100, (costTotal / budget) * 100) : 0;

  return (
    <footer className="h-8 border-t border-border flex items-center px-4 gap-4 shrink-0">
      {budget ? (
        <>
          <div className="flex-1 h-1.5 bg-secondary rounded-full overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all', pct > 80 ? 'bg-red-400' : pct > 50 ? 'bg-yellow-400' : 'bg-green-400')}
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground font-mono">
            ${costTotal.toFixed(3)} / ${budget.toFixed(2)}
          </span>
        </>
      ) : (
        <span className="text-xs text-muted-foreground font-mono">
          Total cost: ${costTotal.toFixed(4)}
        </span>
      )}
      {usage && (
        <span className="text-xs text-muted-foreground font-mono">
          {((usage.used_tokens / usage.total_tokens) * 100).toFixed(0)}% quota
        </span>
      )}
    </footer>
  );
}
