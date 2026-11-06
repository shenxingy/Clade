# /green — take the build from red to green on hardware you already own

Hosted CI is billed per job, rounded up to the minute, and multiplied by
platform (Linux 1x, Windows 2x, macOS 10x). Pushing to find out whether a
change compiles is the most expensive possible way to ask that question, and
the slowest. This skill asks it locally.

`~/.claude/scripts/ci-local.py` parses `.github/workflows/*.yml` and runs the same
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
- a retry loop, a longer sleep or a bigger timeout around a step that failed
  once and then passed — that hides a flake instead of explaining it
- widening a version range or unpinning a dependency to dodge a conflict

If the honest fix is genuinely to change the gate — the test encoded the old
contract and the contract moved — say so explicitly, show the assertion and the
new intended behaviour, and let the user decide. A gate weakened quietly is
worse than a red build, because a red build is still telling the truth.

## Loop

### 1. See the plan before running it

```bash
python3 ~/.claude/scripts/ci-local.py --list
```

If the answer is `ci-local: no .github/workflows under <path>`, this repository
has no hosted CI to mirror. Exit 1 there means **nothing to run**, not *red* —
say so, then fall back to the gates the project documents itself (its
`CLAUDE.md`, `AGENTS.md`, or `Makefile`) and report which of those you ran.
Never report a build green on the strength of a runner that found no gates.

Read what will be skipped and why. A job needing a platform this machine is not
belongs on the machine that has it, not on a hosted runner at 2x or 10x. A
workflow triggered by `pull_request_target` and by no push or pull_request, and
a job whose `if:` is false on every push and pull_request (a schedule or
dispatch tier), genuinely do not run here; say so rather than reporting a clean
run that covered less than it looks.

A `↳ UNPROVEN` line is different in kind: a lane the hosted run executes on
every push that this runner cannot reproduce — a job using `services:`,
`container:`, `strategy:`, a reusable workflow or a `defaults:` other than
`run: shell: bash`, or one whose body it cannot read; a `runs-on:` or job-level
`if:` it cannot evaluate; a step whose `if:` or `${{ }}` expression it cannot
evaluate; a step that needs a repository secret — declared on the step,
inherited from job or workflow env, or used in `run:` — which never runs here,
because a tool run without it falls back to this machine's own credentials
(`~/.aws`, `gh auth`, `~/.npmrc`); an action step other than checkout, cache,
artifact upload/download or a `setup-*` action, so a job whose only gates are a
lint action or a local composite is unproven, not setup-only. A step whose
INHERITED env holds a non-secret `${{ }}` value (a workflow-level
`REPO: ${{ github.repository }}`) runs with that variable unset, and its pass is
unproven too. Those are usually the backend, E2E and migration lanes, the ones
that cover the surface a change most often breaks. Name them before you run
anything; they will not become green here.

### 2. Run

```bash
python3 ~/.claude/scripts/ci-local.py --json
```

Use `--json`: it gives the failing job, the step name, the exit code, the exact
command, and the output tail, which is what you need to fix without guessing.
Pass a job argument through as `--job <name>` when the user named one.

Read `verdict` first, not the exit code — during the report-only rollout a
`partial`, `flaky` or `none` run still exits 0 (`--strict` makes it 2):

- `pass` with a non-empty `passed` → green. Report and stop. Do not push
  unless asked.
- `partial` → **not green.** Nothing that ran failed, but no entry in
  `unproven` (job, step, reason) was proven here: it was skipped, or it ran
  without env only the hosted run sets. Report PARTIAL with each unproven lane
  and its reason, and say what would prove it — the hosted run, or a machine
  with the services it needs. Never shorten PARTIAL to "green" or "CI will
  pass".
- `flaky` → **not green, and not fixed.** Nothing failed in the end, but each
  entry in `flaky` (job, step, `first_exit`, `first_output_tail`) failed once
  and passed on the one rerun ci-local gives every failed step. That first
  failure is real and unexplained. Investigate it as in step 3b; never report
  the rerun's pass as green or as a fix.
