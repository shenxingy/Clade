---
paths: tests/test-*.sh, orchestrator/tests/**/*.py
---
**A test that cannot fail is the defect this repository keeps shipping.** Four of
its own instruments have now been found unable to fire.

- **Prove the new test fails against the OLD code.** Not "it passes now" — run it
  against `git show HEAD:<file>` or a scratch copy and record both outcomes. A
  test written after the fix, never run before it, pins nothing.
- **A skip is not a pass.** Never call `pass()` on a skip path. Count and print
  skips separately, so "nothing ran" and "everything passed" cannot look alike.
- **Never report a rate over a zero denominator.** `fired/max(1,checked)` turns
  "measured nothing" into "0%", which reads as good news.
- Adding a `--self-test` to a script means adding its mutations to
  `orchestrator/tests/test_self_tests_can_fire.py` **in the same commit**, and
  each mutation must be shown to turn that self-test red.
- Assert on the property, not on the prose. A test that greps for a sentence in a
  markdown file proves the sentence exists, not that anything obeys it.
- **Property-first for a pure function** (text in, text out: a redactor, parser,
  normaliser). Write a Hypothesis property for what must NOT happen before more
  examples, pin each shrunk counterexample with `@example`, and keep a mutation
  in the file that makes the property find one. `test_redact_properties.py` is
  the model: its first runs found three defects the example tests in
  `test_redact.py` had missed.
- **A test that goes green on an unchanged rerun is FLAKY, not green.** Report
  both outcomes and fix or pin the cause. "Re-run once; if it passes, discard
  it" teaches the agent that retrying beats fixing.
