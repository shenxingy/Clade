# /green — take the build from red to green on hardware you already own

Hosted CI is billed per job, rounded up to the minute, and multiplied by
platform (Linux 1x, Windows 2x, macOS 10x). Pushing to find out whether a
change compiles is the most expensive possible way to ask that question, and
the slowest. This skill asks it locally.

`configs/scripts/ci-local.py` parses `.github/workflows/*.yml` and runs the same
`run:` blocks, so it cannot drift from CI the way a hand-maintained checklist
does — one such checklist in this toolkit was wrong twice.

## The rule that outranks the goal

**Never change a gate to make it pass.** The goal is a correct build, not a
green one, and the difference is the whole value of the exercise. Specifically
forbidden unless the user asks for it in those words:

- deleting, skipping, or `xfail`-ing the failing test
- loosening an assertion so the current (wrong) output satisfies it
- adding the failing rule to an ignore list, baseline, or `per-file-ignores`
- `continue-on-error`, `|| true`, or `echo` after the command — the last one
  masks the exit code and turns red into green while changing nothing
- widening a version range or unpinning a dependency to dodge a conflict

If the honest fix is genuinely to change the gate — the test encoded the old
contract and the contract moved — say so explicitly, show the assertion and the
new intended behaviour, and let the user decide. A gate weakened quietly is
worse than a red build, because a red build is still telling the truth.

## Loop

### 1. See the plan before running it

```bash
python3 configs/scripts/ci-local.py --list
```

Read what will be skipped and why. A job needing a platform this machine is not
belongs on the machine that has it, not on a hosted runner at 2x or 10x. Jobs
requiring a repository secret or `pull_request_target` genuinely cannot run
here; say so rather than reporting a clean run that covered less than it looks.

### 2. Run

```bash
python3 configs/scripts/ci-local.py --json > /tmp/ci-local.json; echo "exit=$?"
```

Use `--json`: it gives the failing job, the step name, the exit code, the exact
command, and the output tail, which is what you need to fix without guessing.
Pass a job argument through as `--job <name>` when the user named one.

Green, with nothing skipped that matters → report and stop. Do not push unless
asked.

### 3. Diagnose one failure at a time

For each entry in `failed`:

- Read the `command` and `output_tail` **completely** before forming a
  hypothesis. A truncated read is how a mid-stream counter gets mistaken for a
  result — a `tail -4` of a passing suite once read as "7 passed, 5 failed"
  when the real answer was 187/187.
- Reproduce the failing command by hand, in the same directory. If it passes by
  hand, the difference is the environment (`CI=true`, a clean checkout, a
  missing build artefact, a stale deployed copy), and that difference is the
  bug.
- Name the root cause before editing. "The test asserts an exact set of seven
  filenames and the change added an eighth" is a cause; "the test fails" is not.

### 4. Fix the cause, then re-run only that job

```bash
python3 configs/scripts/ci-local.py --job "<job name>" --json
```

Re-running one job keeps the loop short. Re-run the **full** set once at the
end, because a fix in one job can break another — that is the whole reason CI
runs everything.

### 5. Stop conditions

- **Green** → report, list what was skipped and why, stop.
- **Same failure twice with different fixes** → stop and report. Two failed
  hypotheses mean the model of the failure is wrong; a third guess is a loop,
  not progress.
- **Three rounds** → stop and report what is left, with the failing command so
  the user can run it.
- **The fix requires a decision** (change a contract, drop a dependency, accept
  a behaviour change) → stop and ask. Do not decide it by editing.

## When the red run was on GitHub, not here

Pull the failure down rather than pushing again to watch it:

```bash
gh run view <run-id> --log-failed | tail -60
```

Then reproduce it locally with `--job` and continue from step 3. Note that
GitHub expires logs; if they are gone, identify the failing commit and
reconstruct the cause from the diff — `git show <sha>` against the test that
broke is usually enough.

## Report

State plainly:

- which jobs ran, which passed, and **how long the whole thing took**
- every skipped job with its reason, including the platform it needs
- for each fix: the root cause in one sentence, and the file changed
- anything you chose **not** to fix and why
- if you touched a gate at all, say exactly what and why, at the top

Never report "CI will pass" from a subset. Report what ran.
