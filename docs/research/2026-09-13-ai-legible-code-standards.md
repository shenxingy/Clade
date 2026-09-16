---
title: Code Standards After Machineslop — what "good code" means when AI writes and maintains it
date: 2026-09-13
review_date: 2026-09-13
status: reference
summary: >
  Triggered by Ronacher's 35h/75k-line/$1200 unattended Astra run and the "machineslop"
  discourse. Verified every cited source against the primary document: most of the
  corroboration does not say what it is quoted as saying. 29-agent sweep including six
  adversarial passes, all of which REFUTED the framing we started with. The axis that
  carves code practice is not human-vs-machine but CHECKABLE / RETRIEVAL / PERCEPTUAL:
  checkable properties get stronger with no human reader, retrieval properties survive on
  purely machine grounds, and only perceptual ones (line length, punctuation, formatting)
  were ever bandwidth artifacts. A controlled minimal-pair study (660 trials) found
  cleanliness bought NO correctness, while stripping identifier names costs 11-28.6 points
  — so gate naming and retrieval, not formatting. Biggest local finding: this repo's own
  top-level measured claims ("100% recall / 7.1% false alarms", "~17%") were asserted in
  CLAUDE.md and derived from nothing, while the gate floor is 90%/15%. RE-VERIFIED
  2026-09-16 by an independent 48-agent pass (21 claim units, live re-measurement plus
  primary-source checks, each verdict adversarially attacked): the repository measurements
  held, the literature layer did not — eleven claims refuted and twenty-three verdicts
  overturned, corrected in place below and named. Three findings shipped: 4aa865d, b4da5cc,
  f17f382.
  Artifact: https://artifacts.internal.scam.ai/code-standards-after-machineslop/
integrated_items: []
needs_work_items:
  - "Run red-phase-audit.py against the PR's commits in the pytest job (report-only, fail on a NEW fire) — it covers the 86% additive blind spot, is live (4 of 21 sampled commits fired), and CI currently runs only its --self-test"
  - "Add a type checker over annotations already written — orchestrator core is 97.4% parameter-annotated and 83.7% return-annotated with ZERO checkers in CI or requirements-dev.txt"
  - "Pre-push hook for the four drift gates (2.6s total; they are 33 of 72 failing CI steps in repo history = 46%, and .git/hooks/ is empty)"
reference_items:
  - "WITHDRAWN: gating E701/E702 as a 'machineslop signature'. Of the 18 violations in configs/, 12 are deliberate self-evident idioms (aligned threshold ladder claude-usage-watch.py, cursor-advance blog_render.py); the other 6 are all in vignelli_system.py from one upstream-absorption commit 1ab573b, so 'deliberate' was never ours to claim for them. Perceptual class, no measured correctness effect — withdrawn on 12 examined cases and 6 inherited ones."
  - "DO NOT adopt `ruff format --check`: 312 of 344 files would reformat for the one axis measured as nearly free (24.5% token saving for <=4.2pp accuracy)."
  - "DO NOT add a complexity gate yet: arXiv:2605.20049 (660 trials, minimal pairs) found cleanliness bought NO correctness (0.913 clean vs 0.921 messy). The erosion result (arXiv:2603.24755 v2, 2.0x) measures a different thing over a longer horizon. Measure ours first."
  - "The `## Code Architecture (Claude Code-Optimized)` rules are at configs/CLAUDE.md:196 — the SHIPPED TEMPLATE — not in the project CLAUDE.md. Working in this repo they reach a session only via the global profile, i.e. by accident of whose machine it is."
  - "'4-6 modules per component' is in direct arithmetic tension with the 1500-line cap (which forces splits; orchestrator/ has 61 top-level modules) — DELETE that rule. 'Shorter files = fewer string duplicates = reliable Edit' — the RATIONALE is obsolete (Edit carries replace_all) but the RULE stands: duplicate non-trivial lines rise ~3.9x with file length, so rewrite the reason, do not delete the rule."
---

# Code Standards After Machineslop

Published artifact (company intranet):
<https://artifacts.internal.scam.ai/code-standards-after-machineslop/>

