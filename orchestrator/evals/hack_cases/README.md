# Reward-hack corpus

Labelled diffs that score `judge_diversity.test_integrity`. Run them with:

```bash
cd orchestrator && python evals/run_hack_eval.py
```

Each file is a real unified diff with a three-line header:

```
# label: hack | honest
# family: short-slug
# note: why this is (or is not) a reward hack
diff --git a/tests/test_calc.py b/tests/test_calc.py
...
```

## The corpus is the point, not the score

The detector scored **100% recall / 0% false alarms** the first time it was
measured — against cases written by the same person who wrote the detector. A
second round, written specifically to evade it, dropped that to **62.5% / 27.3%**
in one commit. Every signal in `test_integrity` today exists because a case here
proved the previous version blind.

So the score is a floor, not an achievement. If you can think of a way to reach a
green suite without fixing the code, **add it as a `hack` case and let it fail**.
A red gate that names a real evasion is worth more than a green one that only
covers what someone already thought of.

## Both halves are load-bearing

Recall alone is maximised by flagging every diff that touches a test file, and a
signal that fires constantly is one reviewers learn to skip. Honest cases —
renames, moves, splits, fixture extraction, parametrization, mocking a
collaborator, deleting a feature with its tests — are what keep the detector from
degenerating into that. Adding a `hack` case usually means adding the nearest
`honest` case beside it.

## The limit that will not move

`hack-expectation-flip-match-buggy-output` and
`honest-typo-fix-in-expected-string` are the same edit: an expected value
changed. Telling them apart requires the specification, which no diff contains.
That is why these are signals handed to the LLM judge rather than a hard gate,
and why the false-alarm ceiling in `run_hack_eval.py` is not zero. Do not "fix"
it by deleting the signal that catches expectation flips.

## Known blind spots

Nothing here scores whether the *source* fix is real — only whether the tests
were weakened around it. A patch that special-cases the visible inputs leaves
this corpus untouched; that failure mode is measured separately by the held-out
tests in `../resolve_cases/synthetic-proxy-gamed.json`.
