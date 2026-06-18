---
topic: Agent Fingerprint — Distinguishing AI-Agent Commits/PRs from Human Ones (2026)
date: 2026-06-18
status: needs_work
review_date: 2026-06-18
reconciled: 2026-06-18
summary: >
  Empirical studies fingerprint AI-agent commits/PRs at 97.2% F1 from message
  style alone. The dominant tells are multiline commit messages, long templated
  PR descriptions, and message-code inconsistency ("Phantom Changes" 45.4%).
  Agent PRs merge less (83.8% vs 91%) and their symbols churn out sooner
  (3 vs 34 days). Clade's worker already produces the GOOD traits — scoped
  diffs, single-line conventional commits, mechanical (not LLM-narrated) PR
  evidence, an oracle gate against phantom diffs, and it already MEASURES the
  fix-rate fingerprint dimension. Two genuine gaps: the commit type is
  hardcoded `feat:` for every change, and there is no test-INCLUSION signal
  (only test-execution).
sources:
  - https://arxiv.org/abs/2601.17406   # Fingerprinting AI Coding Agents on GitHub
  - https://arxiv.org/html/2509.14745v1 # On the Use of Agentic Coding (agentic vs human PRs)
  - https://arxiv.org/html/2601.04886   # Message-Code Inconsistency in agent PRs
  - https://arxiv.org/pdf/2601.03556    # Do Autonomous Agents Contribute Test Code?
integrated_items:
  - "Single-line conventional commit (avoids the #1 agent tell: multiline ratio 44.7% global importance) — orchestrator/worker.py:789 (commit_msg = f'feat: {task_first_line.lower()}')"
  - "Scoped diff discipline — orchestrator/worker.py:790 (changed_files[:20]) + file-ownership gate orchestrator/worker.py:718 (_check_file_ownership discards out-of-lane edits)"
  - "Anti-Phantom-Changes PR body: evidence is mechanical (test output + oracle verdict), not LLM-narrated claims — orchestrator/routes/tasks.py:147 (_build_pr_body)"
  - "Verify gate rejects empty/incomplete diffs before commit (VERIFIED_OK on diff-stat) — orchestrator/worker.py:756"
  - "Oracle spec-compliance gate requires file:line evidence per criterion, blocks scope-understated merges — orchestrator/worker_review.py:219 (_ORACLE_SPEC_PROMPT)"
  - "Pre-push test EXECUTION gate (undo commit on failure) — orchestrator/worker.py:818,836"
  - "Fix-rate fingerprint ALREADY measured (agent vs human) — configs/scripts/commit-archeology.sh:120 (detect_agent_segmentation)"
  - "Attribution trailers segment agent vs human commits — configs/scripts/committer.sh (X-Clade-Task / Co-Authored-By when CLADE_WORKER_TASK_ID set)"
  - "Conventional commit-type classification — DONE: config.py `_infer_commit_type` + worker.py (commit 2c034eb); uncorrupts the agent fix-rate metric that keys off /^fix/"
needs_work_items:
  - "Test-inclusion signal in PR body + commit-archeology dimension (🟢 DEFERRED — reporting infra; build as a focused, separately-tested follow-up)"
reference_items:
  - "Per-agent style signatures (Codex multiline 67.5%, Cursor bullets/hyperlinks, Copilot long descriptions) — N/A: these identify WHICH agent, not commit QUALITY; Clade wants to avoid the tells, not match a vendor profile."
  - "Symbol-churn / time-to-removal longitudinal tracking (3 vs 34 days) — N/A as enforcement: it is an after-the-fact quality outcome, already proxied by the oracle gate + pre-push tests that catch the low-quality diffs upstream."
---

[English] | [Back to README](../../README.md)

# Agent Fingerprint — AI-Agent vs Human Commit/PR Behavior (2026)

## Overview

A 2026 cluster of empirical papers asks: **can you tell an AI-agent's commit/PR
from a human's, and what are the tells?** The flagship study — *Fingerprinting
AI Coding Agents on GitHub* (arXiv 2601.17406) — trains a supervised classifier
on **33,580 PRs from five agents** (Codex, Devin, Copilot, Cursor, Claude Code)
using **41 features** and hits a **97.2% F1-score**. The headline result for our
purposes: **how an agent communicates a change is more distinctive than what it
changes.** Commit-message and PR-description style dominate; code-content
features (comment density, conditionals) rank lower.

This doc extracts the fingerprint traits, separates **good hygiene** from
**agent tells**, and checks Clade's worker output against each — applying
"different ≠ deficient" but with the lens **"does Clade's worker match
best-practice agent hygiene and avoid the bad tells?"**

## The Fingerprint Traits (with numbers)

### Message/PR style (the dominant signal)
- **Multiline commit ratio — 44.7% global feature importance** (the single
  biggest tell). Codex 67.5%, Devin 48.9%. Agents write paragraph-style commit
  bodies where humans write one line. (2601.17406)
