import { useCallback, useEffect, useState } from 'react';
import { evals as evalsApi } from '../../lib/api';
import type { EvalMetrics } from '../../lib/types';
import { useSessionStore } from '../../stores/sessionStore';

type MetricCardProps = {
  eyebrow: string;
  label: string;
  numerator: number;
  denominator: number;
  rate: number | null;
  inverse?: boolean;
};

function formatRate(rate: number | null) {
  return rate === null ? 'N/A' : `${(rate * 100).toFixed(1)}%`;
}

function MetricCard({
  eyebrow,
  label,
  numerator,
  denominator,
  rate,
  inverse = false,
}: MetricCardProps) {
  const width = rate === null ? 0 : Math.min(100, rate * 100);
  const healthy = rate !== null && (inverse ? rate === 0 : rate >= 0.95);
  return (
    <article className="border border-border bg-secondary/30 p-4 min-h-40 flex flex-col">
      <div className="text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
        {eyebrow}
      </div>
      <div className={`mt-3 text-3xl font-semibold ${healthy ? 'text-green-400' : 'text-foreground'}`}>
        {formatRate(rate)}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
      <div className="mt-auto pt-5">
        <div className="h-1 bg-border overflow-hidden">
          <div
            className={`h-full transition-all ${inverse ? 'bg-red-400' : 'bg-cyan-400'}`}
            style={{ width: `${width}%` }}
          />
        </div>
        <div className="mt-2 flex justify-between text-[10px] text-muted-foreground">
          <span>{numerator} observed</span>
          <span>{denominator} denominator</span>
        </div>
      </div>
    </article>
  );
}

export function EvalDashboard() {
  const activeSessionId = useSessionStore(state => state.activeSessionId);
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    if (!activeSessionId) return;
    setLoading(true);
    setError('');
    evalsApi.metrics(activeSessionId)
      .then(setMetrics)
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [activeSessionId]);

  useEffect(load, [load]);

  if (!activeSessionId) {
    return <div className="p-6 text-sm text-muted-foreground">Select a session to inspect eval health.</div>;
  }

  return (
    <section className="p-6 max-w-6xl mx-auto">
      <div className="flex items-end justify-between gap-4 mb-6">
        <div>
          <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-400">Verified delivery control plane</div>
          <h1 className="mt-2 text-xl font-semibold">North Star and release guardrails</h1>
          <p className="mt-1 text-xs text-muted-foreground max-w-2xl">
            Throughput never compensates for false approval or missing evidence. N/A means no valid denominator.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary disabled:opacity-50"
        >
          {loading ? 'Refreshing…' : 'Refresh snapshot'}
        </button>
      </div>

      {error && <div className="border border-red-900 bg-red-950/30 p-3 text-xs text-red-300 mb-4">{error}</div>}
      {!metrics && !error && <div className="text-xs text-muted-foreground">Loading evidence graph…</div>}
      {metrics && (
        <>
          <article className="border border-cyan-900/70 bg-cyan-950/20 mb-5 grid md:grid-cols-[1.4fr_1fr]">
            <div className="p-5 md:p-6 border-b md:border-b-0 md:border-r border-cyan-900/70">
              <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-400">
                North Star · verified delivery rate
              </div>
              <div className="mt-3 text-5xl font-semibold tracking-tight">
                {formatRate(metrics.north_star.rate)}
              </div>
              <p className="mt-3 text-xs leading-5 text-muted-foreground max-w-xl">
                Delivered attempts with complete terminal evidence, an approved oracle verdict,
                and an eligible delivery candidate — divided by every terminal attempt.
              </p>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-1">
              <div className="p-4 border-r md:border-r-0 md:border-b border-cyan-900/70">
                <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Verified deliveries</div>
                <div className="mt-2 text-2xl text-green-400">{metrics.north_star.verified_deliveries}</div>
              </div>
              <div className="p-4">
                <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Terminal attempts</div>
                <div className="mt-2 text-2xl">{metrics.north_star.terminal_attempts}</div>
              </div>
            </div>
          </article>

          <div className="grid grid-cols-2 md:grid-cols-4 border border-border mb-5">
            {[
              ['Quarantine', metrics.candidates.quarantined, 'text-yellow-400'],
              ['Promoted', metrics.candidates.promoted, 'text-green-400'],
              ['Rejected', metrics.candidates.rejected, 'text-red-400'],
              ['Total signals', metrics.candidates.total, 'text-cyan-400'],
            ].map(([label, value, color]) => (
              <div key={String(label)} className="p-4 border-r last:border-r-0 border-border">
                <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
                <div className={`mt-2 text-2xl ${color}`}>{value}</div>
              </div>
            ))}
          </div>

          <div className="mb-3">
            <div className="text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
              Release guardrails and provenance
            </div>
          </div>
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
            <MetricCard
              eyebrow="Attempt evidence"
              label="terminal bundles with lifecycle-complete fields"
              numerator={metrics.evidence_completeness.complete}
              denominator={metrics.evidence_completeness.terminal_attempts}
              rate={metrics.evidence_completeness.rate}
            />
            <MetricCard
              eyebrow="Immutable provenance"
              label="candidate sources resolving to exact revision + digest"
              numerator={metrics.source_integrity.valid}
              denominator={metrics.source_integrity.candidates}
              rate={metrics.source_integrity.rate}
            />
            <MetricCard
              eyebrow="Confirmed false approve"
              label="human-promoted regressions / oracle-approved attempts"
              numerator={metrics.false_approvals.confirmed}
              denominator={metrics.false_approvals.oracle_approved_attempts}
              rate={metrics.false_approvals.rate}
              inverse
            />
            <MetricCard
              eyebrow="Human override"
              label="promoted labels disagreeing with observed oracle verdict"
              numerator={metrics.human_overrides.count}
              denominator={metrics.human_overrides.comparable_promotions}
              rate={metrics.human_overrides.rate}
              inverse
            />
            <MetricCard
              eyebrow="Accepted coverage"
              label="promotions with a matching, present corpus provenance"
              numerator={metrics.accepted_regression_coverage.covered}
              denominator={metrics.accepted_regression_coverage.promoted}
              rate={metrics.accepted_regression_coverage.rate}
            />
          </div>
        </>
      )}
    </section>
  );
}