- `none` → **not green: no job ran.** Every job was skipped; `skipped` and
  `unproven` say why. Report it as nothing proven, then fall back to the gates
  the project documents itself, as in step 1.
- `fail` → continue below. A failed entry's `reason` can say the step ran
  without inherited env; if so, that may be the whole cause. A failed step was
  already run twice (`first_exit` is the first attempt's code; `exit_code` and
  `output_tail` are the rerun's), unless it hit the step timeout. After the fix,
  a re-run can come back `partial` or `flaky`, which is still not green.

A `partial` run lists its `flaky` steps too, and a `fail` run can carry them
beside the failure: handle each of them as in step 3b as well.

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

### 3b. A FLAKY step: find the cause, do not count the pass

For each entry in `flaky`:

- Read `first_output_tail` completely: it is the only record of the failure,
  and it names the case that failed.
- Try to make it fail again: run that step's command several times in the same
  directory, and under load if the host was busy. A test that shares state,
  depends on order, races a timer or a port, or reads the wall clock is the
  usual cause; name the one you found.
- If the cause is in the code or the test, fix it under the rule above — never
  with a retry, a sleep or a skip — and re-run that job.
- If it does not reproduce, stop and report it as FLAKY with the job, step,
  first exit code and the first attempt's output. Do not run ci-local again
  until it comes back green and call that green: a pass is what a flake does
  most of the time.

### 4. Fix the cause, then re-run only that job

```bash
python3 ~/.claude/scripts/ci-local.py --job "<job name>" --json
```

Re-running one job keeps the loop short. Re-run the **full** set once at the
end, because a fix in one job can break another — that is the whole reason CI
runs everything.

### 5. Stop conditions

- **Green** (`verdict: pass`, `passed` non-empty) → report, list what was
  skipped and why, stop.
- **PARTIAL** (`verdict: partial`) → nothing left to fix here; report it as
  PARTIAL with the unproven lanes, stop. It is not a green result.
- **FLAKY** (`verdict: flaky`, or flaky steps under another verdict) → report
  each flaky step with what step 3b found, stop. It is not a green result, and
  a flake you could not explain is not fixed.
- **Nothing ran** (`verdict: none`) → report it, with every skip and its
  reason, stop. It is not a green result either.
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
gh run list --status failure --limit 5          # find the run
gh run view <run-id> --log-failed | tail -60    # one run's failing step
```

For several failed runs at once, `~/.claude/scripts/scan-ci-failures.sh . 5`
already collects each run's failing step with its log tail. Read its output
rather than re-implementing it — it emits `===TASK===` blocks, so take the
prose and ignore the framing.

Then reproduce it locally with `--job` and continue from step 3. Note that
GitHub expires logs; if they are gone, identify the failing commit and
reconstruct the cause from the diff — `git show <sha>` against the test that
broke is usually enough.

### 6. Before reporting green, look at what you touched

```bash
git diff --stat HEAD -- .github/workflows/ '*test*' '*conftest*' \
  ruff.toml pytest.ini setup.cfg tox.ini package.json
```

Every file listed is a gate. Name each one at the top of the report with its
reason, or undo it — an empty output here is the claim you are making when you
report green. An anti-cheat rule enforced only by the honesty of the agent it
constrains is the weakest form there is, and that agent is under pressure to
produce green.

## Report

State plainly:

- the verdict — pass, PARTIAL, FLAKY, nothing ran, or fail — in the first line
- which jobs ran, which passed, and **how long the whole thing took**
- every **unproven** lane with its reason, and what would prove it
- every **flaky** step with its first exit code, the failing case its first
  output names, and the cause, or that none was found
- every skipped job with its reason, including the platform it needs
- for each fix: the root cause in one sentence, and the file changed
- anything you chose **not** to fix and why
- if you touched a gate at all, say exactly what and why, at the top

Never report "CI will pass" from a subset, and never from a PARTIAL or FLAKY
run or one where nothing ran. Report what ran.
