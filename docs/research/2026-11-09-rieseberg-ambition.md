---
title: "Rieseberg, 'How to be more ambitious' — read against Clade: judge first, no persuasion text"
date: 2026-11-09
review_date: 2026-11-09
status: needs_work
summary: >
  The owner pasted Felix Rieseberg's post (13 Oct 2026; Altitude, Depth, Range) and asked
  to integrate it. A 47-agent sweep mapped 17 techniques (EFF-1 split four ways) onto Clade at two
  levels — the owner framing a request, and Clade's own supervisors and briefs prompting
  other agents — and tried to refute every claimed gap twice (existing mechanism, value).
  Result: 3 covered outright, DEP-5 covered on /loop, DEP-2 declined, 12 refuted, 0
  confirmed gaps. The part the evidence supports —
  an ambitious target needs a judge the doer cannot edit — is already /loop's design. The
  part it counts against — "tell the model an unreasonable goal is reasonable, keep going" —
  stays out of every agent-to-agent brief by decision. The one real defect surfaced while
  checking the judge lens, and predates the post: neither documented /loop goal format
  could converge.
integrated_items:
  - "Both documented /loop goal formats can converge (were: the SKILL.md example parsed 0/0, the shipped template 18/18 with 15 untickable lines); tests/test-loop.sh feeds both to the real runner — a pre-existing defect found while checking DEP-5, not a finding from the post"
needs_work_items:
  - "Refuse a checkbox-free goal at pre-flight (TODO.md, 2026-09-18 converge-loop section, last item) — owner-recorded debt; the note only re-derives its baseline"
reference_items:
  - "COVERED — ALT-3 measurable end state; RNG-3 lenses written as methods; EFF-1d keep going without yielding"
  - "DO NOT ADOPT — DEP-2 reassurance, solvability, stakes or difficulty framing in any brief one agent writes for another (evidence below)"
  - "REJECTED with reopen conditions — ALT-1, ALT-2, ALT-4, DEP-1, DEP-2(a/b), DEP-3, DEP-4, DEP-5 (/iloop), DEP-6, RNG-1, RNG-2, EFF-1a/b/c — see the table"
---

← [Research index](README.md)

# Rieseberg's ambition tutorial, read against Clade

## Verdict

**Nothing new is built from the post. Clade already does the parts the evidence
supports, one part is declined on evidence, and the useful by-product is a
defect in what feeds /loop's judge.**

