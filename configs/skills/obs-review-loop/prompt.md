# Observability Review Loop

Turn real-user signals into fixes and a completeness verdict on the
success-mechanism. Default window: last 14 days. Report language: Chinese.

## Step 1 — Resolve access (never hard-code, never print secrets)

Find the target project's observability wiring:
- Sentry: org + project + auth token — from the project's `.env` /
  config / deployment docs. API: `https://sentry.io/api/0/organizations/{org}/issues/?project={id}&statsPeriod=14d` (or a self-hosted base URL if the project uses one).
- PostHog: project id + personal API key + host — same sources.
  HogQL query endpoint: `{host}/api/projects/{id}/query/`.
- App/DB logs: the project's own log locations (server logs, error
  tables) as documented in its CLAUDE.md/infra docs.
- If a sibling tool already wraps these read-only (e.g. a reporting
  service in the same monorepo with its own clients), prefer calling
  that over raw curl. Read-only everywhere: no state-changing API calls.

If credentials cannot be resolved, stop and name the file that should
carry them — do not probe for tokens.

## Step 2 — Pull

- Sentry: issues sorted by event count and affected users; capture
  title, count, users, first/last seen, issue URL, culprit, and the
  latest event's stack snippet.
- PostHog: top events; the core funnels (signup → activation → paid if
  applicable); drop-off steps; error-adjacent custom events; rage/empty
  clicks if captured; retention if the project defines it.
- Logs: error-rate highlights, repeated exception signatures, slow/failing
  endpoints — proportionate to what the app actually logs.

## Step 3 — Exclude internal traffic

Exclude before counting anything: VPN/tailnet IP ranges, staff
accounts/emails, health-check and bot traffic, the owner's own devices.
State the exclusion rule you used in the report. If internal share is
>50% of an event's volume, say so — the "real user" claim is weak.

## Step 4 — Triage

Dedupe into root causes. Classify each:
- **真bug** — reproducible defect real users hit (evidence: issue/log +
  the code path `path:line`).
- **体验摩擦** — works but loses users (funnel drop, empty-click clusters).
- **数据噪声** — bot/internal/mis-tagging; recommend the filter/instrument
  fix, do not code around it.

Rank by (affected real users × severity). For each top item: evidence,
likely code location, proposed fix, and verification plan.

## Step 5 — Fix the obvious

真bug with clear repro: branch → fix → run the project's real gate →
live re-probe → commit small. Never mute/ignore/delete an error without
a code fix or a documented rationale in the commit/report. 体验摩擦
fixes need the owner's product taste only when the remedy changes UX
copy/flow materially — otherwise pick the conservative default and note
the alternative.

## Step 6 — Success-mechanism completeness

For each fix ask: "how will we know it worked?" If nothing observes it
(metric, alert, dashboard, funnel step), that is a **机制缺口** — report
it; add the cheap instrumentation in the same pass when it is trivial
(a log line, an event, an alert rule), park it with a recommendation
when it is not.

## Step 7 — Report (Chinese, categorized)

1. **结论** — what the data says about product health, in three lines.
2. **已修** — commit each, with evidence (issue URL + verification).
3. **发现未修** — ranked, each with why not fixed (needs decision /
   needs repro / needs owner taste).
4. **机制缺口** — missing success/failure instrumentation, ranked.
5. **数据健康度** — tracking coverage gaps, bot/internal noise level,
   anything that makes the numbers unreliable.
6. **用户反映 vs 统计对照** — where qualitative reports (support,
   sentry comments) and quantitative data agree or diverge, if both exist.

## Failure modes to avoid

- Quoting counts without provenance (issue URL + query window on every
  number).
- Fixing from the stack trace alone without reading the actual code path.
- Treating "no sentry errors" as healthy when the app never reports errors
  client-side (that is a 机制缺口, not a clean bill).
