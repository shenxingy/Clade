---
name: 2026-09-02-agent-orchestration-efficiency.md
date: 2026-09-02
status: integrated
review_date: 2026-12-01
summary:
  - "Measured, not estimated: across all 89 parallel Workflow runs on this account (1777 agents, 49.9 hours of makespan), 22.5 hours — 45% — was spent with exactly ONE agent still running. 55 of the 89 runs have a tail over 15%; 52 run under 55% utilisation. Nothing had ever read the data that says so."
  - "The result that changes how to write a workflow: agent count is not the problem, BARRIERS are. On this session's own runs a 110-agent pipeline() scored 80% utilisation with a 0% tail despite a 6.9x straggler spread, while a 10-agent parallel() barrier scored 55% with 19% of its makespan waiting on one agent."
  - "The lead session's own waste, from its transcript: 702 turns, 946k output tokens, and 81 of 321 Bash calls (25%) were pure status polls of background jobs against 3 uses of Monitor. 76 stop-hook interrupts, most of them while ten subagents were mid-write and committing would have been wrong."
  - "The verification pass that ran BEFORE implementation is the opposite of waste: it corrected about half the audit's specifics and killed four findings that were not defects, two of which would have been actively harmful to implement."
  - "The theory is cleaner than expected and mostly bad news for sophistication: Graham's list-scheduling bound (2 - 1/m) requires NO duration knowledge, its only precondition being that no slot idles while work is ready — exactly what a parallel() barrier violates. Perfect duration knowledge buys only LPT's 4/3. So the whole value of estimation is the gap between 2 and 4/3, and Clade was not collecting the 2."
  - "Prediction is measured impossible, not merely hard: 8 frontier models predicting their own token cost on SWE-bench Verified scored Pearson r 0.05-0.39, and runs on the SAME task differ by up to 30x. HPC scheduling separately found that injecting +5% to +100% error into runtime estimates barely moved FCFS performance — accuracy was never the objective."
  - "Hedged and tied requests are rejected with reasons recorded, because their headline numbers (24x tail cut for 2% load; -38% for <1%) are the most likely thing to be cited by analogy and both depend on properties Clade lacks: a queueing phase, and cancellable not-yet-started work."
  - "No mainstream agent framework does dynamic load balancing — verified in LangGraph, CrewAI, OpenHands and the OpenAI Agents SDK source. Claude Code's own subagents are the exception and the model to copy. Anthropic's 16-agent C compiler fixed its stragglers with GRAIN SIZE."
  - "The largest measured lever is not scheduling: worktree-per-worker made every fan-out N cache writes (1.25x base input) where N-1 could have been reads (0.1x). Fixed in this branch."
  - "Rework has not improved in six months: 184 targeted fixes landed within 7 days of a feature on the same file, out of 864 commits, and the monthly rate sits flat at 9-15% while the correction-capture machinery has been accumulating rules the whole time. Normalising by touch count also KILLED the obvious hypothesis — the highest rework rates are small hooks and gate scripts, not the oversized hub files, which top the raw list only because they are touched constantly."
integrated_items:
  - "configs/scripts/workflow-scorecard.py — reads the per-agent transcripts every Workflow run already writes and reports peak/mean concurrency, utilisation, the single-agent tail share, and the straggler ratio. Stdlib-only. Before it, 80 MB of process data existed for this project alone across 56 projects and not one line of code opened any of it."
  - "configs/hooks/stop-check.sh — detects live subagent transcripts and stays quiet while agents are writing, because every uncommitted file at that moment belongs to an agent mid-task. STOP_CHECK_AGENT_IDLE_S tunes the window; 0 restores the old behaviour. Five tests pin both directions."
  - "Global instruction rule: one Monitor, then yield. Never poll a background job in a loop."
needs_work_items:
  - "Nothing yet enforces pipeline-over-barrier when a fan-out has stages; the scorecard reports the tail after the fact rather than preventing it."
  - "Anthropic's documented fix for the first cache mechanism — stagger the fan-out so the first response primes the prefix — is not implemented; only the system-prompt half is."
  - "Adversarial verification with N skeptics is measurably overspent (Terminal-Bench V2: 73.1% at K=1 to 77.5% at K=16). One better-calibrated verifier belongs in worker_review.py instead."
  - "Unit sizing is still done by topic rather than by estimated size, which is what produced the 2.0x straggler in this session's implementation wave."
  - "Derived-fact syncs (doc-align) ran three times because each wave added scripts; they should run once, after all writers finish."
