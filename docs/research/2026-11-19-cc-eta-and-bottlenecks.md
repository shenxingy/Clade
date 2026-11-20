---
title: "How long is left, and where does the time go? Claude Code task duration, measured"
date: 2026-11-19
review_date: 2027-01-19
status: needs_work
summary: >
  The owner asked whether Claude Code can say how much longer the current task
  will run, and where the time goes. Measured on 1,137 human-started episodes
  (450 main-thread transcripts, five profiles, 2026-10-16..11-20), 74.3% of
  episode wall time is waiting on background work between turns (Monitors,
  Workflows, background Bash); inside a turn, model round trips are 56.3% and
  foreground Bash 37.0% of 423.4 h; hooks are about 1%. The model cannot state
  an honest ETA: it has no clock, and its own estimates add little beyond a
  base rate. A survival lookup on elapsed time, tested on a held-out week,
  gives an honest p25-p75 band (40-54% coverage) but no trustworthy point
  (within 2x 20-41%), and nothing visible mid-task narrowed it. So the ETA
  belongs on the statusline as a range, with statusLine.refreshInterval set.
  How much any setting shortens a run is not measured.
integrated_items:
  - "Statusline task-elapsed + history-based remaining range, refreshInterval 10 (#259, merged 2026-11-20)"
  - "2026-11-20: the band prints only when at most 4x wide, a Monitor's timeout bounds it, and the line fits COLUMNS (branch feat/statusline-compact)"
  - "TODO.md § 2026-11-19 task-ETA and bottleneck follow-ups"
needs_work_items:
  - "Owner: decide the three knob trials (ultracode/Workflow size, default effort, stop-check diet), each as a concurrent treated-vs-control split"
  - "Commit the time decomposer as an instrument so the trials can be measured"
  - "Trace why 39% of main-thread Opus 5.5 calls ran at max effort"
reference_items:
  - "NOT MEASURED: the wall-time effect of any knob; time inside Workflow runs; the statusline refresh on screen"
---

# How long is left, and where does the time go?

Research, 2026-11-19 (transcript data through 2026-11-20 UTC). Measured on one
Linux host from the owner's own Claude Code 2.1.283 transcripts across five
profiles, by a multi-agent run with an independent re-derivation lane and a
claim critic. The measurement scripts ran in a session scratch directory and are
not committed; bracketed keys ([A1], [V1], ...) name the lane each number came
from, listed under "Populations and sources".

## Verdict: the owner's three questions

**1. Can Claude Code put "time remaining" in its replies? No.** The model is given the date but not the time of day, so it has no clock [M]. A CLAUDE.md or output-style rule that demands an ETA line would get invented numbers. The model's own "~N min" estimates also add little beyond a base rate (section 2, P2). **The number belongs on the statusline:** a script reads `transcript_path`, with `statusLine.refreshInterval` set. None of the 5 profiles sets it today [M]. The script shows the task's elapsed time and a range computed from history. Without `refreshInterval` the statusline goes quiet during exactly the waits where an ETA matters (event-driven, 300 ms debounce; confirmed in the CC 2.1.283 binary) [M].

