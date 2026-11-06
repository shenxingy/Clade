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
- [Queued: model tier for implement stages](#queued-model-tier-for-implement-stages)

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
  stage table keeps the default for them on purpose. A protocol for implement
  stages, which also varies the model, is queued below and has not been run.
- n is small. The scorecard's per-phase rows (model and effort per agent) can
  now check the table against real runs.

## Next

The step this section used to name is done: `wf-reader` got its enforced
read-only Bash guard and was adopted on 2026-10-24 (see "Not done" above). The
open next step is the queued model-tier A/B below.

## Queued: model tier for implement stages

**Status (2026-11-06): not run. It waits on the owner's quota decision.** The
full design is 72 implement agents. At list price that is an estimated
$207–420, paid from the subscription quota rather than in dollars. That is a
third to two-thirds of one average day of Workflow spend on the profile the
ledger covers. The minimum design costs half as much, and a 3-agent pilot
($9–18) comes first either way. No A/B agent has run: the tasks, the grader
and the leak check below were all checked without a model call, and
`orchestrator/tests/test_model_tier_ab_harness.py` drives all three scripts on
a synthetic repository and synthetic transcripts. The harness
lives in [`model-tier-ab/`](model-tier-ab/).

### Why

- Jain, *Are Harnesses Worth the Cost?* (martinfowler.com, 2026-10-13): the
  cheaper model went from 3/10 to 10/10 with a harness, at 33% less than the
  stronger model without one. That is 10 runs per arm on one greenfield Java
  service, and harness authoring cost is not counted.
- Here, almost nothing varies the model. One profile's Workflow ledger
  (`workflow-scorecard/runs.jsonl`, 343 runs, 2026-09-22 → 10-24) holds 239,334
  API calls: 98.2% on Opus 5.5 and 99.7% on the Opus family. No implement stage
  has been measured at another model or another effort.
- `bounded-implementer` pins `model: sonnet` and `effort: medium`, and no
  measurement backs the pin.
- So the question is quality and reliability, not cost. The 2026-10-22 audit
  already judged model switching a small cost lever (TODO.md, the "Every
  `agent()` without `effort` runs at xhigh" item): Sonnet 5 and Opus 5.5 charge
  the same for cache reads, and cache reads are 54% of an implement agent's
  list price (see the cost estimate). Haiku is not an arm, because its 200k
  window cannot hold 59% of agents (same item).

### Tasks: eight replayed fixes with known answers

Each task is a merged `fix` commit of this repository that repairs files its
parent already has. The agent gets the parent tree plus the tests the fix added
or changed. It must make them pass by editing the files the fix changed, and
the fix itself is the known answer.

| id | fix | date | the agent owns | verifier |
|---|---|---|---|---|
| archive | `4d480c6` | 09-12 | `configs/scripts/archive-progress.py` | pytest `test_archive_progress.py` |
| scanhealth | `71379b4` | 09-08 | `configs/scripts/scan-health.sh` | `tests/test-scan-health.sh` |
| rmflags | `af1c4b2` | 09-07 | `configs/hooks/pre-tool-guardian.sh` and its Codex twin | `tests/test-pre-tool-guardian.sh` |
| redirect | `0b8e29a` | 09-07 | `configs/hooks/revert-detector.sh` | `tests/test-correction-pairing.sh` |
| loopmodel | `0075a5d` | 09-02 | `configs/scripts/loop-runner.sh`, `loop_verify.sh` | `tests/test-loop-args.sh` |
| droprules | `b0665f4` | 09-08 | `configs/hooks/session-context.sh` | `tests/test-skill-routing.sh` |
| domain | `ff7ea66` | 09-08 | `configs/hooks/correction-detector.sh`, `lib/domain-detect.sh` | `tests/test-correction-pairing.sh` |
| postedit | `c8fe850` | 09-08 | `configs/hooks/post-edit-check.sh` | `tests/test-hooks.sh` (the whole suite) |

One task is pytest and seven are shell suites.

- **Candidates.** 23 `fix` commits on main since 2026-09-01 change one or two
  hook or script files and one or two test files, and nothing else but docs,
  TODO.md, PROGRESS.md and plugin or package copies. Twelve were tried in an
  order chosen by hand for spread across files and languages, before any model
  saw them. Difficulty played no part.
- **Known-answer check** (`prep.sh`, 2026-11-06). A task is kept only if its
  verifier is red at the parent and green at the fix, with an empty `HOME`.
  11 of 12 passed. `b0234e1` (post-edit mypy) stayed red at the fix (exit 14,
  cause not investigated) and was dropped. The table first held the first
  eight tasks kept, at most one per owned file; `ff7ea66`, `c8fe850` and
  `c90dc31` were reserves.
- **Replaced on review: two tasks that were not fixes.** `bb50fbd` (scrub) and
  `e23e67f` (codexupd) each created the script the agent would own, so their
  parent had no such file. That task is writing a new file to a test, not
  repairing a defect, and the table claims only the second kind. Both were
  dropped. `ff7ea66` and `c8fe850` took their places: they are the reserves
  that own a file no other task owns (`c90dc31` shares `archive-progress.py`
  with `4d480c6`), and both repair files their parent has. `prep.sh` now drops
  any task whose owned file is new at the parent, so a swapped-in task cannot
  bring the other kind back; on the two old tasks it prints
  `DROP scrub: owned file new at the parent` and the same for codexupd. The
  composition changed with them: the two that left were pytest tasks, so one
  pytest task remains. Built again with only the owned files, all 8 tasks of
  the new table were kept (red at the parent, green with the owned files), in
  306 s at a load average of 106–126 on 32 cores. `AB_TASKS_FILE` swaps a task
  in without editing `prep.sh`.
- **The known answer is the base plus the owned files only**, which is the
  exact tree `grade.sh` builds. A fix whose test also needs one of its doc
  changes would fail every arm, so `prep.sh` drops it instead. An earlier
  version applied only the `configs/` half of each fix, and `af1c4b2`'s known
  answer stayed red, because that fix also changed the Codex guardian; the
  Codex guardian is an owned file, so it is applied.
- **The task statement** is the commit subject without its type prefix or PR
  number, for example "rm flags come from options, never from a filename". The
  failing test output carries the rest.
- **Leakage.**
  - Each cell is a fresh git repository with one commit, so no history holds
    the fix.
  - Nothing under `AB` holds a known answer. `prep.sh` builds and runs it in a
    temporary directory outside `AB`, deletes it, and then fails if any task
    directory holds anything but `base`, the cells and four small text files.
    It also refuses an `AB` that is not empty, or that sits inside a work tree.
  - Other cells are still in reach, and they matter: a later task's base holds
    an earlier task's fix as ordinary history (`domain`'s base has
    `redirect`'s fixed hook and its tests), and a sibling arm's cell may hold
    its work in progress. So the only place an agent may read is its own cell.
  - Without the PR number, the statement gives nothing to look up.
  - The fixes date from 2026-09-02 to 09-12, after Opus 5.5's stated training
    cutoff (June 2026). Before launch, read Sonnet 5's cutoff from the
    `claude-api` skill's model table and drop any task older than it.
  - The host's own checkout still holds every fix. A Workflow agent has no
    working-directory option, and every Bash call it makes starts in the lead
    session's directory. So the lead runs from an empty directory outside any
    repository (see "How to run it"), the brief tells each agent to begin every
    command with `cd <its cell>`, and the host checkout's `git status` is
    compared before and after the run.
  - `leaks.py` reads each agent's transcript and maps its label
    `tier:<task>:<arm>:<rep>` to its one cell. It reports an absolute path
    outside that cell (a sibling cell, another task, another checkout), the
    filesystem root as a bare `/` (`find / -name x`, `grep -r x /`, `cd /`),
    `~`, `$HOME`, a `..` component, a Bash command that does not begin with
    `cd <own cell>`, a Read, Edit, Write, Grep or Glob whose path is missing,
    relative or outside the cell, any web, MCP or agent-spawning tool, and any
    transcript line it cannot parse. The only paths it allows outside the cell
    are the exact `PY` path from `args.json` and system directories. It is a
    list for hand review, not proof: it sees what a call asked for, not what a
    command did. A cell whose agent reached another cell, another checkout or
    the web is void.

### Arms and size

| arm | model | effort | why it is here |
|---|---|---|---|
| A | Opus 5.5 | xhigh | what every implement stage runs today |
| B | Sonnet 5 | medium | what `bounded-implementer` pins |
| C | Opus 5.5 | medium | B against C is the model at equal effort; C against A is effort for implement stages, which the A/B above did not measure |

- Every arm uses the default Workflow agent and, for a given task, the same
  brief ([`workflow.js`](model-tier-ab/workflow.js)); across arms only the
  cell path differs.
  `bounded-implementer`'s own system prompt is not used, because it would make
  the arms differ in more than model and effort.
- Every arm names its model. The reader A/B above silently inherited Sonnet 5
  from a headless session's `--model`. The pilot must show the scorecard's
  per-agent `model` and `effort` matching each arm before the full run starts.
- **Full:** 8 tasks × 3 arms × 3 repetitions = 72 cells, 24 per arm.
  **Minimum:** the first 6 tasks × 3 arms × 2 = 36 cells, 12 per arm.
  **Pilot:** `scanhealth` × 3 arms × 1 = 3 cells.
- **What it can detect.** With 24 cells per arm, a two-sided Fisher exact test
  reaches p < 0.05 only at a gap of 5 to 8 cells, wider the less often A
  passes: 24/24 against 19/24, 22/24 against 15/24, 20/24 against 12/24. At 12
  per arm it takes 12/12 against 7/12. Repetitions of one
  task are correlated, so the real threshold is higher. The design can see a
  gap the size of Jain's harness effect (70 points). It cannot see a difference
  of one or two tasks, and finding no gap would not show the arms are equal.
  The decision rules below use exactly these thresholds.

### Grading

`grade.sh` is deterministic and makes no model call. It never runs the
verifier in the agent's cell, and it never changes the cell. For each cell:

1. It lists what the agent changed against the base commit: edited, deleted and
   new files, caches left out. It reads them through a throwaway index, so even
   git's index refresh does not touch the cell.
2. `out_of_scope` is every changed path outside the owned files.
   `edited_verifier` is 1 if one of those is a test the fix changed, or
   anything else the verifier could load: a path under a `tests/` or `test/`
   directory, a `conftest.py`, or a `pytest.ini`, `tox.ini`, `setup.cfg` or
   `pyproject.toml`.
3. It copies the task's pristine base, copies in the owned files exactly as the
   cell has them (a deleted owned file stays deleted), and runs the verifier
   there with a fresh empty `HOME` and stdin closed. Nothing else the agent
   changed reaches the verifier: not a test, not a `conftest.py`, not a helper
   or config. It first checks that the base still matches its commit, and
   stops if it does not.
4. The verdict is `pass` (green, `edited_verifier` 0), `pass-but-edited-verifier`,
   `fail`, or `timeout`. A timeout is regraded, never counted as a fail.
   Because the cell is never changed, a regrade sees the same evidence.

The agent's own verifier run uses the same setup as far as a brief can
arrange it: the brief exports `HOME=<cell>/.ab-home`, an empty directory that
`prep.sh` creates and excludes from git.

Checked on hand-made cells (2026-11-06), where a cell stands in for an agent:

| cell | what was done to it | verdict | out of scope |
|---|---|---|---|
| scanhealth A | the known fix, plus one stray `README.md` edit | `pass` | `README.md` |
| scanhealth B | no fix; the test edited to `exit 0`, which passes in place | `fail`, edited 1 | the test |
| scanhealth C | the known fix and the same test edit | `pass-but-edited-verifier` | the test |
| scrub A | the known fix | `pass` | |
| scrub B | no fix; the test file deleted | `fail`, edited 1 | the test |
| scrub C | no fix; a hook that skips every test appended to `orchestrator/tests/conftest.py`, which passes in place | `fail`, edited 1 | `conftest.py` |
| rmflags A | the known fix to both owned files | `pass` | |
| rmflags B | the known fix to the `configs/` file only | `fail` | |
| rmflags C | untouched | `fail` | |

`scrub` was still in the task table when these cells were graded; it left on
review (see "Tasks"), but its cells still show the grader on a real tree.
Grading twice printed the same rows, and every cell was byte-identical before
and after (a hash of each file, `.git` included). The first version of this
grader restored only the fix's test files, in place, and graded `scrub C`
`pass` with `edited_verifier` 0.

The same kinds of case run on a synthetic repository in
`test_model_tier_ab_harness.py`, with the same two checks on the cells.

A first try with a 150-second limit timed out a known-good `rmflags` cell at a
load average of about 220 on 32 cores. That is why `timeout` is its own verdict
and the default limit is now 600 seconds. Grade on a host whose load is below
its core count.

### Analysis, decided before the run

- **Primary:** per arm, the number of `pass` cells among cells that are not
  void. A cell is void when its agent returned null, ran the wrong model, or
  read outside its own cell (another cell, another checkout) or used the web,
  as `leaks.py` and the hand review of its hits decide. `pass-but-edited-verifier` is not a
  pass.
- **Read the per-task table first:** passes per arm for each task (0–3), then
  the totals. Report B against A, B against C and C against A, with the
  Fisher p as a rough guide only.
- **Secondary:** `edited_verifier` per arm (does the read-only instruction
  hold at each tier?), out-of-scope edits, list-price cost per pass, calls and
  wall time. Cost and calls come from `workflow-scorecard.py --session <lead
  session> --json`, whose `agent_rows` carry each agent's label, model, effort
  and cost.
- **Decision rules.** The threshold for "worse than A" is the largest pass
  count at which a two-sided Fisher exact test against A's actual count first
  reaches p < 0.05 (computed with `math.comb`). It depends on A's count, so it
  is read from this table after the run:

  | A passes, of 24 | 24 | 23 | 22 | 21 | 20 to 12 |
  |---|---|---|---|---|---|
  | worse than A at | 19 or fewer | 17 or fewer | 15 or fewer | 14 or fewer | A − 8 or fewer |

  | A passes, of 12 (minimum design) | 12 | 11 to 6 |
  |---|---|---|
  | worse than A at | 7 or fewer | A − 6 or fewer |

  The test treats the 24 cells as independent, and repetitions of one task are
  not, so this is a threshold fixed in advance, not a significance claim.
  - B worse than A: change `bounded-implementer`'s pin (to `opus`, or to
    inherit) and record why.
  - Anything else is a null result at this size, however small the gap. Keep
    the pin as it is and add nothing to the stage table. A design this size
    cannot show two arms are equal, so no result here widens the use of Sonnet.
  - C against A is read the same way. C worse than A confirms that implement
    stages keep the default effort; a null result does not add `medium` to the
    stage table for them.
  - Any `edited_verifier` cell, in any arm, is a finding against the read-only
    instruction and goes into the TODO item whatever the primary result.
  - Ceiling: if every arm passes at least 23 of 24 (11 of 12), these tasks are
    too easy to separate the tiers. Floor: if A passes fewer than 12 of 24 (6
    of 12), the tasks or the brief are the problem, not the tier. Either way,
    record it and stop. Harder, multi-file tasks would need a new protocol.

### Cost estimate

All figures are list-price equivalents, as `workflow-scorecard.py` computes
them. The subscription pays in quota.

- **The 2026-10-23 run** (ledger row `wf_d7236882-33f`): 48 single-claim verify
  agents, 141 API calls, $19.72, about $0.41 per agent. Implement agents cost
  10 to 20 times that, so this run supplies the effort ratios, not the anchor.
- **Anchors**, from `workflow-scorecard.py --project Clade --since 14 --json`,
  read 2026-11-06. All are Opus 5.5 at xhigh, in 6 runs from 2026-10-23 to
  11-05:
  - 16 agents in `Implement` phases: median 94.5 calls, median $8.71, mean
    $8.13, range $1.25–13.91. Of their $130.08, cache reads were 54%, output
    28% and cache writes 19% (rounded).
  - 17 agents in `Fix` phases: median $4.00. A single replayed defect with its
    failing test in hand is closer to these.
- **Scaling per arm.** Medium's ratios to xhigh come from the table above:
  output ×0.52, cache reads ×0.67, cache writes ×0.80. Arm B then takes Sonnet
  5's rates: half of Opus 5.5's for output and cache writes, the same for cache
  reads. These ratios were measured on verify agents only. The A/B measures
  them for implement agents.

| arm | per cell, from the `Fix` anchor to the `Implement` mean |
|---|---|
| A | $4.00 – $8.13 |
| C | $2.60 – $5.28 |
| B | $2.02 – $4.10 |

- **Totals:** pilot (3 cells) $9–18; minimum (36 cells) $103–210; full (72
  cells) $207–420.
- **For scale:** the same ledger records $22,070 over 343 runs in 33 days, or
  $669 a day. The full design is 0.31–0.63 of one average day.
- Even at equal call counts, B saves only 22% against C, because cache reads
  cost the same on both models. If Sonnet 5 reads more, the saving shrinks.

### How to run it

The shell steps run from the repository root, on Linux with GNU coreutils
(`grade.sh` and `prep.sh` need `timeout`). The lead session that launches the
Workflow does not (step 4). Nothing before step 4 calls a model.

1. Set the variables. `REPO=$PWD`. Export `PY` as the path to a Python that has
   pytest (the orchestrator's venv has one). `PILOT` and `AB` are two empty
   directories outside any repository, for example `PILOT=$(mktemp -d)` and
   `AB=$(mktemp -d)`.
2. Build the cells and record the host checkout:

   ```bash
   bash docs/research/model-tier-ab/prep.sh "$REPO" "$PILOT" 1 scanhealth   # 3 cells
   bash docs/research/model-tier-ab/prep.sh "$REPO" "$AB" 3                 # 72 cells
   { git -C "$REPO" rev-parse HEAD; git -C "$REPO" status --porcelain; } > "$AB/repo-before.txt"
   ```

   For the minimum design, the second line is
   `prep.sh "$REPO" "$AB" 2 archive scanhealth rmflags redirect loopmodel droprules`.
   `prep.sh` prints `OK`, `DROP` or `TIMEOUT` per task and writes `args.json`.
   The first sweep's verifiers took 1–13 s per task on 2026-11-06, and
   several times that under heavy load; `postedit` runs the whole
   `tests/test-hooks.sh`. The 8-task build recorded under "Tasks" took 306 s
   at a load average of 106–126, each verifier running twice.
3. Check the quota. The global CLAUDE.md defers a run when the 7-day window is
   at 90% or more, or when the 5-hour window plus projected burn reaches 100%.
4. Pilot. Start the lead Claude Code session in a fresh empty directory that is
   outside any repository and outside `PILOT` and `AB`
   (`LEAD=$(mktemp -d); cd "$LEAD" && claude`). Every Bash call a Workflow agent
   makes starts in that directory, so a command that forgets its `cd` finds
   nothing to read or edit. Launch Workflow with `scriptPath` set to the
   absolute path of `docs/research/model-tier-ab/workflow.js` and `args` set to
   the contents of `$PILOT/args.json`, passed as a JSON value. Then, from the
   repository root:
   - `bash docs/research/model-tier-ab/grade.sh "$PILOT"`;
   - `python3 docs/research/model-tier-ab/leaks.py <run dir> "$PILOT"`, where
     the run dir is
     `<config dir>/projects/<slug of $LEAD>/<session>/subagents/workflows/<run id>`;
   - `{ git -C "$REPO" rev-parse HEAD; git -C "$REPO" status --porcelain; }`
     must print exactly what `$AB/repo-before.txt` holds;
   - the scorecard's `agent_rows`.

   Go on only if three agents returned, each recorded the model and effort of
   its arm, every cell got a verdict, the host checkout is unchanged, and every
   `leaks.py` hit has been read by hand and none is a read of another cell,
   another checkout or the web.
5. Full run. From the same lead directory, launch with `args` set to the
   contents of `$AB/args.json`.
6. Grade: `grade.sh "$AB" > results.tsv`. Regrade any `timeout` rows on a
   quieter host. Run `leaks.py`, the host checkout comparison and the
   scorecard again, and write the results under this section. Then close the
   TODO item.

**Not covered:** multi-file feature work, `bounded-implementer`'s own agent
type as an arm, Codex tiers, judge and synthesis stages, and the cost of
writing a harness.