---

**English**（中文版尚未提供 — [README 中文版](../../README.zh-CN.md)）

← Back to [README](../../README.md) · index: [Research](README.md)

# Agent orchestration efficiency — what the transcripts actually say

## Why this exists

The question was posed plainly: a parallel fan-out finishes when its slowest
agent finishes, so wall-clock is set by the straggler while every other agent
sits idle having already burned its tokens. How should we decide what each agent
is capable of, and how should we assign work?

Before answering it from theory, it was worth checking whether anyone had ever
measured it here. Nobody had. Every `Workflow` run writes a complete per-agent
transcript under

```
~/.claude*/projects/<slug>/<session>/subagents/workflows/wf_*/agent-*.jsonl
```

and as of this morning **not one line of code in this repository opened those
files**. `/retro` mines git history. `session-scorecard.sh` mines the
corrections log. `commit-archeology.sh` mines commits. All three measure
outcomes; none measures process. 80 MB of process data existed for this project
alone, across 56 projects, and the only way anyone learned whether a fan-out was
efficient was to notice that it felt slow.

`configs/scripts/workflow-scorecard.py` now reads it.

## What it measures, and why not agent count

A fan-out holds a slot for its whole makespan whether or not the slot is doing
anything, so "how many agents" answers nothing. Five numbers do:

| metric | meaning |
|---|---|
| `peak` | most agents ever running at once — the parallelism actually reached, usually below the configured cap |
| `mean` | average concurrency across the run, from a timeline sweep |
| `util` | `mean/peak`. Capacity bought that was in use |
| `tail1` | share of makespan with exactly ONE agent still running |
| `straggler` | slowest / median agent duration |

`tail1` is the straggler tax in its purest form: everyone else has finished and
paid, and the run cannot end.

One correction the first measurement forced. A run that never had two agents in
flight has a 100% tail by construction — one agent alone *is* the whole run.
Counting those as stragglers inflated the aggregate badly; they were four of the
five worst-looking runs. The tool now reports them as `sequential` and excludes
them.

## The headline number

Across every parallel Workflow run recorded on this account:

| | |
|---|---|
| runs with real parallelism | 89 |
| agents spawned | 1,777 |
| total makespan | 49.9 h |
| spent waiting on one agent | **22.5 h — 45%** |
| runs with a tail ≥ 15% | 55 of 89 |
| runs under 55% utilisation | 52 of 89 |
| worst single run | 111 minutes lost to its tail |

Nearly half of all multi-agent wall clock on this account is straggler tail.

## Shape beats count

This session ran five workflows. Their scorecards:

| workflow | agents | makespan | peak | util | tail1 | straggler |
|---|---|---|---|---|---|---|
| verify + plan (`pipeline` of one stage) | 12 | 13.8 m | 12 | 71% | 4% | 1.5x |
| implement wave A (`parallel` barrier) | 10 | 19.6 m | 10 | **55%** | **19%** | 2.0x |
| split wave B (`parallel` barrier) | 2 | 10.5 m | 2 | 89% | 21% | 1.1x |
| adversarial review (`pipeline`, 2 stages) | 110 | 26.8 m | 16 | **80%** | **0%** | **6.9x** |
| research (`parallel` barrier) | 6 | 3.7 m | 6 | 87% | 1% | 1.0x |

The review is the interesting row. It had by far the widest spread — its slowest
agent took 6.9x the median — and it still finished with a **zero** single-agent
tail and the best utilisation of the five. Because it is a `pipeline`, each
finding's short refuters started as soon as their dimension's long review
returned, so freed slots refilled continuously.

Wave A had a *narrow* spread by comparison, 2.0x, and wasted nearly a fifth of
its makespan. It is a barrier: ten independent groups, no stages, nothing queued
behind them, so when the first agent finished at 5 minutes its slot stayed empty
until the last finished at 19.6.

**A pipeline absorbs variance. A barrier converts it into idle capacity.** That
is the whole lesson, and it is the opposite of the intuition that a 110-agent
run must be the wasteful one.

