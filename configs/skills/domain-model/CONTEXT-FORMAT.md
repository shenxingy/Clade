# CONTEXT.md entry format

Each entry is a level-3 heading with the term, then a tight definition plus
disambiguation from anything it could be confused with.

## Format

```markdown
### {Term}
{One or two sentences: the precise meaning AS USED IN THIS PROJECT.}
- **Not to be confused with**: {near-miss term or common outside meaning, if any}
- **Where it matters**: {file/module/subsystem where getting this wrong causes real bugs}
- **Defined**: {YYYY-MM-DD} {why now — what friction triggered this entry}
```

## Example

### Worker
A single spawned `claude -p` subprocess executing ONE task to completion, tracked
by `Worker` in `worker.py`. Ephemeral — exists only for the task's lifetime.
- **Not to be confused with**: a "session" (the long-lived interactive Claude Code
  conversation this file itself is part of) or a "node" (loop-runner.sh's
  supervisor/worker distinction in the background-loop system — a different axis).
- **Where it matters**: `worker.py`, `session.py` — conflating Worker with Session
  produces bugs in `poll_all()`'s lifecycle handling.
- **Defined**: 2026-07-06 — surfaced when a PR review used "worker" to mean the
  loop-runner shell process, not the orchestrator's `Worker` class.

## Maintenance rules

- UPDATE an entry in place when its definition changes — never leave two entries
  for the same term. Note what changed and why in the "Defined" line's trailer
  (e.g. "Defined: 2026-07-06, redefined 2026-08-01 — X was folded into Y").
- Keep it a GLOSSARY, not a design doc: one term, one entry, no prose essays.
  If an entry needs more than ~5 lines, the real content probably belongs in an
  ADR (`docs/adr/`) or the module's own docstring instead — link to it, don't
  inline it here.
- A term earns an entry when it causes real friction — ambiguity across two
  people/code paths, a term used with silently different meanings, or a name
  that looks self-explanatory but isn't. Do not pre-populate a glossary of
  everything; that produces a document nobody reads.
