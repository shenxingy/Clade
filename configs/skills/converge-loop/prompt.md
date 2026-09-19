# Converge Loop

You drive a product to convergence: repeated rounds of gap discovery,
in-round fixes, re-audit, until consecutive rounds find nothing new.

## Inputs (slots — fill from the invocation, else infer, else default)

| Slot | Default | How to resolve |
|---|---|---|
| Target | the repo you are standing in | cwd's git root; ask only if genuinely ambiguous |
| Dimensions | UIUX · 登录 · 服务 · 收钱 · 软件系统 | override when the product shape differs (e.g. a static hub has no 收钱; a library swaps 登录 for API surface) |
| Stop rule | 2 consecutive rounds with zero new P1/P2; hard cap 8 rounds | state the rule in the report |
| Deploy | fix batches land per the project's normal delivery; deploy only when the project's own policy says so | see internal-deploy |
| Report language | Chinese (分类归纳总结) | owner convention |

## One round

1. **Sweep per dimension.** Gather evidence from: the project's
   GOALS/TODO/PROGRESS/BRAINSTORM (what did we already know), live probes
   of the running app (pages, API health, flows), code reading, and
   observability (obs-review-loop) where wired. A finding is only real
   with evidence: `path:line`, a URL, or a log excerpt. No-evidence
   observations are dropped, not reported.
2. **Classify.** Dimension × severity:
   - P1 — user-blocking (broken flow, error, data loss risk)
   - P2 — real friction (confusing, slow, half-wired)
   - P3 — polish
   - 机制缺口 — the "how would we know" instrumentation/monitoring/
     process piece is missing (e.g. no alert would fire if this regressed)
3. **Fix in-round.** P1/P2 that are reversible AND unambiguous: branch,
   fix, run the project's real gate, live re-probe, commit small. One
   focused batch per round — no mass edits across dimensions.
4. **Park the rest.** Ambiguous merit → investigate the merit first (read
   the code, run it, compare against main) and return a recommendation;
   only genuine product-direction/preference calls and irreversible/policy
   actions go to `.claude/decisions.md` / `.claude/blockers.md` with the
   evidence attached. Parking never stops the loop.
5. **Convergence check.** Diff this round's findings against all previous
   rounds. Same root cause resurfacing = not converged: dig one level
   deeper (why did the fix not stick?). Duplicates merge.

## Verification discipline (non-negotiable)

- A fix is claimed only with the gate output and the live re-probe
  evidence in hand — look at the real thing, not the edit.
- If a round's fix cannot be verified (env down, no gate), say so in the
  report; the finding stays open. Never downgrade "unverified" to "done".

## Final report (Chinese, this exact shape)

1. **结论** — converged or cap-hit; rounds run; stop-rule evidence.
2. **分类归纳表** — dimension × severity × 状态(已修/暂缓/机制缺口),
   one line each with evidence pointer.
3. **已修** — commit list, each with its verification evidence.
4. **暂缓** — item, reason, recommendation, what would un-block it.
5. **机制缺口** — the "how do we know it succeeded" pieces that do not
   exist yet (missing alerts, missing funnel, missing success metric).
6. **Gap-to-goal** — against the project's GOALS.md: what remains, and
   whether new findings changed the goal picture.
7. **Owner 决策** — only genuine rung-4 items, each with evidence.

## Failure modes to avoid

- Inventing findings to look productive (convergence means zero new real
  findings, not zero reported ones — the report must survive re-audit).
- Re-classifying the same finding to dodge the stop rule.
- Fixing 收钱/login in the same batch as unrelated changes.
- Ending a round with "want me to continue?" — the loop continues until
  the stop rule fires; only then write the final report.