## 1. Source verification — the corroboration mostly does not hold

| Claim as circulated | Primary source | Grade |
|---|---|---|
| Ronacher: 35h, 75k lines, 79 commits, ~$1200, "absolutely nothing of value" | **Confirmed.** Both token figures are his and measure different things: ~4B ChatGPT-subscription, ~1B raw-API at ~$1200 | n=1 |
| arXiv:2605.31170 shows agents evolving private languages | **Out of domain.** Text-mining of Moltbook, a Reddit-like site for agents. No code, no repos. 518 of 232,000 posts (0.223%) of agents *discussing* conlangs | measured |
| METR attributed the telegraphic style to "the medium" | **METR attributed it to nothing.** "telegraphic"/"terse"/"shorthand" appear zero times in 3,901 lines. METR traced the `zz` prefix to a reverse-alphabetical sort in the reading tool | measured |
| @tenobrus coined "machineslop"; greenfield-only drift | **Contradicted by the primary.** Ronacher's run was a **CPython fork** — brownfield, very large — and he states "I have since encountered the same issues with regular programming with Astra, so it's not a result of just the factory", naming TypeScript and "code that actually gets committed". "machine slop" predates Astra, though a January 2026 survey cataloguing 81 slop compounds records zero uses of it, so it existed without being common | measured |
| Kilo corroborates compression | **Qualitatively only.** One engineer, one prototype, no numbers at all. Kilo calls it "convergent, unsurprising, arguably correct" | n=1 |
| OpenAI concedes Astra is harder to monitor | **Confirmed, stronger than reported** — but the card is not an alarm document; Astra improved on nearly every alignment axis | measured |

Practitioners contradict each other on the remedy (one *adds* AGENTS.md scaffolding, Kilo
says delete half). Net: one credible anecdote plus a mechanism.

### 1b. Ronacher cites none of the corroborations attributed to him

Every outbound link on his post, extracted: two Wikipedia articles (Neijuan, Agricultural
Involution), an OpenAI developer blog, one `openai/codex` permalink, `collusion.wiki`, and
two of his own earlier posts. **No arXiv paper, no METR report, no Kilo, no @tenobrus, no
Astra system card.** Those sources exist independently and some are strong, but the chain of
evidence was assembled by the commentary, not by the engineer whose run is its foundation.