The corollary for unit sizing: wave A's groups were cut by *topic* — auth,
redaction, CI, portability — not by estimated size, so their durations ranged
from about 5 to 19.6 minutes with no way to rebalance. Cutting the same work
into more, smaller units with a queue behind them would have packed the slots
whatever the estimates were, which is the useful half of what work-stealing buys
in a CPU scheduler: you do not need duration estimates if you have queue depth.

## Where this session's own tokens went

From the lead session's transcript:

| | |
|---|---|
| assistant turns | 702 |
| assistant output tokens | 946,076 |
| Bash calls | 321 |
| **of those, pure status polls of background jobs** | **81 (25%)** |
| `Monitor` calls (the correct instrument) | 3 |
| stop-hook interrupts | 76 |

A quarter of every shell call in a nine-hour session produced nothing but a line
saying how many agents had finished. The mechanism is a loop: the turn ends, the
Stop hook fires, that wakes the session, it checks status and replies, the turn
ends. The instrument that ends it — a single `Monitor` armed once — was reached
for only after roughly forty polls.

Both halves are now fixed rather than merely noted:

- `stop-check.sh` detects live subagent transcripts and stays quiet while agents
  are writing. Its 76 interrupts were all correctly refused, because committing
  an agent's half-finished files would have been wrong — and a gate that is
  right to ignore teaches people to ignore gates.
- The global instructions now say: one Monitor, then yield; never poll in a
  loop; fill a genuine wait with work that cannot conflict.

## Rework, classified honestly

13 of the branch's 24 commits touch a file an earlier commit on the same branch
already touched. That raw number overstates the problem — `CLAUDE.md` and
`TODO.md` are hubs and are legitimately touched many times. Classified:

- **Two genuinely self-inflicted defects.** Both fix the same commit: the CORS
  regex admitted all of `100.0.0.0/8` when Tailscale uses `100.64.0.0/10`, and a
  bare `startswith("/web")` made `/webhook` public. Both were found by probing
  after the fact rather than by a test failing first.
- **One cross-wave breakage.** The file split moved a function that two SWE-bench
  eval scripts called through the module object, and no CI gate covers those
  scripts. The agent that made the split found it and reported it because it was
  told to report anything outside its file ownership rather than fix it.
- **Roughly nine doc-sync re-touches.** `doc-align.py` had to run three times
  because each wave added scripts and moved a derived count. Sequencing fix: run
  derived-fact syncs **once**, after every writer has finished, not per wave.

## Implementation speed: the rework rate has not moved in six months

The other half of the question was whether the project itself is being built
efficiently — whether things that could have been designed right the first time
are instead landing and then being repaired.

Proxy, and its limits stated up front: count a **targeted** `fix` (touching five
files or fewer, so a repo-wide sweep does not qualify) landing within seven days
of a `feat` or `refactor` that touched the same file. That is not proof any
given pair is rework — some of it is legitimate iteration on a thing still being
built — but it is consistent over time, which is what makes the trend readable.

Over 864 commits in 180 days: **184 such pairs across 97 files**, about 21% of
commits. By month:

| month | commits | with rework | rate |
|---|---|---|---|
| 2026-03 | 149 | 16 | 11% |
| 2026-04 | 186 | 16 | 9% |
| 2026-05 | 22 | 0 | 0% |
| 2026-06 | 158 | 22 | 14% |
| 2026-07 | 179 | 22 | 12% |
| 2026-08 | 144 | 19 | 13% |
| 2026-09 | 26 | 4 | 15% |

May is an artifact — 22 commits is too few to read. Ignoring it, the rate is
flat to slightly worse across six months. **The correction-capture machinery has
been accumulating rules the whole time and the rework rate has not moved.**
That is worth sitting with: rules are being written, and either they are not
reaching the moment of decision, or they are not the binding constraint.

Where the reworked files live:

| area | share |
|---|---|
| `orchestrator/` | 27% |
| tests | 20% |
| `configs/scripts/` | 15% |
| skills and plugins | 11% |
| `configs/hooks/` | 8% |