- **Change concentration / Gini — 10.1%** (2nd biggest). Copilot concentrates
  changes (24.9%); Devin distributes across files (8.2%).
- **PR description length**: agents write **median 355 words vs humans' 56**
  (2509.14745). Cursor leans on bullets (17.2%) + hyperlinks (12.8%).

### Acceptance & durability (the quality signal)
- **Merge rate**: agentic PRs **83.8% vs human 91.0%** (p<0.05) (2509.14745).
- **Diff size**: agents add **median 48 lines vs humans' 24**; both touch ~2
  files median (2509.14745).
- **Symbol durability**: agent-introduced functions/classes are removed
  **sooner (median 3 vs 34 days)** and **more often (churn 7.33% vs 4.10%)**
  (2601.17406) — agents ship more disposable code.

### Message-code inconsistency (the trust killer)
- *Analyzing Message-Code Inconsistency* (2601.04886): the top defect is
  **Phantom Changes — 45.4%** (PR claims changes never implemented), then
  **Scope Understated 22.0%**, **Placeholder/Incomplete 18.8%**. High-
  inconsistency PRs had **51.7% lower acceptance (28.3% vs 80.0%)** and took
  **3.5× longer to merge**. Copilot's inconsistencies were 74% Phantom Changes.

### Test inclusion (studies DISAGREE — note this)
- 2509.14745: agent PRs include test edits **MORE** often (18.8% vs human 4.5%).
- 2601.03556 (*Do Autonomous Agents Contribute Test Code?*): agents include
  tests in a **small fraction**, **lower** than humans; PRs **with** tests merge
  more often in both groups.
- The disagreement is dataset-dependent (curated agent platforms vs open
  scrape). The robust takeaway for Clade: **test inclusion is a measured
  fingerprint dimension AND a merge-rate lever** — worth a signal regardless of
  which direction the population skews.

### Good hygiene vs agent tells (summary)
| Trait | Good hygiene | Agent tell to avoid |
|---|---|---|
| Commit message | concise, conventional, accurate type | multiline paragraph body (44.7%!) |
| PR description | structured, evidence-backed | 355-word templated wall; bullets+links boilerplate |
| Diff | scoped, ~2 files, focused | larger churn, disposable symbols |
| Description↔code | matches the diff exactly | Phantom Changes (45.4%) |
| Tests | added with the change | claimed-but-absent / none |

## Clade Worker Output vs the Fingerprint

### What Clade does RIGHT (avoids the tells)

1. **Single-line conventional commit — sidesteps the #1 tell.**
   `orchestrator/worker.py:789` →
   `commit_msg = f"feat: {task_first_line.lower()}"`. One line, no paragraph
   body. The multiline-ratio signal (44.7% importance) is exactly what flags
   Codex/Devin; Clade's worker commits read like a disciplined human's. Good.

2. **Scoped diffs, enforced.** `orchestrator/worker.py:790`
   (`changed_files[:20]`) caps the commit payload, and
   `orchestrator/worker.py:718` (`_check_file_ownership`) **discards** any edit
   outside the worker's assigned lane (`git checkout .` + `git clean -fd`,
   worker.py:723-740). This directly counters the "distributed change /
   large churn" tell — the worker physically cannot sprawl across the repo.

3. **PR body is mechanical, not narrated — structurally anti-Phantom-Changes.**
   `orchestrator/routes/tasks.py:147` (`_build_pr_body`) assembles the body from
   **data the worker already carries**: the task text, the oracle verdict
   (`oracle_result`/`oracle_reason`), and the **literal pre-push test output**
   (`test_evidence`, routes/tasks.py:163-165). Because the evidence is captured
   command output rather than an LLM's prose summary, it cannot "claim a change
   that was never implemented" — the 45.4% Phantom-Changes failure mode is
   designed out. (Contrast: agents that ask an LLM to *describe* the diff are
   exactly where phantom claims come from.)

4. **Empty/incomplete diffs blocked before commit.**
   `orchestrator/worker.py:756` runs a Haiku verify gate on the diff-stat that
   must emit `VERIFIED_OK`; `worker.py:714` returns early on zero changed files.
   No "PR that claims work but the diff is empty."

5. **Scope-understated merges blocked.** `orchestrator/worker_review.py:219`
   (`_ORACLE_SPEC_PROMPT`) requires **file:line evidence per acceptance
   criterion** before a `satisfied` verdict — the inverse of the 22.0%
   Scope-Understated defect.

6. **Pre-push test EXECUTION gate.** `orchestrator/worker.py:818` runs the
   project suite; on failure `worker.py:836-846` undoes the commit, skips push,
   and requeues with the failure as evidence. Agents that ship red diffs are a
   prime churn source; Clade gates that out.

