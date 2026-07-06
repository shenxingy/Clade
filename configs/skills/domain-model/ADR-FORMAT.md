# ADR format (docs/adr/NNNN-title-kebab-case.md)

## The gate — apply BEFORE writing; most decisions do NOT clear it

Write an ADR only when the decision is AT LEAST ONE of:

1. **Irreversible or expensive to reverse** — a schema change, a public API
   shape, a chosen dependency that's hard to swap later, a data format choice.
2. **Surprising** — it goes against what a reasonable engineer would default
   to; future-you (or a reviewer) would ask "wait, why not the obvious thing?"
3. **A genuine trade-off** — multiple viable options existed and the choice
   gives up something real (not a no-brainer where one option is strictly
   better with no real downside to the others).

If none of the three apply: do NOT write an ADR. Routine, reversible,
obvious-in-hindsight choices are noise — recording them buries the decisions
that actually needed the paper trail.

## Format

```markdown
# {NNNN}. {Decision title, imperative or noun phrase}

Date: {YYYY-MM-DD}
Status: {proposed | accepted | superseded by NNNN}

## Gate
{Which of the 3 gate criteria this decision clears — one line each that applies.}

## Context
{The forces at play — technical, project, constraints. 2-4 sentences.}

## Decision
{What was decided, stated plainly.}

## Alternatives considered
{Each real alternative + the ONE reason it lost. Skip alternatives nobody
seriously considered — this is not a survey.}

## Consequences
{What this makes easier, what it makes harder or forecloses. Be honest about
the downside — an ADR with no cost listed is usually hiding one.}
```

## Numbering

Sequential across the whole project (`docs/adr/0001-...md`, `0002-...md`, ...),
never reused. A decision that supersedes an earlier one gets its OWN new
number; mark the OLD file `Status: superseded by NNNN` rather than deleting
it — the history is the point of the record.
