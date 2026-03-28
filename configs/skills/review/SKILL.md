---
name: review
description: Coverage-driven review — tests all VERIFY.md checkpoints systematically, fixes failures in-session, converges when full coverage is achieved
user_invocable: true
---

# Review Skill

Performs a systematic, coverage-driven review of the project by working through every checkpoint in `VERIFY.md`. Unlike a free-form code review, this skill tests specific scenarios end-to-end, fixes failures immediately, and only declares convergence when all checkpoints are ✅ or ⚠.

**Convergence condition**: all checkpoints in VERIFY.md are ✅ (pass) or ⚠ (known limitation). No ⬜ (untested) or ❌ (fail) remaining.