7. **The fix-rate fingerprint is ALREADY measured.**
   `configs/scripts/commit-archeology.sh:120` (`detect_agent_segmentation`)
   segments commits by the attribution trailer and emits
   `agent fix-rate N% (af/a) vs human N% (hf/h)` — Clade already tracks one of
   the exact dimensions these papers fingerprint, surfaced at SessionStart via
   `configs/hooks/commit-archeology.sh`. Attribution comes from
   `configs/scripts/committer.sh` (X-Clade-Task / Co-Authored-By trailers added
   when `CLADE_WORKER_TASK_ID` is set).

### Where Clade has GENUINE gaps

**Gap 1 — Hardcoded `feat:` commit type (worker.py:789).**
Every worker commit ships as `feat:`, including bug fixes, refactors, and
test-only changes. This is two problems at once:
- **Accuracy bug**: a fix that lands as `feat:` corrupts conventional-commit
  history and any downstream tooling (changelog gen, the fix-rate detector
  itself — `commit-archeology.sh:126` keys `fix` off `$3 ~ /^fix/`, so genuine
  agent fixes are invisible to its own fix-rate metric).
- **Self-inflicted fingerprint**: a uniform-type prefix on 100% of agent
  commits is itself a trivially-classifiable tell, and it understates the
  agent's true fix-rate (the very signal Clade tracks).
- **Fix (small, reversible)**: pick the type from the task text or the verify
  step — e.g. classify the task first-line (or reuse the oracle's already-known
  task intent) into `fix`/`feat`/`refactor`/`test`/`docs` before building
  `commit_msg`. A keyword heuristic (`fix|bug|error → fix:`, `test → test:`,
  `refactor → refactor:`, else `feat:`) is a 5-line change with no destructive
  side effects. This *improves* the fix-rate metric's own accuracy.

**Gap 2 — No test-INCLUSION signal (only test-execution).**
Clade runs the suite (worker.py:818) but never records whether the **diff added
test files**. The fingerprint studies treat test inclusion as both a tell and a
merge-rate lever, yet the PR body (`_build_pr_body`) and the commit-archeology
segmentation are blind to it. The data is one `git diff --name-only` filter away
(`grep -E '(test_|_test|/tests?/|\.spec\.)'` over `changed_files`).
- **Fix (small)**: in `verify_and_commit`, derive `tests_added = any(path looks
  like a test for f in changed_files)`; surface it as a PR-body line
  ("Tests added: yes/no") and, optionally, as a new commit-archeology dimension
  (agent test-inclusion rate vs human) — mirroring the existing fix-rate split.
  This turns a passive blind spot into a second measured fingerprint dimension,
  consistent with the "Clade already measures one dimension" posture.

### What is correctly NOT a gap (different ≠ deficient)

- **Per-agent style signatures** (Codex multiline 67.5%, Cursor bullets+links,
  Copilot long descriptions) identify *which vendor* produced a PR. Clade should
  **not** chase a vendor profile — the goal is to avoid the bad tells, not to
  match a fingerprint. N/A.
- **Symbol-churn / time-to-removal** (3 vs 34 days) is an after-the-fact
  durability *outcome*, not an enforceable pre-commit signal. Clade already
  attacks the upstream cause (oracle gate + pre-push tests reject the
  low-quality diffs that later get reverted), so adding longitudinal churn
  tracking would be measurement-for-measurement's-sake at current scale. N/A as
  enforcement.
- **Long PR descriptions = a tell**: Clade's `_build_pr_body` IS structured and
  can run long, but its length is *evidence* (test output + oracle reason), not
  templated narration. The papers penalize *unfaithful* long descriptions
  (Phantom Changes), not faithful ones. Different mechanism, not deficient.

## Verdict

Clade's worker already produces **best-practice agent hygiene on the dimensions
that drive merge-rate and trust**: single-line conventional commits (dodging the
44.7% multiline tell), file-ownership-scoped diffs, an evidence-driven PR body
that structurally cannot Phantom-Change, a verify+oracle gate against empty and
scope-understated diffs, a pre-push test-execution gate, and — uniquely — it
**already measures** the agent-vs-human fix-rate fingerprint. Two cheap,
reversible gaps remain, both of which *improve Clade's own measurement
accuracy*: (1) stop hardcoding `feat:` so fixes are typed correctly and the
fix-rate metric stops undercounting, and (2) record test-INCLUSION (not just
test-execution) as a PR-body line and a second commit-archeology dimension.

**STATUS: reconciled — 2 genuine gaps, both small/reversible/non-destructive.**

## Sources
- Ghaleb et al., *Fingerprinting AI Coding Agents on GitHub*, arXiv 2601.17406 — https://arxiv.org/abs/2601.17406
- *On the Use of Agentic Coding: An Empirical Study of Pull Requests on GitHub*, arXiv 2509.14745 — https://arxiv.org/html/2509.14745v1
- *Analyzing Message-Code Inconsistency in AI Coding Agent-Authored Pull Requests*, arXiv 2601.04886 — https://arxiv.org/html/2601.04886
- *Do Autonomous Agents Contribute Test Code? A Study of Tests in Agentic Pull Requests*, arXiv 2601.03556 — https://arxiv.org/pdf/2601.03556