One hypothesis this measurement **killed**. The obvious story is that the
oversized hub files drive rework, and the raw counts support it: `worker.py` 20
follow-up fixes, `loop-runner.sh` 13, `config.py` 12. But normalising by how
often each file is touched at all inverts the ranking — the highest *rates* are
small hooks and gate scripts (`pre-tool-guardian.sh` 50% of its touches,
`design-lint.py` 50%, `memory-sync.sh` 40%), while the hubs sit far down. The
hubs appear at the top of the raw list only because they are touched constantly.

That matches the shape this repository keeps rediscovering, and which the
2026-08-29 audit named: *a control that exists, is documented as working, and
never applies*. Hooks and gates are exactly where that failure lives, because
their failure mode is silence — they do not crash, they simply stop mattering,
and nothing notices until someone measures. Three of this session's own findings
were that shape: a checklist gate blind to the gate that had just been added, a
scorecard whose counters had read zero for the life of the file, and a stop hook
whose 76 interrupts were all correctly ignored.

The actionable reading is not "write fewer hooks". It is that **a control needs a
test that proves it can fail** — the red phase — and this repository already
knows that (`red-phase-audit.py`, `--self-test`) without applying it to its own
hooks.

## A negative result: the three generated surfaces are not the problem

Worth checking, because the setup looks expensive: every shipped skill exists in
up to four places — `configs/skills/` as canonical, then generated copies in
`mcp-package/skills/`, `plugins/clade/skills/`, and a generated `agents/` tree —
each with its own regeneration script and CI drift gate. 560 source files
producing 184 generated ones.

Measured over the same 865 commits: **8 are pure regeneration churn, about 1%**,
and 52 touch a generated surface at all. The drift gates catch staleness at
commit time rather than letting it accumulate, which is the whole point of
having them, and the cost of running four regen scripts is not showing up in the
history.

Do not spend effort here. The one visible wart is a sync / revert / re-sync
triple around the `research` skill (`5e8f4ed` → `0807199` → `2749a8c`), which is
three commits for one regeneration — the same "run the derived-fact sync once,
at the end" lesson as `doc-align`, not a structural problem with generation.

## The verification pass paid for itself

The obvious place to cut, if the goal is fewer tokens, is the read-only pass
that ran before any implementation: 12 agents, 1.75M tokens, 13.8 minutes,
producing no code.

Cutting it would have been the expensive choice. It corrected about half the
audit's specifics and killed four findings outright:

- Splitting `worker.py` by responsibility, which the topology measurement showed
  was not available for a 60-attribute stateful class and rested on a false
  claim that every leaf routed through it.
- Deleting two agents that turned out to be live, one of them contract-tested.
- Writing a `task_schema` test that already existed.
- **Wiring `reaction_configs` as published** — which would have silently dropped
  two of five reaction rules for anyone using the generated reference file.

That last one is the argument in miniature: the finding was written in good
faith, the fix sounded obvious, and implementing it would have introduced a
defect. Verification before implementation is not overhead on a fan-out of ten
writing agents; it is what stops ten agents confidently implementing the wrong
thing in parallel.

## What the outside world says, and what it kills

Six research lanes, sourced to primary papers and to framework source rather
than docs. The useful half is what they *reject*.

### The theory gives a cleaner answer than expected

Graham's list-scheduling bound is **2 − 1/m, and it requires no duration
knowledge at all**. Its only precondition is that no slot sits idle while work
is ready — which is exactly what a `parallel()` barrier violates. Knowing every
duration perfectly buys LPT's 4/3 − 1/(3m).

So the entire value of duration estimation is the gap between 2 and 4/3, and
Clade is not even collecting the 2. Fixing the barrier is worth more than any
estimator could be, which is why the change that shipped today is a rule about
shape and not a predictor.

### Prediction is not merely hard, it is measured impossible

"How Do AI Agents Spend Your Money?" (arXiv 2604.22750, Microsoft Research +
Stanford) had eight frontier models inspect a repository and predict their own
token cost on SWE-bench Verified before executing: **Pearson r between 0.05 and
0.39**, systematically biased low, and in-context examples of human cost
breakdowns did not fix the bias. Underneath that is a floor no model can beat:
**runs on the same task differ by up to 30x in total tokens.**

And accuracy is not the objective anyway. HPC scheduling work that injected
deliberate error into runtime estimates — +5%, +10%, +20%, +40%, +100% — found
FCFS performance barely moved. Retire "we need a duration estimate" as a
requirement.

