---
name: Geoffrey Huntley's Ralph (Ralph Wiggum) Loop + CURSED — Deep Dive
date: 2026-06-18
status: reference
review_date: 2026-06-18
reconciled: 2026-06-18
summary: >
  Verifies the standing auto-promoted conclusion "Ralph ≈ /loop — same supervisor-loop
  pattern, not a gap." CONFIRMED. Ralph is `while :; do cat PROMPT.md | claude-code; done`
  — a single-process bash loop that re-allocates a fresh ~170k context each iteration from
  spec/fix_plan/AGENT.md files, does ONE task per loop, and relies on the OPERATOR (not the
  harness) to judge convergence and re-tune the prompt. Clade's /loop is the same pattern
  with MORE machinery: deterministic pre/post phases, fresh `claude -p` process per worker
  (loop-runner.sh + run-tasks.sh), parallel workers, oracle gate, syntax-fix + mid-iter
  test-fix retries, and — unlike Ralph — AUTOMATED convergence detection (count-based AND
  semantic-hash, session.py; or "no unchecked items" deterministic, loop-runner.sh).
  Clade is strictly a superset on convergence/guardrails. No genuine code deficits found.
  Two low-value optional framing nudges noted (goal-file authoring guidance, codebase-search-
  before-implement worker instruction) — both reference_items, not needs_work.
integrated_items: []
needs_work_items: []
reference_items:
  - "Single-process bash loop (`while :; do cat PROMPT.md | claude-code; done`) — Clade's loop-runner.sh:1164 `while true` core IS this, wrapped in DET pre/post nodes. Same pattern, more structure. Different ≠ deficient."
  - "Fresh context per iteration (~170k re-allocated each loop) — Clade already spawns each worker as a fresh `claude -p` process (configs/scripts/run-tasks.sh:471 `exec claude -p ... stream-json`); the supervisor is also a fresh `claude -p` per iteration (loop-runner.sh:463). Clade has this; not a gap."
  - "One task per loop — Clade's orchestrator plan_build mode is an EXACT mirror: 'picks the first unchecked item, spawns ONE worker, marks the item done, and repeats' (orchestrator/session.py:444-446, 535-575). Blueprint mode runs ≤MAX_WORKERS parallel tasks per iter (loop-runner.sh:453) — a deliberate, stronger variant, not a regression."
  - "fix_plan.md / specs / AGENT.md as durable state re-injected each loop — Clade's equivalent: goal file (re-read every iter, loop-runner.sh:385), .claude/loop-context.md (hydrated each iter, loop-runner.sh:270-299), IMPLEMENTATION_PLAN.md (plan_build, session.py:456), AGENTS.md + CLAUDE.md prepended to every worker (orchestrator/worker_taskfile.py:203-221), and learned correction rules injected per-task (loop-runner.sh:519-526). Equivalent mechanism, already present."
  - "Operator-judged convergence ('I watch the TODO like a hawk, throw it out often'; 'eventual consistency'; no hard stop) — this is the ONE axis where Clade is demonstrably STRONGER, not just different: Clade AUTOMATES convergence (session.py:412-420 dual count-based + semantic-hash; loop-runner.sh:1027-1039 '0 unchecked items') plus stuck-detection (3× no-commit, loop-runner.sh:1021) and max-iter. Ralph lacks all of these by design. Importing Ralph's manual model would be a downgrade."
  - "Codebase-search-before-implement worker instruction ('search before you assume not implemented') — a prompt nicety. Clade workers already get TLDR + fault-localization + recent-completions context (worker_taskfile.py:308) which serves the same anti-duplication purpose. Optional micro-nudge, not a deficit."
  - "Goal-file authoring guidance (Ralph's PROMPT.md is hand-tuned spec+plan+learnings) — Clade's /loop SKILL.md already teaches goal.md framing ('what the system should do — NOT a task list', SKILL.md:42-57) and the supervisor does breakdown. Equivalent."
  - "CURSED (3-month while-true loop → Gen-Z compiler) — proof-of-scale anecdote, not a technique delta. Confirms the loop pattern works for long unattended runs; Clade's background worker pool + checkpoints (loop-runner.sh:1077-1101) already target this regime."
---

[中文] | [Back to README](../../README.md)

# Research: Geoffrey Huntley's Ralph Loop + CURSED (2026-06-18)

