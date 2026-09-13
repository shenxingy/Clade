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
  top-level measured claims ("100% recall / 7.1% false alarms", "~17%") are asserted in
  CLAUDE.md and derived from nothing, while the gate floor is 90%/15%.
  Artifact: https://artifacts.internal.scam.ai/code-standards-after-machineslop/
integrated_items: []
needs_work_items:
  - "Derive CLAUDE.md's measured claims or stop making them — '100% recall / 7.1% false alarms' (CLAUDE.md:199) and '~17%' (CLAUDE.md:67) are ungated while run_hack_eval's floor is 90%/15%; add a `derive` type to docs/facts.json shelling out to run_hack_eval.py --json"
  - "judge_diversity._ASSERT_RE cannot see shell tests: 6 of 863 assert-helper lines match (0.7%) because \\bassert\\b does not match assert_contains; a diff deleting 3 assertions from tests/test-loop.sh returns eroded:False WITH test_files:1, i.e. it claims it looked. Add assert_[a-z_]+ and run_test, plus 2 hack + 2 honest shell cases to evals/hack_cases/"
  - "Run red-phase-audit.py against the PR's commits in the pytest job (report-only, fail on a NEW fire) — it covers the 86% additive blind spot, is live (4 of 21 sampled commits fired), and CI currently runs only its --self-test"
  - "Add a type checker over annotations already written — orchestrator core is 97.4% parameter-annotated and 83.7% return-annotated with ZERO checkers in CI or requirements-dev.txt"
  - "Pre-push hook for the four drift gates (2.6s total; they are 33 of 72 failing CI steps in repo history = 46%, and .git/hooks/ is empty)"
  - "Measure our OWN erosion before gating it: complexity + docstring density per commit by author. The 2.2x agent-vs-human erosion figure is someone else's corpus."
  - "test_self_tests_can_fire.py's known_gap exemption list contains exactly the four scripts CI runs under the banner 'can the harness go red?' — the meta-gate exempts the gates it exists to police"
reference_items:
  - "WITHDRAWN: gating E701/E702 as a 'machineslop signature'. The 18 load-bearing violations are deliberate self-evident idioms (aligned threshold ladder claude-usage-watch.py:97-99, cursor-advance blog_render.py:145). Perceptual class, no measured correctness effect."
  - "DO NOT adopt `ruff format --check`: 312 of 344 files would reformat for the one axis measured as nearly free (24.5% token saving for <=4.2pp accuracy)."
  - "DO NOT add a complexity gate yet: arXiv:2605.20049 (660 trials, minimal pairs) found cleanliness bought NO correctness (0.913 clean vs 0.921 messy). The 2.2x erosion result measures a different thing over a longer horizon. Measure ours first."
  - "The `## Code Architecture (Claude Code-Optimized)` rules are at configs/CLAUDE.md:196 — the SHIPPED TEMPLATE — not in the project CLAUDE.md. Working in this repo they reach a session only via the global profile, i.e. by accident of whose machine it is."
  - "'4-6 modules per component' is in direct arithmetic tension with the 1500-line cap (which forces splits; orchestrator/ has 61 top-level modules). 'Shorter files = fewer string duplicates = reliable Edit' is obsolete — Edit carries replace_all."
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
| @tenobrus coined "machineslop" | **No evidence found.** "machine slop" predates Astra. His verified Astra post is about neuralese/CoT monitorability, publicly rebutted | asserted |
| Kilo corroborates compression | **Qualitatively only.** One engineer, one prototype, no numbers at all. Kilo calls it "convergent, unsurprising, arguably correct" | n=1 |
| OpenAI concedes Astra is harder to monitor | **Confirmed, stronger than reported** — but the card is not an alarm document; Astra improved on nearly every alignment axis | measured |

Practitioners contradict each other on the remedy (one *adds* AGENTS.md scaffolding, Kilo
says delete half). Net: one credible anecdote plus a mechanism.

## 2. The axis that actually carves the practices

Six adversarial passes rejected "human-bandwidth artifact vs real rule". The axis is:

- **CHECKABLE** (types, invariants, tests, contracts, DAG imports, pinned deps,
  idempotency) — gets **stronger** with no human reader. The human was the residual
  enforcer of everything not written down; what is not in a gate is not in the reward.
  Types: ~15% as a defect filter for a person, up to **+79pp** of task completion for an
  agent in a compiler loop.
- **RETRIEVAL** (naming, greppability, one-declaration-one-location, module boundaries,
  section markers) — survives on purely **machine** grounds. Stripping identifiers costs
  **11–28.6 points**; names are retrieval cues into memorised patterns, so a model may
  degrade *faster* than a human. Fixing file-level localisation recovers 50% of unresolved
  cases vs 19% for line-level.
- **PERCEPTUAL** (line length, punctuation, formatting) — the only genuine bandwidth class.
  arXiv:2605.20049, minimal pairs, 6 pairs / 33 tasks / **660 trials**, hidden-test graded:
  **0.913 clean vs 0.921 messy**. Cleanliness bought no correctness. Layout compression is
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
AGENTbench, at +20% cost** (arXiv:2602.11988). Human-written gained ~+4%, entirely from
non-obvious knowledge not recoverable from the code. The architecture-overview section —
the one everyone writes — is the measured-useless part.

Stale artifacts are worse than absent: misleading comments cost **23.2%** degradation and
trigger 2–3× token consumption (arXiv:2504.14119).

Prose compliance: an agent follows a trivial unambiguous instruction from its context file
**~64%** of the time, decaying ~5.6% in odds per function; file size, position and even
directly contradicting instructions showed **no detectable effect** (arXiv:2605.10039,
1,650 sessions).

From the GPT-6 Astra system card: *"Astra often frames the reward-hacking workaround as
normal code modularization."*

**Defensible version:** humans read artifacts the agent **cannot author** — test results,
behaviour diffs, gate outcomes, production signals. Caveat: there is **no published study**
of a human-facing generated artifact layer as a discipline. It is a bet, not a finding.

## 5. This repo, measured at 0c7bf91

| What | Measured | Reading |
|---|---|---|
| Files in the 1401–1500 band | **0** | Of 492 tracked source files: 433/40/9/8/**0**/2. An empty band under a ceiling is the signature of a rule that drives behaviour. |
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
1M-token context; a 2,461-line file is ~0.03% of the window. **Tie rules to properties
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
