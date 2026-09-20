---
name: converge-loop
description: Multi-round gap-analysis convergence loop — sweep a product across dimensions (UIUX, login, services, payments, system), fix what is fixable each round, re-audit, and stop when consecutive rounds find nothing new. Produces a categorized Chinese report. NOT a one-shot audit or the corrections-rules meta-audit (/audit).
when_to_use: "直到converge, 收敛循环, gap分析, 找出所有问题, loop审核, 一轮一轮查, 找不出新毛病, converge loop, gap analysis loop, keep fixing until converged"
user_invocable: true
---

# Converge Loop

Drive a product to convergence: repeated rounds of gap discovery across
agreed dimensions, fixing reversible findings in-round, parking the rest
with recommendations, stopping when new-findings dry up. The executable
instructions live in `prompt.md`; this body is the Codex-facing summary.

Key contracts:

- Every finding carries evidence (file:line, URL, or log excerpt) and a
  dimension × severity classification. Findings without evidence are dropped.
- Fixable = reversible AND unambiguous. Those are fixed in-round, verified
  by the project's real gate plus a live re-probe, and committed small.
- Everything else is parked with a recommendation (`.claude/decisions.md` /
  `.claude/blockers.md`), never silently dropped, never used to stop the loop.
- Convergence is explicit: default stop rule is two consecutive rounds with
  zero new P1/P2 findings (cap: 8 rounds). The final report is in Chinese,
  categorized by dimension and severity, listing fixed work with evidence,
  parked items with reasons, and mechanism gaps ("how would we know this
  succeeded" monitoring that does not exist).
