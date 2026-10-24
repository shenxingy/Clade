---
title: Workflow agents — per-stage effort and a lean reader type, measured on 15 known-answer claims
date: 2026-10-23
review_date: 2026-10-23
status: integrated
summary: >
  The 2026-10-22 audit of 316 Workflow runs left two levers unmeasured: every
  agent() inherits xhigh effort, and every subagent re-reads ~54k tokens of
  CLAUDE.md and skill listing. A paired A/B on 16 claims about a pinned repo
  snapshot (8 seeded false, one later dropped as ambiguous) found low and medium
  effort as accurate as xhigh at 29–52% of its output tokens, and the
  wf-reader agent type equally accurate with turn-1 context 95.8k → 5.4k
  tokens. The effort table is now guidance; wf-reader waits for a write-deny guard.
---

← [Research index](README.md)

# Workflow agents: per-stage effort and a lean reader type, measured

**Verdict.** For a read-only stage that checks one claim against code, two
changes cut cost without measurable loss of accuracy on this task:

- **`effort: 'low'` or `'medium'`** matched xhigh's accuracy (15/15) while
  using 29% (low) or 52% (medium) of xhigh's output tokens, 55–70% of its
  cache reads, and about half its wall time. xhigh was the only setting that
  reproduced an edge case, so adversarial review keeps the default.
- **`agentType: 'wf-reader'`** at the same effort and model cut the turn-1
  context from 95.8k to 5.4k tokens and cache reads by 92%, with the same 15/15.
  It is not adopted yet: read-only is still only an instruction (see
  "Not done").

The sample is small: 15 decisive items, one task type (single-claim
verification), one repository, one model (Opus 5.5). Treat these as the
direction and the order of magnitude, not as rates. This answers the
2026-10-22 Workflow efficiency audit's two "A/B before rollout" items in
TODO.md.

## Contents

- [Why](#why)
- [Method](#method)
- [Results](#results)
- [Not done](#not-done)
- [Next](#next)

## Why

The audit of 316 Workflow runs found that no `agent()` set `effort`, so every
stage inherited the owner's `xhigh`, mechanical stages included (302 of 314).
It also found a turn-1 context median of 72.6k tokens per subagent, of which
about 54k is CLAUDE.md and the skill listing, re-read on every call. Both
levers looked large, but neither had been measured on the same items at two
settings, so the audit refused to roll either out on observational data.

## Method

- **Items.** 16 claims about a pinned snapshot of this repository (a detached
  worktree at `4f9fcae`). Each claim names a file and a fact: 8 true, 8 seeded
  false. The answer key was checked by hand against the snapshot before any
  run. Examples: the default of `delivery.py`'s `--checks` option (seeded
  false: "gate"); `check_rollup` counting a NEUTRAL check as failing (seeded
  false); `install.sh` preserving the private tail of `~/.claude/CLAUDE.md`
  from "## Cross-Project Rules" onward (true).
- **Prompt.** Identical for every cell. Decide TRUE, FALSE or UNDETERMINED for
  the snapshot by reading the code, with file:line evidence, returned through a
  schema.
- **Effort A/B.** The same 16 items at `xhigh`, `medium` and `low` with the
  default workflow agent on Opus 5.5: 48 agents in one run.
- **Reader A/B.** The same 16 items with `agentType: 'wf-reader'` at `medium`.
  It ran in a fresh headless session, because the agent registry is read at
  session start and an agent installed mid-session is not visible. One run
  inherited Sonnet 5 from the headless session's `--model`; it was re-run on
  Opus 5.5 so that only the agent type differs from the default-medium cell.
- **Metrics.** Accuracy against the key. Per agent, from its transcript, usage
  keyed by `message.id` (the scorecard's double count does not apply): calls,
  output tokens, cache reads, cache writes and turn-1 context. Wall time comes
  from transcript timestamps. Concurrency and host load differed between runs,
  so time is the weakest metric here.
- **One item dropped from scoring.** Claim c14, that the rule injector "never"
  scans a nested rules directory inside `node_modules`, turned out to be
  ambiguous. The xhigh agent answered FALSE and reproduced two counterexamples
  on fixtures: a symlink into `node_modules`, and a project root that itself
  sits inside one. medium and low named the same caveats but answered TRUE. The
  symlink case is a real defect, now fixed separately. Accuracy below is out of
  the remaining 15.

## Results

Effort, default agent, Opus 5.5 (16 agents each):

| effort | correct | calls | output tokens | cache reads | cache writes | median wall time |
|---|---|---|---|---|---|---|
| xhigh | 15/15 | 61 | 20,542 | 4.70M | 1.33M | 13 s |
| medium | 15/15 | 43 | 10,631 | 3.13M | 1.06M | 8 s |
| low | 15/15 | 37 | 5,955 | 2.59M | 0.99M | 6 s |

Agent type, effort medium, Opus 5.5 (16 agents each):

| agent type | correct | turn-1 context (median) | calls | output tokens | cache reads | cache writes |
|---|---|---|---|---|---|---|
| default | 15/15 | 95.8k | 43 | 10,631 | 3.13M | 1.06M |
| wf-reader | 15/15 | 5.4k | 44 | 11,754 | 0.26M | 0.10M |

How to read the tables:
- Cache writes barely move with effort, because each agent writes its turn-1
  prefix once. That prefix is what `wf-reader` removes.
- Output tokens and calls fall with effort, because the agent stops after the
  decisive line instead of reading around it.
- Every one of the 8 seeded false claims was caught at every setting, so this
  item set does not show low effort missing a planted error. The one
  difference in depth went the other way: xhigh found and reproduced an edge
  case the others only mentioned.

## Not done

- **wf-reader adoption (closed 2026-10-24).** It was held back until
  read-only was a control rather than an instruction. #160 added a frontmatter
  PreToolUse hook that holds Bash to a read allowlist. The live smoke ran under
  a bypassPermissions parent with a test double carrying wf-reader's exact
  frontmatter: the hook denied `touch`, `git commit` and `gh pr comment`, the
  reads ran, and nothing was written. The guidance now routes host-safe
  read-only stages to it. Limits: the hook does not run where hooks are off,
  and the plugin copy `clade:wf-reader` is unguarded.
- Other stage types (implement, synthesize, judge) were not measured. The
  stage table keeps the default for them on purpose.
- n is small. The scorecard's per-phase rows (model and effort per agent) can
  now check the table against real runs.

## Next

Give `wf-reader` an enforced read-only Bash guard, show live that `touch`,
`git commit` and `gh pr comment` are refused, and only then add the routing
line to the Workflow guidance. Owner: the Clade maintainer session that lands
the guard.