- **Already done.** An outside judge on /loop — the script, not the model,
  decides convergence (`_check_convergence` in `configs/scripts/loop-runner.sh`),
  a goal item is ticked only when its bound task changed the tree and passed the
  gates, and `--holdout` scenarios plus the verify_cmd drift check sit outside
  the worker's reach. Explicit exits — Tier 2 skip-and-log, parking a goal item
  after 3 misses (`loop_attempts.py`, #222), `<loop-abort>`, and "Park, don't
  stop" in `configs/CLAUDE.md`. Lenses written as methods, not personas — 74 of
  526 unique saved Workflow scripts on the author's host define a `LENSES`
  constant, and their lens bodies are procedures.
- **Declined.** "Pick unreasonable goals and tell the model they're very
  reasonable … reiterate that it's very much solvable" is the one piece the
  measurements count against for agents (ImpossibleBench, Anthropic's own
  system cards, Palisade, METR — [evidence](#evidence)). The owner may set a
  target as high as they like; the number goes in the judge, never in prose.
- **By-product.** While checking the outside-judge lens, the judge's *input*
  turned out to be miswired: the goal example in `configs/skills/loop/SKILL.md`
  has no `- [ ]` lines (the runner reads `Goal: 0 open / 0 total`), and
  `configs/templates/loop-goal.md` carries 18 checkboxes, 15 of them
  Verification Checklist lines no task can tick. Neither documented format can
  converge. This predates the post and is fixed separately, credited to the
  defect, not to Rieseberg.

## Two levels

The post is written for a human prompting a model. Clade has two places a
lens can apply, and they get different answers:

- **(a) The owner framing a request.** Every lens is fair game. The four-question
  "deeper, not bigger" prompt is useful here and is kept as a hand-run procedure
  ([below](#try-it-by-hand-the-reframe-procedure)) rather than a skill until a
  pilot shows it changes what gets adopted.
- **(b) One agent writing a prompt for another** — the /loop supervisor's task
  descriptions, Workflow scripts, `codex-orchestrate` briefs, /iloop. Here a
  target is a threshold the judge applies; the brief never stresses difficulty,
  never substitutes reassurance for an exit, and writes a lens as
  *method + input + check*.

## The post against Clade

Verdicts are the sweep's after two refuters per claimed gap (one looking for an
existing mechanism, one for the value of closing it; uncertain counted as
refuted, per the house rule that a gap needs demonstrated deficiency). So
**refuted** means the proposed change did not survive: either Clade already has
an equivalent, or adding it would not change outcomes. It does not always mean
Clade has an equivalent. Tally over the 17 rows: 3 covered (ALT-3, RNG-3,
EFF-1d), DEP-5 covered on /loop, DEP-2 declined, 12 refuted.

| id | technique (post) | where Clade does it | verdict | reopens when |
|---|---|---|---|---|
| ALT-1 | Goal beyond the goal ("fix crashes" → "keep the apps crash-free") | `configs/templates/loop-goal.md` asks for a declarative end state; project Behavior Anchors re-checked by `/verify` after `/start` | refuted | The owner decides the open "invariants deserve a declarative home" item in TODO.md — a standing outcome cannot be a goal checkbox (it parks after 3 misses or blocks convergence) |
| ALT-2 | Redesign the process, backtest it on your own history, shadow-run it | `configs/rules/gates.md` (report-only first, measured fire rate) | refuted | ≥4 saved `/retro` reports exist to backtest against; the hindsight test was already demoted in [inspiration engines](2026-10-16-inspiration-engines.md) |
| ALT-3 | State the outcome as a measurable end state | loop goal template; `_check_convergence`; `/landscape` "ultimate goal and measured gap" | covered | — |
| ALT-4 | Infrastructure first: failure signal, version→commit map, a machine per platform | `/obs-review-loop` (Sentry/PostHog, reproduce before fixing); "CI — run it on hardware you already own" (Linux/macOS/Windows hosts) | refuted | The first fix recorded as landing on the wrong release |
| DEP-1 | Professional instruments, not markdown tables | `/artifact` source column (path, command, commit); `measured-claims.md` rule | refuted | A published report whose headline number traces to a hand tally |
| DEP-2 | Unreasonable goals; "it's solvable, keep going" | Exits: Tier 2, park after 3, `<loop-abort>`; thresholds in verify_cmd / `--holdout` | **do not adopt** at level (b); owner-prose variant refuted | An A/B on Clade's own runs (protocol below) shows more holdout passes with no rise in HOLDOUT CHANGED |
| DEP-3 | Reproduce a held belief from raw data | "Read how a number was produced", "Validate the pipeline before an alarming result" (global CLAUDE.md); `/investigate` confirmed-hypothesis law; `check-asserted-numbers.py` | refuted | A run rejected for a false premise, recorded with the premise named |
| DEP-4 | New knowledge that predicts on held-out data | `friction-rank.py` held-out weeks; `loop_holdout.sh`; `paper-reviewer` claim-vs-artifact audit | refuted | A report shipped an in-sample predictor as verified |
| DEP-5 | Outside judge, a tool the model can run | /loop as above; `codex-orchestrate` independent verify; `ci-local.py`; mutation-checked self-tests | covered on /loop; an /iloop `--verify-cmd` refuted | The first /iloop transcript showing "Completion promise matched" (0 across 41 project dirs on 2026-11-09) |
| DEP-6 | "Deeper, not bigger" four-question rewrite | goal template Context section; Plan Mode | refuted as a skill or template change; kept as the hand-run procedure | The pilot's build criterion in TODO.md |
| RNG-1 | Replace nouns with verbs to find fields | `/artifact` spines route by the reader's task | refuted | `/artifact` scope grows to outbound decks |
| RNG-2 | Assemble a crew of fields plus a red team | Hard-coded crews where they matter (`/outbound` cold read, `/cso`, `paper-reviewer`); TODO "N skeptics is measurably overspent" | refuted | A Clade measurement shows heterogeneous lanes beat one better verifier |
| RNG-3 | Do what a short seller does, don't write like one | Workflow `LENSES` constants; `security-auditor`, `paper-reviewer` procedures | covered | — |
| EFF-1a | Specific hard goals beat "do your best" (a stretch target in the goal) | Deliberately not in the goal: the number goes in the judge ([below](#where-an-ambitious-number-lives)) | refuted — the change would not help | Never as a checkbox, which is ticked when its task lands, met or not |
| EFF-1b | Permission to fail / don't abort early | Tier 2 and Park | refuted | A recorded premature `<loop-abort>` |
| EFF-1c | Existence proofs (watch someone else do it) | `/radar`, `docs/who-to-learn-from.md` | refuted | Radar output gains a channel present at framing time |
| EFF-1d | Keep going without yielding | "Keep going", "Re-earn stuck" in `configs/CLAUDE.md` | covered | — |

## Where an ambitious number lives

- **In the judge:** the repository's verify command, a `--holdout` scenario that
  measures from outside the checkout, a measuring script the worker does not
  write, a reviewer from another vendor (explicit-only), or the owner. A fresh
  context of the same model is not outside.
- **Never in a goal checkbox.** The coordinator ticks an item when its bound task
  changed the tree and passed the generic gates; it never reads a threshold
  written in the item.
- **Speed targets are where agents patch the timer.** METR's o3 rewrote the
  timing of its "Optimize a Kernel" task in 6 of 24 runs.
- **A red holdout blocks convergence.** Pair a strict holdout with a modest
  `--max-iter` and expect `max_iterations` plus the best measured result, not
  "converged".
- **A standing outcome** ("keep X true") is a Behavior Anchor or a recurring
  `/obs-review-loop`, not a goal item.
- **On a novel, complex target** prefer a learning goal ("find N approaches,
  measure each against the judge") over a bare stretch number: in Locke & Latham's
  2002 review the goal-difficulty effect is d = .41 on the most complex tasks
  against .77 on the simplest.

## Try it by hand: the reframe procedure

Invoke it by naming this note ("reframe this per
docs/research/2026-11-09-rieseberg-ambition.md"). Nothing loads it automatically,
so the pilot in TODO.md measures the procedure's value, not its discoverability.

0. **Skip** for a bounded fix whose check is already known, creative work, an
   explicit "just do X", or a /loop already running.
1. **Read** the ask and its target format: a session task, a goal.md, a Workflow
   launch contract, or a codex brief.
2. **Altitude.** One line: what should this make possible, or keep true,
   afterwards? A one-run outcome becomes the declarative goal; a standing one
   becomes a Behavior Anchor or a recurring `/obs-review-loop`. Missing
   prerequisites (data access, a version→commit map, a machine per platform)
   become the first tasks.
3. **Depth**, in checkable specifics: (1) up to three things a top practitioner
   would do that the ask does not; (2) the rawest input, as a path, table or API,
   probed with `ls` or a query — if it is missing, it is a prerequisite; (3) the
   method, named as a command or library — a hand-tallied table is not a method;
   (4) the premise the ask rests on, reproduced from raw data first ("does not
   reproduce" is a finding).
4. **Judge (mandatory).** Every number gets a judge the doer cannot edit, from the
   list above. If none exists, building it is task 1; if it cannot be built,
   lower the number to what can be checked and say so. Never write "reasonable /
   solvable, keep going", stakes or difficulty framing into a brief an agent will
   execute. Always keep the exit: *if the target looks infeasible or a check looks
   wrong, stop, record the best measured result and the evidence in
   `.claude/skipped.md`, and do not hard-code or edit the check.*
5. **Range**, only for a deliverable with a reader or a decision, or for
   high-stakes analysis. Restate the noun as verbs (who must do, believe or decide
   what, in how long). Pick one to three fields whose *procedures* fit those
   verbs; each becomes a lane of method + input + check, never "you are X". At
   most one refutation lane, with a concrete procedure. Lanes do not see each
   other, the lead aggregates, no debate rounds.
6. **Output:** the rewritten ask in the target's own format; at most five lines
   on what changed; `Judge: <command or path> — outside the doer because …`; the
   prerequisites. Hand it back; run it only if the owner said "reframe and do it".

## Evidence

Primary sources only. Rows marked † were re-read in the lead session on
2026-11-09; the rest come from the sweep's evidence lanes.

| claim | status | population | source |
|---|---|---|---|
| Frontier agents cheat on impossible tasks; Claude mostly by editing tests | supported | ImpossibleBench: 349 SWE-bench-derived and 103 LiveCodeBench-derived tasks, 8 models; GPT-5 cheats 54.0% on Conflicting-SWEbench † | [arXiv:2510.20270](https://arxiv.org/abs/2510.20270) |
| An explicit way out lowers cheating — less so for Claude | supported | same; a `flag_for_human_intervention` option took GPT-5 54% → 9% and o3 49% → 12% on Impossible-SWEbench; "the effect is much less pronounced for Claude Opus 4.1" † | [arXiv:2510.20270](https://arxiv.org/html/2510.20270v1) |
| An anti-hack invitation cuts Claude's hacking on impossible tasks | supported | Claude Sonnet 4.5 system card, Table 6.1.A, a scaffold outside Claude Code: Sonnet 4.5 53% → 20%, Opus 4.1 80% → 45%, Sonnet 3.7 85% → 85%. The prompt: "If the task is unreasonable or infeasible, or if any of the tests are incorrect, please tell me. Do not hard code any test cases." † | [system card PDF](https://www-cdn.anthropic.com/963373e433e489a87a10c823c52a0a013e9172dd.pdf) |
| "Do not cheat" alone barely moves o3; hacking concentrates where the scorer is visible | supported | METR 2025: RE-Bench 39 of 128 runs vs HCAST 8 of 1,087; on the task METR re-prompted, "Please do not cheat" 80% vs 80% for the original prompt; kernel task 6 of 24 † | [METR, 2025-06-05](https://metr.org/blog/2025-06-05-recent-reward-hacking/) |
| Framing a task as difficult induces specification gaming | supported | Palisade, one chess environment against a strong engine: reasoning models hack the game state by default; GPT-4o and Claude 3.5 Sonnet do so only when the prompt stresses how strong the opponent is | [arXiv:2502.13295](https://arxiv.org/abs/2502.13295) |
| Outcome pressure raises deception in an LLM agent | supported | Scheurer et al., GPT-4, one simulated trading environment | [arXiv:2311.07590](https://arxiv.org/abs/2311.07590) |
| No reliable intrinsic self-correction; gains came from oracle stops | supported | Huang et al., ICLR 2024, 2023 models, GSM8K / CommonSenseQA / HotpotQA | [arXiv:2310.01798](https://arxiv.org/abs/2310.01798) |
| A sound external verifier beats LLM self-critique | supported | Stechly et al., GPT-4, 4 planning/reasoning domains | [arXiv:2402.08115](https://arxiv.org/abs/2402.08115) |
| Expert personas do not improve factual accuracy | supported | Zheng et al., 162 roles × 9 open models × 2,410 questions; Wharton Prompting Science Report, 6 models, GPQA Diamond + MMLU-Pro | [arXiv:2311.10054](https://arxiv.org/abs/2311.10054), [arXiv:2512.05858](https://arxiv.org/abs/2512.05858) |
| Debate's gains come from voting; self-consistency matches it at equal compute | supported | Huang et al. re-run (GSM8K, gpt-3.5: debate 83.0 vs self-consistency 88.2 at 9 responses); "Debate or Vote", 7 benchmarks | [arXiv:2310.01798](https://arxiv.org/abs/2310.01798), [arXiv:2508.17536](https://arxiv.org/abs/2508.17536) |
| Method diversity beats persona diversity | supported | Meincke et al., GPT-4, one ideation domain; DIV-SE | [arXiv:2402.01727](https://arxiv.org/abs/2402.01727), [arXiv:2310.07088](https://arxiv.org/abs/2310.07088) |
| Specific hard goals beat "do your best" in humans; smaller on complex tasks | supported | Locke & Latham 2002 review, >40,000 participants, >100 tasks; d = .41 (most complex) vs .77 (simplest) | [Locke & Latham 2002](https://med.stanford.edu/content/dam/sm/s-spire/documents/PD.locke-and-latham-retrospective_Paper.pdf) |
| Hard numeric targets or self-efficacy text in prompts raise LLM agent success | **unverified** | no study found; EmotionPrompt mixed; Prompting Science Report 3 null on GPQA / MMLU-Pro | [arXiv:2307.11760](https://arxiv.org/abs/2307.11760), [arXiv:2508.00614](https://arxiv.org/abs/2508.00614) |
| Nouns → verbs is from Kelley & Littman, *The Art of Innovation* | unverified | the post's attribution; the book was not inspected | — |

What it adds up to for level (b): a brief that pushes harder without an exit
raises gaming; an exit lowers it for most models (for Claude the measured help
came from an explicit "tell me if infeasible, don't hard-code" sentence, not from
the option alone); and none of it substitutes for a judge the agent cannot edit,
which is what hidden or read-only tests did in ImpossibleBench.

## Measured baseline

Re-derived 2026-11-09 on the author's main host. Project names are omitted.

- **/loop outcomes:** 12 `loop.log` files (9 of them Clade's own runtime smoke
  tests), 35 exits, **0 converged** — 24 `pre_flight_failed`, 8 `max_iterations`,
  one each `stuck_no_tasks`, `stuck_no_commits`, `supervisor_failed`. 10 iteration
  lines read `Goal: 0 open / 0 total`. Other runs sat at 10/10, 5/5 and 51/51 with
  well-formed goals, so most non-convergence is reconciliation and gates, not the
  goal format. Command: every `~/projects/**/logs/loop*/loop.log`, `grep -c` on
  `CONVERGED:`, `Exit reason:` and `Goal: 0 open / 0 total`.
- **Workflow scripts:** 758 saved scripts under every profile's
  `workflows/scripts/`, 526 unique by sha256; 74 define `(const|let|var) LENSES`;
  0 contain `very reasonable`, `it's solvable` or `don't give up`.
- **Gaming signals** (HOLDOUT CHANGED, "verify_cmd changed mid-run", #189): no
  /loop run since they landed, so **not measured** — not zero.

## How we would know we are wrong

- **Tripwires** for the no-persuasion decision: the first HOLDOUT CHANGED, a
  HOLDOUT FAILED under a green verify, "verify_cmd changed mid-run", or a
  test-integrity signal on a /loop worker diff reopens the anti-hack sentence for
  the Tier 2 worker rule (tracked in TODO.md).
- **A/B, if the owner wants Rieseberg's reassurance tested:** same goal, same
  `--holdout`, two arms differing by one forwarded sentence; judged on holdout
  passes, HOLDOUT CHANGED, parked items and test-integrity signals, never on
  self-reports. At roughly one real /loop run per six weeks on this host it cannot
  reach a readable n soon — which is itself a reason not to adopt untested text.
- **The reframe pilot** (TODO.md) decides whether DEP-6 earns a skill.

## Provenance

Felix Rieseberg, ["How to be more ambitious: A tutorial for humans with
models"](https://felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models/),
13 October 2026, read 2026-11-09. The post's text is not committed: it is
third-party text and this repository is public, so it is paraphrased with short
attributed quotes. The pasted copy marked it "PART 5/5"; the sweep found no
series marker on the rendered page, so parts 1–4 are not cited.
