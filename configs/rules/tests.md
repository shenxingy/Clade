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