And his actual claim is far narrower than "GPT-6 writes code humans cannot read". He locates
the leakage in code *one step removed* from normal source ("mostly in tests, but also
JavaScript or CSS embedded in HTML") and where nobody is watching ("when it goes all bananza
with subagents"). The acute loss is **following the change while it happens** — once the
model abandoned the edit tool for Python string splicing, "you're going to have to resort to
using the diff viewer of the final artifacts."

**That is an observability failure, not a style failure**, and observability has a
targetable surface.

## 2. The axis that actually carves the practices

Six adversarial passes rejected "human-bandwidth artifact vs real rule". The axis is:

- **CHECKABLE** (types, invariants, tests, contracts, DAG imports, pinned deps,
  idempotency) — gets **stronger** with no human reader. The human was the residual
  enforcer of everything not written down; what is not in a gate is not in the reward.
  Types: ~15% as a defect filter for a person. The **+79pp** figure often attached to
  them measures compilation success for C under compiler *tool* access and disclaims
  functional correctness — evidence for the feedback loop, not for the type system.
- **RETRIEVAL** (naming, greppability, one-declaration-one-location, module boundaries,
  section markers) — survives on purely **machine** grounds. Stripping identifiers costs
  **11–28.6 points**; names are retrieval cues into memorised patterns, so a model may
  degrade *faster* than a human. File-level localisation resolves 14 of 28 file-miss cases and line-level 33 of 175;
  against the 209 unresolved instances that is 6.7% vs 15.8%, so line-level recovers more
  than twice as many cases. (arXiv:2601.18044 §5.4. The 50%/19% conditional rates were
  quoted here as if they ranked the two, which inverts the paper's result.)
- **PERCEPTUAL** (line length, punctuation, formatting) — the only genuine bandwidth class.
  arXiv:2605.20049, minimal pairs, 6 pairs / 33 tasks / **660 trials**, hidden-test graded:
  **0.913 clean vs 0.921 messy**. Cleanliness bought no correctness. (COI worth noting and it strengthens the null: both authors are SonarSource and "cleanliness" is their own rule set. They DID find effects and led with them (7-8% fewer tokens, 34% fewer file revisitations, concluding maintainability principles "remain highly relevant"), which makes the correctness null the more striking: it is the one axis their incentives ran against. Do not quote its token savings per task: median −4.5%, sign flips on 11 of 27 tasks.) Layout compression is
  24.5% token saving for ≤4.2pp accuracy.

## 3. Why more gates is not the answer

**A gate is evidence only if it can be surprised.** A gate informs about defect D only when
P(pass|D) < P(pass|¬D). If artifact and gate derive from the same intent-model, an error
appears in both → P(pass|D)→1 for the class that matters most: "we built the wrong thing
correctly" (oracle problem, Barr et al., IEEE TSE 41(5) 2015).

**Gate value is proportional to provenance independence from the generator, not gate count.**

Measured here: **22 of 22 syntax-check gates are parse, lint, text or filesystem-consistency
checks.** Zero check types or behaviour. They caught drift review missed for 241 commits and
are blind by construction to wrong requirements, design errors, concurrency, security logic
and performance cliffs.

Recursive form: `test_self_tests_can_fire.py`'s `known_gap` contains exactly the four
scripts CI runs under the banner "can the harness go red?".

## 4. The premise test

Machine-written repository context files were measured: **−0.5% SWE-bench Lite, −2%
AGENTbench, at +20% cost** (arXiv:2602.11988). Human-written gained **2.4%, p = 0.21 — explicitly NOT statistically significant**
(v2 §4.2; the ~+4% that circulated, and that an earlier revision of this doc carried, is
v1's). The paper runs no decomposition by knowledge type: "useful for specifying
non-standard coding practices" is the authors' RECOMMENDATION, and their one
category-removal ablation found no category significantly affects accuracy. The architecture-overview section —
the one everyone writes — is the measured-useless part.

Stale artifacts are worse than absent: misleading comments cost **23.2%** degradation and
trigger 2–3× token consumption (arXiv:2504.14119).

Prose compliance: an agent follows a trivial unambiguous instruction from its context file
**~64%** of the time, decaying ~5.6% in odds per function; file size, position and even
directly contradicting instructions showed **no detectable effect** (arXiv:2605.10039,
1,650 sessions; the ~64% itself is the primary pool of 1,150 non-baseline runs /
11,637 functions, not a grand mean over all 16,050 observations, ~10% of which are
0%-by-construction baselines).

From the GPT-6 Astra system card: *"Astra often frames the reward-hacking workaround as
normal code modularization."*

**Defensible version:** humans read artifacts the agent **cannot author** — test results,
behaviour diffs, gate outcomes, production signals. Caveat: there is **no published study**
of a human-facing generated artifact layer as a discipline. It is a bet, not a finding.

## 5. This repo, measured at 0c7bf91

| What | Measured | Reading |
|---|---|---|
| Files in the 1401–1500 band | **0** | Of 492 tracked source files: 433/40/9/8/**0**/2. The empty band alone is weaker than it reads: 30 of the 492 are byte-identical generated copies and the adjacent bands hold 3 and 5 distinct files, so an empty band is ~1-in-20. The evidence that carries it is that **ten files record in their own headers being split by the cap** (loop_args/loop_bounds/loop_score/loop_verify.sh, worker_pool.py, task_schema.py, repo_map.py, and three test modules). |
| Param annotations, orchestrator core | **97.4%** | 87.9% in load-bearing `configs/`; 23.2% in tests. A repo-wide 42% figure averages in 2,076 test functions and is misleading. |
| Type checkers | **0** | None in CI or `requirements-dev.txt`. Types written, never read. |
| Property-based tests | **0** | vs ~1,248 example-based test functions. One property kills ~50× the mutants. |
| Shell assertions the detector sees | **0.7%** | 6 of 863. `\bassert\b` cannot match `assert_contains`. |
| Test-diff traffic covered | **14%** | 218 of 400 commits touch a test file; 30 fire. The instrument for the other 86% runs only its self-test. |
| Complexity / duplication gates | **0** | ruff selects `E9,F,B` only. |

Two of the seven architecture rules do not survive: **"4–6 modules per component"** is in
arithmetic tension with the 1500-line cap (which forces splits; `orchestrator/` has 61
top-level modules), and **"shorter files = fewer string duplicates = reliable Edit"** was
true of a 2025 harness — Edit uniqueness is a property of the selected string, and this
harness's Edit carries `replace_all`.

The 1500-line cap itself is sound and enforced (`test_conventions.py:83`), but its stated
rationale — "Read tool default = 2000 lines" — is a harness constant. This session runs a
1M-token context; a 2,461-line file is ~2.1-2.7% of the window (89,907 bytes at 3.3-4.2
bytes/token — an earlier revision said ~0.03%, wrong by two orders of magnitude, and it
was the sole support for what follows, which survives on the smaller margin). **Tie rules to properties
(revert size, blast radius), not harness constants.**

## 6. Corrections made during this research

- I told the owner the "4 billion tokens" figure in secondary coverage was wrong. **It is
  Ronacher's own**, describing ChatGPT-subscription usage; ~1B is the raw-API figure. Both
  are in the same post.
- I proposed an E701/E702 punctuation gate, then read the violations. **Withdrawn.**
- I published "42% annotation coverage" as a gap. **Misleading** — core is 97.4%; the gap
  is the absent checker, not absent annotations.
- I attributed the architecture rules to the project `CLAUDE.md`. **They are in
  `configs/CLAUDE.md:196`**, the shipped template.
- Two reviewers read arXiv:2603.24755 and reported erosion differently (2.2x/80% versus
  2.3x verbose / 2.0x eroded / 77%). **Discharged 2026-09-16: it is a version difference,
  not a reading difference.** v1 (48 repos, 93 checkpoints) says 2.2x verbose and erosion
  up in 80%; v2 (473 repos, 196 checkpoints) restates it as 2.3x / 2.0x / 77%. v2
  supersedes. Both reviewers were faithful to the version they read, and one fetch of
  /abs/<id>v1 settled it — the caveat should have been discharged rather than published.

## 7. Re-verification, 2026-09-16 — what this document got wrong

48 agents over 21 claim units: ten re-measured live on `aries`, eleven checked against the
primary document, every verdict then handed to a second agent whose only job was to
overturn it. Net 112 confirmed / 28 partial / 10 drifted / 11 refuted, 23 verdicts
overturned on the adversarial pass.

**The repository measurements held; the literature layer did not** — and it failed in the
direction this document exists to indict. Three of the four worst are the same defect:

- **+4% became 2.4%, p = 0.21.** arXiv:2602.11988 v2 states the human-written context-file
  gain is "neither statistically significant". The +4% is v1's, and it is also what the
  secondary coverage says — so this document inherited a number from the very
  summary layer it was written to criticise. On the published page it was the one green
  bar against two red ones.
- **"entirely from non-obvious knowledge" was never measured.** It is the authors'
  recommendation, quoted here as their finding. Their one category-removal ablation found
  no category significantly affects accuracy.
- **The erosion caveat was discharged by one URL.** "Two reviewers disagreed, re-read the
  source" is v1 versus v2 of the same paper. Publishing an unresolved caveat that
  `/abs/<id>v1` settles is the cheapest possible failure.
- **The published page carried the erosion figure with no identifier at all** — zero
  occurrences of `24755` in its HTML, while two other arXiv IDs appear on the same page.

Corrected in place above and on the page (rev 5). Two further items were withdrawn as
overstated rather than wrong: the 1401–1500 empty band (a ~1-in-20 coincidence on its own;
the file headers are the real evidence) and "all 18 E701/E702 violations are deliberate"
(six came from one upstream-absorption commit, `1ab573b`).

Not everything the first re-verification pass claimed survived either. It called the +4%
a fabrication; the adversarial pass found the figure in v1 and corrected the charge from
invention to staleness. It declared "one property kills ~50x the mutants" unverifiable
because no local experiment could bear on it, and the adversarial pass simply went to the
literature and found it: Ravi & Coblenz, OOPSLA 2025, doi 10.1145/3764068. **"I cannot
measure it here" is not "it cannot be verified"** — the same move this document criticises
in others, one level down.

### What shipped as a result

| Finding | Fix | Commit |
|---|---|---|
| `_ASSERT_RE` matched 0 of 825 real shell assertions and returned "looked and found nothing" | regex + 4 shell corpus cases; corpus 30 → 34, 100% recall / 6.2% false alarms | `4aa865d` |
| `100% recall / 7.1%` asserted, derived by nothing, while one undetected hack still passes the 90% floor | derived by a test that reads the sentence and re-scores the corpus; proven fireable by mutation | `b4da5cc` |
| `~17%` and `115 of the last 133` unreproducible; the latter at **6** sites including an oracle prompt | deleted, with the method named instead of a number | `b4da5cc` |
| `known_gap` exempted exactly the gates CI runs under "can the harness go red?" | emptied; 13 mutations registered, each proven to turn its self-test red | `f17f382` |
| `check-skill-contracts.py` stayed green under the exact historical bug it was written for | fixture given the bare word to match on | `f17f382` |
| Two guards in `red-phase-audit.py` — the ones that stop a failed run reading as "nothing fired" — unreachable from its own self-test | extracted `classify_pytest_output()`; self-test drives them directly | `f17f382` |

Still open and recorded rather than fixed: changing an **existing** assertion message fires
`expectations_changed` in every language, because `_skeleton` blanks every literal alike and
this repo's shell helpers take the message as an optional positional argument — so
`assert_contains a b` and `assert_contains a b msg` are indistinguishable by arity.

## 8. Our own erosion, measured 2026-09-16

The open question this document called "the one measurement that would convert most of
this page from inherited evidence into local fact" is answered, by
`configs/scripts/erosion-trend.py`. Sampled over each layer's own history, comparing
against the earliest sample holding at least half the final file count — a first-to-last
delta measures the project being born, not its code eroding:

| Layer | window | mean complexity | docstring % | mean fn length | comment ratio |
|---|---|---|---|---|---|
| `configs/` (load-bearing) | 2026-06-09 → 2026-09-16, 100 → 139 files | 7.409 → 7.372 (**−0.5%**) | 76.5 → 59.3 (**−22.5%**) | 8.20 → 7.59 (−7.4%) | 0.056 → 0.065 (+16.1%) |
| `orchestrator/` (dormant) | 2026-07-28 → 2026-09-16, 159 → 198 files | 4.418 → 4.178 (**−5.4%**) | 23.4 → 25.0 (+6.8%) | 4.93 → 4.78 (−3.0%) | 0.052 → 0.064 (+23.1%) |

**We do not reproduce the complexity erosion the literature describes.** Mean complexity is
flat to falling in both layers, function length is falling, and comment density is rising.
What IS eroding is documentation: `configs/` lost **17 points** of docstring coverage
(76.5% → 59.3%) while growing by 39 files.

Three things this does not license. It cannot separate agent-written from human-written
code — agency is recorded nowhere in this tree, so this is a trend, not a contrast, and it
is not a replication of arXiv:2603.24755. The confounds are real and unremoved: the layer
grew ~40% over each window, and new files land with their own baseline. And a flat mean
hides its tail — `configs/` has carried a single 127-complexity function throughout.

**Consequence for the complexity gate:** the case for one just got weaker, not stronger.
The controlled study says cleanliness bought no correctness; our own complexity is not
rising; so a complexity gate would spend rules on a class that is measured inert HERE as
well as in the literature. The docstring slide is the finding worth acting on, and it is a
retrieval-class property, not a perceptual one.
