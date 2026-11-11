---
name: merge-pr
description: Integrate an exact reviewed PR under repository policy, choose truthful history semantics, and verify cleanup
when_to_use: "merge PR, integrate pull request, squash/rebase/merge PR, clean merged branch"
argument-hint: '[PR_NUMBER_OR_URL] [--strategy auto|squash|rebase|merge]'
user_invocable: true
---

# Merge PR

Integrator workflow for an already reviewed Clade delivery. It never treats
authorship as merge authority, never bypasses pending/red gates, locks the
reviewed head SHA, respects repository merge policy and live child ancestry,
and does not finish until mainline/branch cleanup is verified. A green gate on
the exact head plus a clean merge into the current main is the merge
condition; main moving is never a reason to re-gate.
