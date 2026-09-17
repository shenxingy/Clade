---
paths: orchestrator/judge_diversity.py, orchestrator/evals/**
---
**Re-run the eval after touching anything here — the thresholds are measured, not chosen.**

`cd orchestrator && .venv/bin/python evals/run_hack_eval.py`

Recall and false alarms move together; the round-1 numbers in this file's header
are what a self-graded corpus looks like just before adversarial cases halve them.

- A regex change is a **population** change. `\bassert\b` could not match
  `assert_contains` (the underscore is a `\w`), so the detector saw **0 of 825**
  real shell assertions and returned `eroded:false` **with** `test_files:1` —
  "looked and found nothing". Widening a pattern also widens the false-alarm
  surface: measure `fp_rate` before and after, not just recall.
- Adding corpus cases changes the denominator CLAUDE.md states. The derivation
  test `test_documented_detector_score_is_derived` will catch it; update the
  sentence, do not weaken the test.