**How good that range is.** Tested on the held-out week 2026-11-12..20 (main thread, five profiles, fitted on earlier items) [A2]:
- **The range is honest; the point is weak.** The p25-p75 band holds the true remaining time 40-54% of the time, against the 50% a calibrated band would hold. The median lands within 2x 27-41% of the time for turns (n = 407 alive at 1 min down to 32 at 60 min, of 692 test turns). For human-started episodes it is 20-38% (n = 157 down to 49, of 196 test episodes).
- **Background tasks are the most predictable part.** One in-flight background task lands within 2x 50% and 56% of the time at 1 and 5 min after launch (n = 958 and 725 of 1,039 test background tasks).
- **It beats the global median.** For turns the gain is +21.9 points (95% CI +17.5..+27.2). For episodes the shipped elapsed-only lookup gains +19.2 points, with no CI computed. Both are pooled within-2x over checkpoints 1, 5, 15, 30 and 60 min, unweighted. (The +16.1 in A2's summary belongs to a model that was dropped; see Corrections.)
- **It fails on long tasks.** Items that end up running 4 h or more are never within 2x: 0 of 20 turn checkpoint rows and 0 of 85 episode checkpoint rows (test week, checkpoints 1-60 min).

No signal we tested makes a point estimate trustworthy. A2's explanation: the remaining time is set by the background work the agent launched, not by anything visible in what it has done so far. Even an oracle that knows a Workflow's true done/total fraction reaches only 46-49% within 2x (461 Workflow runs, leave-one-week-out).

**2. Where is the bottleneck? Waiting on background work between turns.** It takes 74.3% of the wall time of human-started episodes (1,177 h of 1,585 h; n = 1,137 episodes, 450 main-thread transcripts, five profiles, turns started 2026-10-16..11-20). The verification lane re-derived 74.3% independently (n = 1,116). Shares of the same 1,585 h of human-started episode wall:
- Monitor event streams: 26.8%. This is the largest share, and it is open-ended.
- Workflow runs: 21.3%. This is the largest wait with a defined end; p50 wait 31 min.
- Background Bash poll loops: 12.8%.

Inside a turn, the time goes to the model's own round trips (56.3%) and foreground Bash (37.0%). Both are shares of 423.4 h of turn wall over 3,749 turns, same transcripts. Hooks are 0.4-0.5% of turn time by the hooks lane's own measure, and about 1.0-1.3% against a timestamp-based denominator. Tests and compaction are each at most 2.4% of turn wall.

**3. How do you tune how long Claude Code runs? Not yet answerable from measurement.** No lane measured the wall-time effect of any setting. The measured part is how much time each setting governs:
- `ultracode: true` with `workflowSizeGuideline: "large"` governs the Workflow wait, 21.3% of episode wall.
- `effortLevel: "xhigh"` governs model time, 56.3% of turn wall.
- `stop-check.sh` re-entries total 20.2 h, about 4.8% of turn wall.

That these settings make runs longer is inference. The knobs lane labels its magnitudes "direction only". Its effort figure (low and medium matched xhigh's accuracy at 29-52% of the output tokens) counts output tokens on 15 claims, not wall time. A1's per-call effort table is not causal. Section 4 gives the treated-vs-control trials that would measure each effect.

## Populations and sources

File names in this table are the research run's own outputs. They lived in a session scratch directory and are not committed; committing the decomposer is a TODO item (TODO.md § 2026-11-19).

| Key | Source | Population |
|---|---|---|
| A1 | `a1-decompose/summary.md` (`per_turn.jsonl`, `per_episode.jsonl`, `per_session.jsonl`) | 450 main-thread transcripts (mtime 30 d or less), profiles main and main1-4, turns started 2026-10-16..11-20. **E** = 1,137 human-started episodes, 1,585.1 h. **T** = 3,749 turns, all triggers, 423.4 h |
| V1 | `v1-verify/verify.md` (`gapall_summary.txt`, `coststate.json`, `turns5.json`) | Same 450 files, independent gap-attribution method |
| A2 | `a2-predict/eta_eval.md`, `results.json`, `fit.log`, `timing.txt` | 479 main-thread files (2.1 GB, no mtime filter). **Test** = items started 2026-11-12..11-20. **Fit** = items started before 11-12 |
| H | `h-hooks/hooks.md` (`agg.json`, `est_summary.txt`, `pass3_summary.txt`, `bench.json`) | mtime on or after 2026-10-20: 290 main-thread and 6,325 subagent files, five profiles; hook totals are main-thread, 177 sessions with `turn_duration` |
| M | `m-surfaces/surfaces.md` (`binary-evidence.txt`, `docs/`) | CC 2.1.283 binary plus docs fetched 2026-11-19; the 5 profiles' settings.json |
| K | `k-knobs/knobs.md` (`scan14d.json`, `stopblocks.txt`, `tools14d.json`) | 309 main-thread files, mtime 14 d or less, five profiles |
| P | Prior-art lane, returned inline only (`lanes-index.json` key `p`) | Public docs, source and papers fetched 2026-11-19 |
| S1 | `synthesis/stopreentry_30d.json`, `stopreentry_14d.json` (`stopreentry.py`) | Main-thread files, mtime 30 d or less (450) or 14 d or less (309), five profiles |
| S2 | `synthesis/recheck_a1.json` (`recheck_a1.py`) | E, from `a1-decompose/per_episode.jsonl` |

## 1. Where the time goes

### Episodes

Population: E (n = 1,137 human-started episodes; 1,585.1 h) [A1 §b]. Shares are of human-started episode wall time.

| # | Component | Hours | Share | Verified [V1] |
|---|---|---:|---:|---|
| 1 | **Background wait between turns** | 1,177.3 | **74.3%** | 74.3% (1,183 of 1,592 h, n = 1,116) |
| 1a | Monitor event streams (open-ended) | 424.4 | 26.8% | not re-derived |
| 1b | Workflow runs | 337.5 | 21.3% | not re-derived |
| 1c | Background Bash poll loops | 202.4 | 12.8% | not re-derived |
| 1d | Other background Bash | 122.7 | 7.7% | not re-derived |
| 1e | Async Agents | 26.0 | 1.6% | not re-derived |
| 1f | Usage-limit resumes | 25.3 | 1.6% | not re-derived |
| 1g | Stop-hook rewakes (async Stop hook notifications) | 19.1 | 1.2% | not re-derived |
| 1h | SendMessage replies | 14.7 | 0.9% | not re-derived |
| 1i | Wakeups | 4.0 | 0.3% | not re-derived |
| 2 | Model, main thread | 224.5 | 14.2% | — |
| 3 | Foreground Bash | 155.5 | 9.8% | — |
| 4 | Human answering AskUserQuestion | 11.3 | 0.7% | — |
| 5 | Compaction | 10.2 | 0.6% | — |
| 6 | Prompt Stop hook | 3.0 | 0.2% | — |
| 7 | Unattributed | 2.6 | 0.2% | — |

Details behind rows 1a-1c [A1 §b launcher table]:
- Monitor: 52 episodes, p50 gap 4.8 min.
- Workflow: 248 episodes, p50 gap 31.4 min, p90 2.04 h.
- Poll loops: 178 episodes, p50 gap 12.9 min.

The finding survives four robustness checks:
- **Per episode** [A1, V1]: the median episode spends 67.7% in background wait (n = 512 episodes of 10 min or more). V1 gets 67.5% (n = 513).
- **Largest component** [A1, V1]: background wait is the largest component in 329 of those 512 episodes. V1 puts a lower bound of 310 on it, of 513.
- **Without open-ended waits** [A1 only]: 62.8% of 1,097.7 h (n = 1,137), after dropping gaps that end in a Monitor event, a Stop rewake, a wakeup, a usage-limit resume or a SendMessage reply. Also limited to episodes under 24 h: 65.5% of 1,040.1 h (n = 1,132).
- **Without the largest project** [S2]: that project holds 58.5% of episode wall. The other 599 episodes (657.6 h) still spend 71.7% in background wait.

Episodes with a Workflow call: 324 episodes, 987.2 h, 86.4% of it waiting [S2]. The A1 prose says 325 / 993 h / 86.5%; A1's own table and S2 give 324.

**Heavy tail** [A1, E]. The top 5 episodes hold 28.9% of episode wall and the top 20 hold 43.2%. The longest, 256.9 h, is a Monitor stream. Episodes of 8 h or more are 2.6% of episodes (30) and 49.0% of wall. Human-started episodes run p50 6.4 min, p75 47 min, p90 2.88 h.

**Most API time is off the main thread.** In the 135 sessions with an Agent or Workflow call, main-thread model time is 0.18x `totalAPIDuration` [A1 §f]. V1 gets 0.186x over 134 sessions. So about 82% of API time in those sessions is subagent or Workflow work. Workflow internals are not decomposed here.

### Turns

Population: T (n = 3,749 turns, all triggers; 423.4 h) [A1 §a]. Shares are of turn wall time.

| # | Component | Hours | Share | Verified [V1] |
|---|---|---:|---:|---|
| 1 | **Model** | 238.5 | **56.3%** | 56.7% |
| 2 | **Foreground Bash** | 156.6 | **37.0%** | 37.1% |
| 2a | sleep/poll loops | 63.6 | 15.0% | — |
| 2b | Python scripts | 18.8 | 4.4% | — |
| 2c | File writes | 14.4 | 3.4% | — |
| 2d | File reads | 14.1 | 3.3% | — |
| 2e | git | 12.7 | 3.0% | — |
| 2f | ssh | 9.7 | 2.3% | — |
| 2g | Tests | 5.2 | 1.2% | — |
| 3 | Human answering | 11.3 | 2.7% | 2.7% |
| 4 | Compaction | 10.3 | 2.4% | 2.5% |
| 5 | Prompt Stop hook | 3.1 | 0.7% | 0.7% |
| 6 | Unattributed | 2.7 | 0.6% | — |

- **Poll loops:** 1,758 foreground calls (T), p50 30 s, p90 6.2 min.
- **Model calls:** 80,669 calls (T), p50 6.3 s, p90 20.9 s, about 91 output tokens/s. Turns of 10 min or more make p50 59 calls (n = 427).
- **Long turns** (10 min or more): model 50.0%, Bash 42.7% (n = 427). V1 gets 50.4% / 42.8% (n = 429).
- **Validation against Claude Code's own counters:** in 301 sessions without subagents, model time is 0.95x `totalAPIDuration` and tool time 1.03x `totalToolDuration`. V1 reproduces 0.950x / 1.030x on 264 sessions. A deliberate mutation of the method drops the model ratio to 0.84.

**Stop-check re-entry** [S1; 450 main-thread files, mtime 30 d or less, five profiles]. `stop-check.sh` blocked 634 of 3,945 Stop events (16.1%), and the model continued after 632 of them. After the 3,311 Stop events it did not block, the model continued 0 times. Each re-entry runs from the blocking stop summary to the next one: 632 re-entries, 20.16 h in total, p50 4.7 s, p90 25.7 s. That total is about 4.8% of T's 423.4 h. The two figures come from the same 450-file population but were computed separately. The re-entry happens before the turn's `turn_duration` record, where A1's turns end, so it falls inside A1's turn wall and is already spread over its model and Bash rows. (That follows from the two definitions; it was not checked turn by turn.) This is more than the prompt Stop hook's 0.7% and small next to background wait. Part of the time is presumably the work the block asked for (K: "usually a commit"); how much is useful is not measured.

**Hooks** [H]. Main-thread hooks total 4.44-5.71 h in 30 d (177 sessions). H divides that by a `turn_duration` sum of 1,104.4 h and gets 0.40-0.52% of turn time. A1 found `turn_duration` is not a per-turn wall for notification turns: in 186 of 2,168 such turns it equals the time since the episode's human prompt. Against A1's timestamp-based 423.4 h the share is about 1.0-1.3%. That is a mixed-population ratio, not re-derived on one population. Either way hooks are minor.
- The prompt Stop hook costs p50 2.74 s and p90 3.94 s at every turn end (n = 3,914 Stop events).
- Sync Bash pre/post hooks cost 63-127 ms per call (72,245 main-thread Bash calls).
- `commit-archeology.sh` hit its 15 s SessionStart timeout 26 times (181 recorded starts).

## 2. ETA

P1 is the survival lookup on elapsed time (shipped with no conditioning feature). P0 is the global median. Test population as in the verdict [A2].

| t | Turns n | P0 | **P1** | Band | Episodes n | P0 | **P1** | Band |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 min | 407 | 26% | **33%** | 42% | 157 | 21% | **20%** | 54% |
| 5 min | 197 | 15% | **31%** | 41% | 120 | 15% | **35%** | 48% |
| 15 min | 95 | 8% | **27%** | 40% | 89 | 12% | **36%** | 52% |
| 30 min | 50 | 4% | **30%** | 46% | 69 | 7% | **38%** | 51% |
| 60 min | 32 | 0% | **41%** | 50% | 49 | 10% | **33%** | 47% |

(P0 and P1 columns are within-2x rates; Band is p25-p75 coverage.)

- **Pooled gains** (unweighted mean over the five checkpoints):
  - Turns: +21.9 points (paired bootstrap 95% CI +17.5..+27.2). The validation-selected model and the shipped model are identical here.
  - Episodes, shipped elapsed-only P1: +19.2 points (`fit.log`: uncond 0.324 vs P0 0.132). No CI was computed for this pair.
  - The +16.1 points (CI +10.1..+22.1) in `results.json` `episode.boot_sel_vs_p0` belongs to the validation-selected "wait" model, which was dropped.
- **Typical miss:** 2.2x to 4.6x (median abs log2 error 1.17-2.19, across turn and episode checkpoints).
- **Long tasks:** 4 h or more is never within 2x (turns 0 of 20 rows, episodes 0 of 85; test week, checkpoints 1-60 min).
- **Features:** none helped on held-out data (project, phase, what is in flight, wait state, last tool, call count, turns so far). Validation picked the episode wait state. On test it scored 3.1 points below the elapsed-only lookup (CI -6.5..+0.1), so it was dropped.
- **Background tasks:** one in-flight background task lands within 2x 50/56/49/36/30% of the time at 1/5/15/30/60 min (n = 958/725/490/163/47 of 1,039 test tasks: 806 Bash, 123 Agent, 90 Monitor, 20 Workflow; fit on 2,170).
- **Workflow progress (P3)** (461 runs, leave-one-ISO-week-out): conditioning on the fraction of phases done raises within-2x from 40% to 48% at 15 min (n = 367) and from 41% to 45% at 30 min (n = 293). It adds nothing at 1-5 min. **An oracle that knows the true done/total fraction tops out at 46-49%.** The test week alone holds 25 runs (n ≤ 23 per checkpoint), too few to separate the methods.

**The model's own estimates add little beyond the base rate (P2; n = 744 parsed estimates, 171 precise; five profiles).**
- The model has no clock: the system prompt carries only the date [M].
- It usually times a sub-job, not the task. Against the rest of the turn its estimates land within 2x 6% of the time (n = 744). Against the rest of the episode it is 16% (all, n = 744) and 22% (precise, n = 171).
- On the fairer target, the next in-flight background job, precise estimates land within 2x 46% of the time (n = 103). An in-sample constant median scores 44%. The estimates overshoot by a median 1.4x.
- At the same test-week moments, rest of the episode: P1 47% vs precise text 28% (n = 32), and P1 24% vs all cued text 16% (n = 161). No CI was computed, and n = 32 is too small to carry a verdict. The direction agrees with A2's overall reading: text estimates add little beyond a base rate. It does not show the text is worse than the lookup on every target.
- The literature agrees [P]. Pre-task LLM duration estimates overshoot 4-7x (arXiv 2604.00010, abstract; 68 tasks, 4 model families), and agents are overconfident about their own success (arXiv 2602.06948, abstract).
- Caveat: this measures a parser. Its precision was 5 of 6 on a 10-snippet draw; recall is not measured.

**Prior art [P].** No coding agent checked shows time remaining. Codex CLI shows elapsed time only, and Aider a spinner only (both checked in source). Copilot shows session length, and Jules shows total runtime after the task (docs). CI systems compute ETAs from history:
- Jenkins takes the mean of up to 3 recent builds with result UNSTABLE or better (source). In JENKINS-21099, counting failed builds made the estimates useless.
- TeamCity uses about 5 matching finished builds.
- CircleCI uses previous workflow runs.

**Prototype `a2-predict/eta.py`** (research-run scratch; its port to `configs/scripts/task-eta.py` is in progress on branch `feat/statusline-task-eta`).
- Output, e.g. `task 55m · ~1.5h left (p50; p25-p75 35m-4.2h; n=248)` (`live_demo.txt`).
- Speed, as a subprocess, 5 runs per file over the 40 largest main-thread transcripts (`timing.txt`):
  - Median over files: 81 ms.
  - The largest file (220.6 MB): 97 ms.
  - The slowest file (22.1 MB, a long latest episode): 182 ms. That is over A2's 150 ms target and the only one of 40 files over it. An earlier run measured it at 152 ms.
- Its tail read matches a full parse on 120 of 120 transcripts.
- Four mutants fail its self-test, and a no-op control passes.

## 3. Where an ETA can be shown

Confirmed in the binary of CC 2.1.283 [M].

| Surface | Elapsed | Remaining | Refresh | Cost |
|---|---|---|---|---|
| **Statusline** | `cost.total_duration_ms` is session-level only; derive per-task elapsed from `transcript_path` | Only if the script computes it | Event-driven, 300 ms debounce. Quiet during waits **unless `statusLine.refreshInterval` is set** (seconds, min 1). None of the 5 profiles sets it | 0 tokens; one process spawn per tick |
| Spinner | Live, per turn | No | Live | None |
| "Cooked for" line | After the turn | No | Final only | None |
| Task list | No | Step N of M | Live | Off on Opus 5.5 (allowlist); `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` turns it on; context cost not measured |
| `/workflows` | Phase/agent state | done/total counts | Live | None |
| Hook additionalContext | As model input | As model input | No timer event (0 of 33 hook events) | Tokens per event |
| UserPromptSubmit hook injecting the clock | Lets the model report elapsed time truthfully | No; the model would still guess | Once per prompt | About 20 tokens per prompt (estimate, not measured) |
| MessageDisplay hook | Footer | If computed | Only while text streams | 0 tokens |
| OSC 9;4 / OSC 7501 | Busy/waiting/done state | No | Live | None |
| Output style or CLAUDE.md footer | No clock | Invented | — | Not recommended |

**Lane conflict closed.** A2 left the statusline's refresh cadence during idle waits open (`eta_eval.md:266`). M settled it from the docs and the binary: the trigger list plus a 300 ms debounce constant, and the docs' own note that event-driven updates "can go quiet when the main session is idle". So `statusLine.refreshInterval` is part of the recommendation, not an option. The behaviour has not been seen on screen.

## 4. Knobs, ranked by the measured share of time they govern (their effects are inference)

All five profiles share one `settings.json` and one `CLAUDE.md` [K]. The "Governs" column is measured. That changing a knob would change that time, and by how much, is not measured: K labels its magnitudes "direction only".

| # | Knob (current setting) | Governs (measured) | Effect of changing it | Source |
|---|---|---|---|---|
| 1 | `ultracode: true` + `workflowSizeGuideline: "large"` | Workflow wait, 21.3% of E's wall. Workflow episodes are 86.4% waiting (324 episodes). About 82% of API time is off the main thread (135 sessions) | Inference: fewer and smaller Workflows. Not every Workflow comes from `ultracode` | A1, S2, K |
| 2 | `effortLevel: "xhigh"` (the documented Opus 5.5 default is medium) | Model time, 56.3% of T's wall. Per-call p50 for main-thread Opus 5.5: medium 4.4 s (1,027 calls), high 4.9 s (6,476), xhigh 6.1 s (40,562), max 6.9 s (30,937). 39% of those 79,002 calls ran at max | Inference. A1's table is not causal: different efforts ran different tasks. The 29-52% figure counts output tokens on 15 known-answer claims (CLAUDE.md, via K), not wall time | A1, K |
| 3 | Persistent Monitors | 26.8% of E's wall, open-ended | Not separable from the human being away | A1 |
| 4 | Foreground poll habit | 15.0% of T's wall | This is the duration of the job being waited on, so moving it elsewhere does not remove it | A1 |
| 5 | CLAUDE.md gate/verify/land mandates | Not separable. 366 `ci-local` calls in 14 d (309 files) | Direction only | K |
| 6 | `stop-check.sh` | Blocked 634 of 3,945 Stop events (16.1%, 30 d, 450 files); the model continued after 632. 14 d: 529 of 2,540 (20.8%, 309 files). Re-entries total 20.16 h, about 4.8% of T's wall (p50 4.7 s, p90 25.7 s) | Upper bound on time saved; the useful share is not measured | S1 |
| 7 | `autoCompactWindow 350000` | Compaction, 2.4% of T's wall | Direction only | A1, K |
| 8 | Prompt Stop hook | 0.7% of T's wall; 4 blocks in 2,527 checks (14 d) | Removing it saves at most that 0.7% | A1, H, K |
| 9 | Sync Bash hooks | 1.2-2.5 h in 30 d (main thread) | Small | H |
| 10 | `/fast` (paid, opt-in only) | Model time | Vendor claim "up to 2.5x faster", at a higher per-token price | K |

**Three trials to run first.** These are K's measurement plan, adapted. Run each as a concurrent treated-vs-control split, using a project's `.claude/settings.local.json` as the treatment. Profiles cannot be split because they share one settings file. Do not run a before/after comparison: Workflow use fell after 11-10, from 470 runs before the cutoff to 25 in the test week. Use `outcome-scorecard.py --since 14` as the quality guard, so that a speed-up that causes rework shows up.
1. **`ultracode` opt-in, Workflow size `"medium"`.** Measure with `decompose.py`: episode wall p50/p75/p90, plus Workflow wait and Workflow calls per episode, for 7 days.
2. **Effort `medium` by default,** with xhigh or `ultrathink` on hard turns and a per-stage `effort` in Workflows. First trace why 39% of main-thread Opus 5.5 calls ran at max. Measure model time per turn, per-call p50 by effort, and output tokens per turn.
3. **Stop-hook diet.** `stop-check` warns instead of blocking. Pin a fast model on the prompt Stop hook, or drop it. Measure with `stopreentry.py`: re-entry count and hours against the 632 / 20.16 h baseline. Check that uncommitted work at session end does not rise.

## 5. Build proposal (one PR)

`feat(statusline): task elapsed time and a history-based remaining-time range`. In progress on branch `feat/statusline-task-eta` (2026-11-19).

It prints the band first and no point estimate. Proposed formats (the first two reuse values from `a2-predict/live_demo.txt`; the last two are format sketches without data):
- `task 55m · 35m-4.2h left (p25-p75, n=248) | bg bash 8m · 6m-53m left`
- `task 21m · idle | bg workflow 51m · 20m-2.2h left`
- `task <elapsed> · beyond history`
- `task <elapsed> | bg monitor <age> (open-ended)` (this case is unevaluated)

Files:
- **`configs/scripts/task-eta.py`**, a port of `a2-predict/eta.py` (834 lines). Stdlib only. Flags `--stdin`, `--json`, `--fit`, `--self-test`.
  - `--fit` writes the rolling 30-day survival grid to `~/.claude/task-eta-model.json`.
  - A lazy detached refit runs at most every 24 h, behind an `O_EXCL` lock.
  - A2's extraction read 479 files (2.1 GB) in 2 s, likely helped by the page cache (not checked). The fit itself is not timed.
- **`statusline-command.sh`**: an inline ETA segment. Drop-in segments get no stdin, so they cannot see `transcript_path`.
- **`install.sh`**: `statusLine.refreshInterval: 10` (M suggests 5 or 10). At 81-182 ms per run that is under 2% of one core per session. The other segments' cost is not measured.
- **`tests/test-statusline-eta.sh`**, plus an entry in `docs/ci-gates.md`.
- **`orchestrator/tests/test_self_tests_can_fire.py`**: the 4 mutants and a no-op control.
- **This report**, scrubbed.

Self-test (synthetic data only):
1. Seeded heavy-tailed durations: the lookup must beat the global median by a margin.
2. A Workflow still in flight after its turn reads `idle | bg workflow`, and p50 grows from 1 to 60 min.
3. A prompt typed during the Workflow still shows the Workflow.
4. A missing model or an unreadable transcript fails soft, with exit 0.

`--self-test --held-out 7` checks against the user's own last week. It runs locally, not in CI.

Acceptance: `ci-local` green, plus a live screenshot of the segment updating during a background Workflow.

Out of scope, as separate PRs: the task-tools env var, the knob trials, reading live Workflow progress (`meta.phases`), a per-transcript offset cache for the 182 ms file, and a ledger of ETA misses.

## 6. Not measured, and what would break each verdict

**Not measured:**
- The wall-time effect of `ultracode`, `workflowSizeGuideline`, effort or any other knob.
- A CI for the shipped episode gain (+19.2 points).
- How much stop-check re-entry time is useful work.
- Time inside Workflow runs; subagent transcripts were not decomposed.
- The statusline with `refreshInterval` on screen.
- The context cost of the task tools.
- The CI gate's own share; it is not separable from the python-script class.
- Full-project tsc on `.ts` edits.
- Silent hook durations.
- Prompt-time ETA features, and excluding interrupted items from the history.
- P2 recall.
- Whether the human was present during Monitor waits.

**What would break each verdict:**
- **No trustworthy point:** a prompt-time feature lifting held-out within-2x well above 40%. Live Workflow progress cannot do it (the oracle tops out at 46-49%). Test sets are small at 60 min (32 turns, 49 episodes).
- **Background wait is the bottleneck:**
  - Open-ended waits could be mostly human absence; the 62.8% view covers this.
  - One project could drive the result; it is 71.7% without the largest project.
  - The mix is not stationary: Workflow use fell after 11-10. Re-run `decompose.py` before acting on the 21.3% Workflow share.
  - The 30-day transcript deletion shifts the window on every re-run.
- **Hooks are minor:** unmeasured full-project tsc in TypeScript projects.
- **The model's estimates add little:** this rests on a parser with 6 hand-checked precise matches and on proxy targets.
- **The knob ranking:** a share governed is not a saving. The trials in section 4 could find any of these knobs neutral.

## Lane disagreements

- **A1 vs V1.** They agree within 1-5% relative. The cost-state gap (58.6% vs 52.1%) is a population mismatch; like for like it is 69.5% vs 71.2%. The launcher split, the 62.8% / 65.5% views and "329 of 512" are A1-only.
- **H vs K on `stop-check`.** K is right. S1 found the model continued after 632 of 634 blocks, against 0 of 3,311 unblocked stops. H's "non-blocking stderr notices" (`hooks.md:58`) is refuted. `preventedContinuation` measures something else. K's 523 of 2,532 (20.7%, 14 d) matches S1's 529 of 2,540 (20.8%).
- **Hook share.** H's 0.40-0.52% uses a `turn_duration` denominator; about 1.0-1.3% against A1's timestamp wall (mixed populations).
- **Prompt Stop hook p50.** 2.74 s (H, 30 d), 2.5 s (K, 14 d), 2.55 s (M, 3 d): consistent.
- **Workflow episodes.** S2 re-counts 324 / 987.2 h / 86.4%, matching A1's table rather than its prose (325 / 993 h / 86.5%).
- **Task tools.** One use in 309 files; the tools are gated off for Opus 5.5. Consistent.
- **Statusline refresh (A2 vs M).** Resolved in M's favour by binary and docs evidence (section 3). Not yet seen on screen.
- **A2's episode gain.** A2's summary and `eta_eval.md` (lines 12 and 99) report +16.1 points for P1 vs P0. That figure is the dropped "wait" model's. The shipped lookup's gain is +19.2 points, with no CI.

## Corrections after review

Each item is a problem from `critic/critic.md`. The fix was checked against the cited lane file.

1. **Episode gain mislabelled.** The +16.1 points (CI +10.1..+22.1) came from the validation-selected "wait" model. `results.json` `episode.boot_sel_vs_p0` with `chain ['wait']` and `ship_note` show it was dropped. The report now gives the shipped lookup's +19.2 points (`fit.log` 0.324 - 0.132), says no CI was computed, and notes A2's own mislabel. The turn figure, +21.9, was correct (selected and shipped are the same model).
2. **Report missing.** The harness refused the `.md` write for the synthesis agent and again for the fix agent ('Subagents should return findings as text'). Neither worked around the guard. This corrected text is returned as the last caveat of the fix agent's result, and the lead writes it to `synthesis/report.md`. The uncorrected draft is the last caveat of the synthesis agent's result.
3. **Populations added.** The Monitor / Workflow / poll-loop shares now say "of human-started episode wall (1,585 h, n = 1,137)". The 4 h line now says "0 of 20 turn and 0 of 85 episode checkpoint rows, test week, 1-60 min". The 632 / 634 line now says "450 main-thread files, mtime 30 d or less, five profiles".
4. **Owner question 1 answered.** The verdict now says no ETA in replies (the model has no clock; a CLAUDE.md or output-style line would be invented). It names the working route: a statusline reading `transcript_path`, with `statusLine.refreshInterval`, which is unset in all 5 profiles.
5. **Statusline conflict closed.** A2's open caveat is closed with M's binary and docs finding, and `refreshInterval` is now part of the recommendation, not an option.
6. **Owner question 3 answered as "not yet measurable", and the inference is labelled.** The knob table separates the measured share governed from the inferred effect. The effort figure is now described as output tokens on 15 claims, not wall time, and A1's effort table as not causal. The three trials are framed as K's measurement plan.
7. **Re-entry cost quantified.** 632 re-entries, 20.16 h, p50 4.7 s, p90 25.7 s, about 4.8% of T's 423.4 h. The useful share is marked not measured.
8. **Omitted lane results.** These are now in the verdict or section 2: the background-task ETA (50-56% at 1-5 min, n = 958 / 725 of 1,039), P3 (+8 points at 15 min, n = 367), A1's robustness views and heavy tail, S2's 58.5% / 71.7% (n = 599), prior art, and H's own 0.4-0.5%. One critic figure was wrong. It said `eta.py` runs at a 97 ms median, but `timing.txt` gives 81 ms as the median over files and 97 ms as the largest file's median. The report keeps 81 / 97 / 182 ms and adds the 150 ms target (1 of 40 files over it) and the prototype's scratch-only, undeployed state.
9. **Model-text comparison made two-sided.** "Beats the model's text" was removed from the verdict. Section 2 now shows 47% vs 28% (n = 32, no CI) beside the 46% vs 44% on the next background task (n = 103), under A2's conclusion that text "adds little beyond the base rate".
10. **A1's 325 vs 324 Workflow episodes.** It is noted under Lane disagreements; no conclusion depends on it.

## 2026-11-20 follow-up: what would narrow it

After #259 shipped, the owner reported the printed range too wide to act on
("我都不知道到底还要再跑多久"). The 2026-11-20 re-test used one split: fit on items
that started before 2026-11-12T00:00Z, test on 2026-11-12..20. The population
was 971 fit and 221 test human-started tasks, and 2,333 fit and 1,106 test
background jobs. Each cell below reads within-2x of the p50, then band width
(p75/p25), at 1 / 5 / 15 / 30 min elapsed. The scripts are scratch-only, like
the rest of this note's.

**How wide the shipped band is.** Tasks are 28.5x, 11.6x, 8.1x and 7.8x wide.
The width is the same whether a turn is running or the session is waiting on
background work. Single jobs, pooled by kind, are 7.4x, 8.4x, 7.1x and 7.8x.

**A job's identity does not narrow it.** The identity tried was the normalised
command, the subagent type or the Workflow name. At launch, 66% of test jobs
had 3 or more earlier runs of the same identity. Signature-with-fallback scored
within 2x on 37 / 53 / 59 / 31% of jobs, with bands 6.2x, 5.7x, 6.7x and 8.3x
wide. Kind alone scored 38 / 54 / 56 / 40%. For Bash, a control that shuffled
signatures among jobs scored 36 / 47 / 49 / 39%, so the signature carries only
a few points. The commonest "jobs" are poll loops (`until … sleep`, 569 runs,
p25-p75 4.5-29 min), whose length is whatever they wait for.

**Neither does adding the job and a tail while waiting.** Task remaining at an
idle-waiting moment can be split into the in-flight job plus the time after
it. That predictor scored 30.4% within 2x, against 29.6% for elapsed only, on
the same 1,653 per-minute moments from 73 test tasks. The paired difference
is +0.8 points (95% CI -8.9..+11.0).
- **The tail is the obstacle.** Knowing the job exactly reaches only 49%;
  knowing the tail exactly reaches 68%.
- **Why the tail cannot be predicted.** After a wait, the agent launches
  another round 54% of the time in the fit half and 67% in the test week.
  Without one, the rest of the task takes p50 59 s. With one, it takes p50
  67 min.
- **What else was tried.** The best predictor of another round was whether
  earlier waits in the task were followed by one: 61% vs 51% in the fit half,
  75% vs 59% in the test week. Job kind, round count, elapsed time, the number
  of jobs in flight and the project's rate did no better.
- **Control.** An exact job plus an exact tail reproduces the true remaining
  time on all 106 checked moments.

**What is tight.**
- **Monitors.** A Monitor cannot outlive its declared timeout, and 74% of 90
  test Monitors ran to at least 90% of it.
- **`sleep N`.** A bare `sleep N` job is exact, but only 73 of the 1,106 test
  jobs were one.
- **Workflows.** A Workflow's journal always shows its agents started and
  finished, which is a fact rather than an estimate.

**What changed (branch `feat/statusline-compact`).**
- The line prints the band only when p75 is at most 4x p25. On this history it
  never is, and `--json` still carries the band.
- A Monitor prints `≤<time> left` from its timeout.
- The line states what the session is doing (`run`, `wait`, `idle`) instead of
  `task`.
- The line fits `COLUMNS`. On a 29-column tmux split the old line showed
  `faceswap-platform-100 gi…` and never the task.

**Not built.** `sleep N` countdowns and Workflow agents-done counts are both
facts. The second needs the run's journal path from the launch result.