### Three classical fixes that do not transfer, and exactly why

These are the ones most likely to be proposed by analogy, so the reasons are
recorded rather than the verdicts.

- **Hedged requests** (Dean & Barroso: p99.9 1800 ms → 74 ms for 2% extra load).
  That 24x is real and irrelevant. The paper says why in its own words: it is
  hedging *queueing* delay, and "once a request is actually scheduled and begins
  execution, the variability of its completion time goes down substantially".
  98% of hedges never run, which is what makes them cost 2%. A Clade agent has
  no queue phase — `worker.py` spawns the CLI and it starts spending
  immediately. The variance *is* the service time. A hedge here is a second
  full-price agent that runs to completion with certainty.
- **Tied requests** (−38% p99.9 for under 1% overhead — the best ratio in the
  literature). It works entirely by cancelling work *that has not started*.
  Clade has nothing in that state; killing a worker stops future spend and
  refunds nothing, and `worker_evidence.py` already books the sunk tokens.
- **Work stealing.** The randomised deque exists to keep scheduling overhead
  negligible against nanosecond tasks, and a steal moves an *unstarted* frame.
  Neither property holds. What does transfer is the trivial part: a queue deeper
  than the slot count.

**MapReduce backup tasks** are the interesting middle case. Disabling them made
a sort take 44% longer — five of ~1700 tasks held the job for 300 seconds — and
the trigger was not a prediction but a *phase predicate*: most tasks are done,
these few are not. That predicate transfers and costs nothing to compute. The
economics do not: one duplicate against 1700 is "a few percent", one duplicate
in a fan-out of eight is +12.5%.

### Nobody else has solved this either

Read in source, not documentation: LangGraph's `PregelRunner.tick` drains all
futures before the next superstep; CrewAI spawns an unbounded thread per async
task and then joins **in submission order**, so even result processing is
head-of-line blocked behind the straggler; OpenHands' `DelegateTool` is
literally start-all / join-all with `max_children=5`, and non-blocking
delegation is an open feature request; the OpenAI Agents SDK documents
`asyncio.gather` as the whole parallelism story; AutoGen runs exactly one agent
at a time.

**Not one mainstream framework does dynamic load balancing across agents.** The
exception is Claude Code's own subagents, which are background-by-default and
not barrier-synchronous — the model to copy.

The one published multi-agent run with real numbers points the same way as the
measurement above: Anthropic's 16-agent C compiler used file-lock task claiming,
and its straggler fix was **grain size**.

### The largest lever is not scheduling at all

Two mechanisms, both documented by Anthropic, mean a Clade fan-out pays a cache
**write** (1.25x base input) for a prefix a sibling could have **read** (0.1x) —
12.5x on the shared part of the prompt:

1. "A cache entry only becomes available after the first response begins… If you
   need cache hits for parallel requests, wait for the first response before
   sending subsequent requests." A simultaneous fan-out is N misses by
   construction.
2. The default system prompt embeds the working directory, so
   worktree-per-worker guarantees no two workers share a prefix even
   sequentially.

The second is fixed as of this branch — `--exclude-dynamic-system-prompt-sections`
on every worker spawn, behind `worker_shared_prompt_cache`. The first needs a
stagger, which Claude Code already implements inside its own Workflow runtime.

### And a finding that indicts this session's own method

Terminal-Bench V2 pairwise verification accuracy: a discrete judge goes from
**73.1% at K=1 to 77.5% at K=16**. Sixteen times the verification spend for 4.4
points. This session ran three refuters per finding on 28 findings. A single
better-calibrated verifier returning a score plus its evidence is the cheaper
shape, and `worker_review.py` is where that belongs.

## What changed today

| change | file |
|---|---|
| Read the process data that was already being written | `configs/scripts/workflow-scorecard.py` |
| Stop nagging while subagents hold the tree | `configs/hooks/stop-check.sh` + 5 tests |
| One Monitor, then yield | global instructions |

## What has not changed yet

- Nothing enforces pipeline-over-barrier. The scorecard reports a tail after the
  fact; it does not prevent one.
- Units are still cut by topic rather than sized. The cheap fix is queue depth,
  not estimation: more, smaller units than slots.
- Derived-fact syncs still run per wave rather than once at the end.