Deep-dive on Geoffrey Huntley's **Ralph Wiggum technique** and the **CURSED** language
built by running it for three months. Goal: extract loop-convergence and goal-framing
lessons, and **verify** (not re-derive) the standing auto-promoted rule:

> "Ralph ≈ /loop — same supervisor-loop pattern, not a gap."

**Verdict up front: CONFIRMED.** Ralph is the same loop pattern. Clade's `/loop` is a
strict superset on convergence detection and guardrails. "Different ≠ deficient" applied
hard — nothing here is a genuine code gap.

---

## 1. What Ralph / CURSED actually is

**Ralph Wiggum** (named for the glue-eating Simpsons character — persistent despite
setbacks) is, in Huntley's words, *"in its purest form, a Bash loop"*:

```bash
while :; do cat PROMPT.md | claude-code ; done
```

That is the whole technique. Everything else is operator discipline layered on top.
([ghuntley.com/ralph](https://ghuntley.com/ralph/), [ghuntley.com/loop](https://ghuntley.com/loop/))

Three load-bearing ideas:

1. **Fresh context every iteration.** Each loop spawns a *new* process with a clean
   ~170k-token window. The operator must *"deterministically allocate the stack the same
   way every loop"* — re-injecting `@fix_plan.md` (priorities), `@specs/*` (specs), and
   `@AGENT.md` (learnings captured from prior runs). *"The more you use the context window,
   the worse the outcomes."* Nothing accumulates; specs live on disk, not in chat history.

2. **One task per loop.** *"Only one thing."* This caps blast radius and keeps each
   increment verifiable. Huntley explicitly rejects multi-agent fan-out as *"a red hot mess"*
   and runs a **monolithic single process in a single repo**, scaling vertically.

3. **Operator-judged convergence.** There is **no hard stop**. The loop runs until the
   TODO/fix-plan is exhausted or goes circular; the operator decides. *"The TODO list is what
   I'm watching like a hawk. And I throw it out often."* When Ralph misbehaves, the operator
   re-tunes the prompt — *"each time Ralph does something bad, Ralph gets tuned, like a
   guitar."* Building this way *"requires a great deal of faith and a belief in eventual
   consistency."*

**CURSED** ([ghuntley.com/cursed](https://ghuntley.com/cursed/)) is the proof-of-scale:
Huntley ran a Ralph loop for ~3 months with the seed prompt *"make me a programming language
like Golang but the lexical keywords are Gen-Z slang"* and produced a working compiler
(interpreted + LLVM-compiled, binaries on Mac/Linux/Windows). The ongoing iteration prompt:
*"study specs/* … come up with a plan to implement XYZ as markdown then do it."* It is an
anecdote about endurance and spec-driven continuity, **not a new mechanism** beyond §1.

Guardrails Huntley emphasizes: anti-placeholder yelling (*"DO IT OR I WILL YELL AT YOU"*),
*search the codebase before assuming something isn't implemented*, serialize build/test
(1 subagent) while parallelizing search/write, and capture *"the why"* of each test for
future loops. Anthropic later shipped an official `ralph-wiggum` Claude Code plugin.

---

## 2. Clade's /loop — the same pattern, more machinery

Clade ships two loop implementations, both Ralph-shaped:

### 2a. Blueprint loop (`configs/scripts/loop-runner.sh`)

The core is literally Ralph's `while`:

```
loop-runner.sh:1164   while true; do            # ← Ralph's `while :`
  [DET] pre_flight / hydrate_context / parse_todo
  [LLM] supervisor    → plans ≤MAX_WORKERS tasks (fresh `claude -p`, line 463)
  [LLM] workers (par) → each task = a fresh `claude -p` process (run-tasks.sh:471)
  [DET] syntax_check → [LLM] fix_syntax (1 attempt) → revert if still broken
  [DET] test_sample  → [LLM] mid-iter fix (Stripe pattern, 1 retry)
  [DET] commit_changes / convergence_check
done
```

Every Ralph idea has a Clade counterpart:

| Ralph idea | Clade equivalent | Evidence |
|---|---|---|
| `while :; do … done` | `while true` core | `loop-runner.sh:1164` |
| Fresh context / iteration | fresh `claude -p` per worker AND per supervisor | `run-tasks.sh:471` (`exec claude -p … stream-json`), `loop-runner.sh:463` |
| Re-inject `fix_plan`/`specs`/`AGENT.md` | goal file re-read each iter + `.claude/loop-context.md` hydrated each iter + `AGENTS.md`/`CLAUDE.md` prepended to workers + learned correction rules injected | `loop-runner.sh:385,270-299`; `worker_taskfile.py:203-221`; `loop-runner.sh:519-526` |
| One task / loop | ≤MAX_WORKERS independent tasks / iter (parallel variant) | `loop-runner.sh:453` |
| Search-before-implement | TLDR + fault-loc + recent-completions context | `worker_taskfile.py:308` |
| Operator watches TODO | **automated**: "0 unchecked items" → CONVERGED | `loop-runner.sh:1027-1039` |
| No hard stop | **3× no-commit stuck-detect + max-iter** | `loop-runner.sh:1021,1014` |

### 2b. Orchestrator plan_build (`orchestrator/session.py`)

`_run_plan_build` is an almost line-for-line description of Ralph's loop — its own docstring
(session.py:444-446) reads:

> *"picks the first unchecked item, spawns ONE FIXABLE worker, waits for it to complete,
> marks the item done, and repeats until no unchecked items remain or max_iterations."*

That is Ralph's single-task-per-loop with `IMPLEMENTATION_PLAN.md` (session.py:456) playing
the `fix_plan.md` role — generated by a PLAN-phase agent, then drained one checkbox at a time
(session.py:535-575). The plan file is the durable on-disk state; each worker is a fresh
process.

---

## 3. The one axis where Clade is *stronger*: convergence detection

This is the heart of "different ≠ deficient." Ralph's convergence is **a human watching a
TODO list**. Clade automates it three ways — none of which Ralph has:

```
session.py:412-420   # Dual convergence
  count_converged    = last N iters each produced ≤ k changes      (default k=2, n=3)
  semantic_converged = last 2 iters have identical semantic hash   (loop spinning in place)
  is_converged       = count_converged OR semantic_converged
                       OR iteration >= max_iter
```

Plus Blueprint's deterministic "0 unchecked items remain" check (loop-runner.sh:1027-1039),
3-consecutive-no-commit stuck detection (loop-runner.sh:1021), and consecutive-worker-failure
→ writes `.claude/blockers.md` and stops (loop-runner.sh:1313-1323).

Ralph's *"throw out the TODO often / eventual consistency / faith"* model is the explicit
*absence* of this. Importing it into Clade would be a **downgrade**, not a fix. So the auto-
promoted rule's parenthetical — *"same supervisor-loop pattern, not a gap"* — is correct, and
if anything understates it: Clade leads on the one dimension Ralph leaves to the operator.

---

## 4. Did anything survive the "deficient?" test? No.

Per the cross-project rule (don't flag `needs_work` without proving Clade is *deficient*, not
merely *different*), every candidate was checked:

- **Fresh context per iteration** — claimed Clade "accumulates"; FALSE. Each worker and each
  supervisor call is a fresh `claude -p` (run-tasks.sh:471, loop-runner.sh:463). Already done.
- **Single-task discipline** — Clade has both the pure single-task variant (plan_build,
  session.py) and a bounded-parallel variant (Blueprint). Superset.
- **Spec/plan re-injection** — goal file, loop-context, IMPLEMENTATION_PLAN, AGENTS.md,
  correction rules all re-injected. Mechanism present (worker_taskfile.py:203-221).
- **Search-before-implement & goal-file authoring** — prompt-craft niceties; Clade's
  /loop SKILL.md already teaches goal framing (SKILL.md:42-57) and workers get anti-
  duplication context. Optional polish at best → reference, not needs_work.

**Genuine deficits: 0.** Status: **reference**.

---

## Sources

- [ghuntley.com/ralph — "Ralph Wiggum as a software engineer"](https://ghuntley.com/ralph/)
- [ghuntley.com/loop — "everything is a ralph loop"](https://ghuntley.com/loop/)
- [ghuntley.com/cursed — "I ran Claude in a loop for three months… CURSED"](https://ghuntley.com/cursed/)
- [HumanLayer — A Brief History of Ralph](https://www.humanlayer.dev/blog/brief-history-of-ralph)
- [anthropics/claude-code — ralph-wiggum plugin](https://github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum)
- [github.com/ghuntley/how-to-ralph-wiggum](https://github.com/ghuntley/how-to-ralph-wiggum)
