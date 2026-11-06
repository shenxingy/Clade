# Codex Orchestrate — supervisor of a `codex exec` worker fleet

You are the **orchestrator**. Codex workers are the hands; you are the verification gate. Nothing a worker produces reaches `main` until YOU have independently verified it. This is the manual version of Codex's native fan-out (`model_reasoning_effort = ultra`) — but it has no 4-slot cap (bounded only by host/quota) and every result passes your review.

## When to use / not

- **Use**: implement several independent gaps/features, research N repos or people in parallel, run N review dimensions, any "do it at scale with Codex" that benefits from parallelism + a review gate.
- **Not**: a single cross-vendor sanity check → `second-opinion-codex` agent. Web-UI task decomposition → `/orchestrate`. A quick one-off codex question → just run `codex exec … < /dev/null`.

### Cost reality (be honest about what delegation buys)

Delegating to Codex is **not** a token saver — a worker re-reads its whole context cold, so *total* tokens go UP (measured ~4× vs doing one gap yourself). What it actually buys, and the only reasons to reach for it:

- **Your context stays lean** (~3× less on the orchestrator side): the worker eats the reads/edits, you keep only the diff + verdict. This is the real win on a long multi-step run — it delays your own compaction and lets you hold more threads.
- **Separate quota pool**: the worker burns the *Codex* weekly limit, not your Claude session's. If the Claude quota is the binding constraint, offload even though total tokens rise. (Watch both pools — `codex-usage` + the Claude statusline.)
- **Wall-clock speedup ONLY when workers run async/parallel.** A single **synchronous** `codex exec` you sit and wait on is *slower* than doing it yourself (dispatch + review overhead). The speed only materializes with ≥2–3 independent workers fanned out and a non-blocking poll. If you're delegating one gap and blocking on it, just do it yourself.

Rule of thumb: reach for the fleet when your context is the scarce resource, the Claude quota is tight, OR you have ≥2–3 independent gaps to parallelize — not for a single quick fix.

## The loop

1. **Scout inline first** — enumerate the work list (the gaps, the repos, the files). Do the cheap discovery yourself; only fan out once you know the shape.
2. **Classify** — separate code-able-now from design-heavy from research/ops. Don't fire a worker at "monitor X" or "benchmark on live tasks" (those aren't "write it and merge").
3. **Per worker: isolated worktree off the latest main**
   ```bash
   git -C <repo> fetch origin main -q
   git -C <repo> worktree add -q -b feat/gap-<slug> <scratch>/wt-<slug> origin/main
   ```
   The worktree has no `.venv` (gitignored) — tell the worker to verify with the main repo's interpreter: `<repo>/orchestrator/.venv/bin/python -m pytest`.
4. **Write a tight prompt** (one file, fed via stdin). Scope it to ONE gap, name the exact files to study + build, demand **additive** changes (no deleting existing writes), require the worker to run py_compile + the new test + (for core-engine code) the FULL suite, and forbid `git commit` (leave it in the worktree for your review).
5. **Dispatch — headless, network/writes on, stdin closed, detached + polled:**
   ```bash
   setsid nohup bash -c '
     echo $$ > <pgid-file>
     codex exec -C <worktree> --dangerously-bypass-approvals-and-sandbox \
       -o <last-msg-file> < <prompt-file> > <log> 2>&1
     echo "rc=$?" > <done-flag>
   ' >/dev/null 2>&1 &
   disown
   ```
   `<pgid-file>` records the wrapper's pid. Under `setsid` that wrapper leads a new session and process group, both numbered by its pid, so this file is the handle that **Steer, cancel, follow up** (below) signals. Then launch a **separate** `run_in_background: true` poll that waits for `<done-flag>` to appear (loop `sleep 20; [ -f <done-flag> ] && break`). Why detached, not codex-as-the-tracked-command: a worker that runs many minutes as the *foreground process of a tracked background Bash task* can be **reclaimed by the harness at a turn boundary** — observed killing a codex worker twice at ~1–4 min while it was still in its study phase. `setsid nohup … & disown` runs codex in its own session so it survives turn/session boundaries; the lightweight flag-poll is what gets tracked. `--dangerously-bypass-approvals-and-sandbox` is safe here: the worktree is throwaway and nothing merges without your review (bubblewrap can't create user namespaces on some hosts anyway, so the plain sandbox degrades).
6. **Verify (验收) — adversarially, independently:** see the checklist below.
7. **PR + merge** the ones that pass; for the ones that don't, **follow up** (resume the same session), **fix it yourself**, or **re-dispatch** cold. **Steer, cancel, follow up** below says which. For core-engine work, merge **sequentially** (each next worktree cut off the just-updated main) so PRs don't conflict on shared files.
8. **Loop** to the next work item. Report progress per merge.

## Dispatch gotchas (each is a real failure, not hypothetical)

- **`< /dev/null`** — `codex exec "<prompt>"` in a non-interactive shell (your Bash tool, or a subagent) BLOCKS reading stdin until EOF even though the prompt is an argument. Always redirect stdin (or use a heredoc, which closes it). Symptom: the worker "hangs", the foreground call times out at 120s. This also affects any agent that shells out to codex (`second-opinion-codex` needs it too).
- **Detach long workers; poll a flag — don't run codex as the tracked foreground.** A codex worker that runs many minutes as the foreground process of a `run_in_background` Bash task can be reclaimed by the harness mid-run (observed: killed twice at 1–4 min, still in the study phase). Fully detach it (`setsid nohup … & disown`) so it lives in its own session, write a `rc=$?` flag on exit, and track a *separate* lightweight poll that waits for the flag. A quick (<~60s) worker can run as a tracked foreground fine; the detach matters for the long ones. (A bare `codex exec … &` buried in a combined command also survives — it orphans — but then you have no flag and must poll by hand; the `setsid`+flag form is the clean version.)
- **Worktree, not the live checkout** — never let a worker edit the repo you're standing in, and never let two writers share one worktree/build dir. Cut a fresh worktree per worker off `origin/main`.

## Steer, cancel, follow up

Checked 2026-11-06 against `codex-cli 0.167.0` on Linux, from `codex exec --help`, `codex exec resume --help`, and the log headers and process trees of real runs in a scratch repository. None of those runs reached a model; **Not verified** at the end of this section says what that leaves open. Re-read `codex exec resume --help` after a Codex upgrade.

`codex exec` has no channel into a running turn: no option or subcommand in `codex exec --help` delivers a message mid-run. That leaves three moves:

| You want to | Do |
| --- | --- |
| **Follow up** once it has finished | wait for `<done-flag>`, then **resume** the same session with the next instruction |
| **Steer** it mid-run | **cancel**, then **resume** with the correction |
| **Stop** it for good | **cancel**, then `git worktree remove --force <worktree>` |

### Cancel: signal the worker's whole session

```bash
P=$(cat <pgid-file>)
if [ -f <done-flag> ]; then
  cat <done-flag>                                          # finished already: nothing to cancel
elif ps -ww -o args= -p "$P" | grep -qF -- '<worktree>'; then
  pkill -TERM -s "$P"                                      # every process in the worker's session
  for i in 1 2 3 4 5; do pgrep -s "$P" >/dev/null || break; sleep 1; done
  pkill -KILL -s "$P"                                      # whatever ignored TERM for 5 s
  [ -f <done-flag> ] || echo "rc=cancelled" > <done-flag>  # the killed wrapper writes none
  pgrep -l -s "$P" || echo "cancelled: nothing left in session $P"
else
  echo "pid $P is not this worker's wrapper; nothing killed"
fi
```

Run it as one block. Each Bash call starts a fresh shell, so a later `pkill -s "$P"` would see an empty `$P`.

- **Signal the session, not the process group.** `kill -- -$P` reaches only the wrapper's process group, and codex moves some children out of it: on 0.167.0 an MCP-server child ran in a process group of its own inside the same session. That child died when codex did in the observed run, not from the signal. `pkill -s` reaches everything still in the session.
- **The `ps … | grep` check** refuses to signal a pid that is no longer this worker's wrapper, such as a pid reused after the worker exited. The wrapper's command line contains `<worktree>`.
- **Write the flag yourself.** The wrapper is killed before its `echo "rc=$?"` runs, so without this line the tracked poll waits forever.
- **`$$`, not `$!`.** setsid(1) forks when its caller already leads a process group, which every background job does in a shell with job control. `$!` then names a setsid process that has already exited. The wrapper's own `$$` is right in both cases.

### Follow up or steer: resume the same session

The header of every `codex exec` log names the session. This prints the id that replaces `<session-id>` below:

```bash
grep -m1 '^session id:' <log> | awk '{print $3}'
```

Dispatch the next round detached, exactly like the first. Give each round its own log, last-message file and done-flag (suffix `.2`, `.3`, …): the poll waits for a flag to *appear*, and the earlier round's log is your only record of the id.

```bash
setsid nohup bash -c '
  echo $$ > <pgid-file>
  codex exec -C <worktree> resume <session-id> --dangerously-bypass-approvals-and-sandbox \
    -o <last-msg-file>.2 - < <followup-file> > <log>.2 2>&1
  echo "rc=$?" > <done-flag>.2
' >/dev/null 2>&1 &
disown
```

Poll `<done-flag>.2`. To cancel this round, run the cancel block with `<done-flag>.2`. Each observed on 0.167.0:

- **`resume` works in the directory you run it from, not the session's.** Resumed from a different repository without `-C`, the header's `workdir:` line named that other repository. Run from your live checkout, the worker would edit the live checkout. Put `-C <worktree>` **before** `resume`: `codex exec resume --help` lists no `-C` of its own, and `codex exec -C <dir> resume …` was accepted and worked in `<dir>`. After `resume`, `-C` or `--cd` is rejected before anything runs (`error: unexpected argument '-C' found`, exit 2), so that round writes `rc=2` and does no work.
- **Flags and `-c` overrides do not carry over.** A session started with `-c model_reasoning_effort="low"` resumed at the config default (`high`). Pass `--dangerously-bypass-approvals-and-sandbox`, `-m` and every `-c` again.
- **`-` reads the prompt from stdin.** The follow-up file is both the prompt and the stdin that reaches EOF, so the `< /dev/null` rule still holds.
- **After a steer, say so.** Open the follow-up prompt with "your last turn was cancelled; run `git status` before you continue". A cancelled turn can leave edits half-applied.

**Resume or re-dispatch cold?** Resume when the approach was right and the correction is bounded: a test it missed, a checklist finding, a file it should not have touched. The worker keeps what it already read. Re-dispatch cold, with a fresh worktree and a corrected prompt, when the approach itself was wrong, because a resumed worker carries its plan forward. A resume re-sends the conversation so far; whether it costs fewer tokens than a cold re-dispatch is not measured here.

**Not verified.** The Codex profile on the checking host was not logged in, so no run reached a model. That a resumed worker recalls its earlier turns comes from `codex exec resume --help` ("Resume a previous session"), not from a run. How a cancelled turn's partial work appears in the resumed context is unknown. No shell-tool command ran either, so whether codex starts those inside the worker's session is unverified; one started in a session of its own would survive the cancel block. What was observed: after a run was killed, `resume` started against the recorded session, with the same `session id:` in its header.

## Verification checklist (do NOT skip — this is the whole point)

For each finished worker:
- [ ] **Scope**: `git -C <wt> status --short` — did it touch ONLY the files it was scoped to? (New files are untracked — `git diff --stat` alone misses them.)
- [ ] **Additive**: `git -C <wt> diff | grep '^-'` — did it DELETE or alter existing writes/behavior when it was told to be additive? A deletion in core code is a red flag; read it.
- [ ] **Independent test run — DON'T trust the summary.** Re-run yourself with the main venv against the worktree. A worker claimed "996 passed"; the truth was 995 passed + 1 real failure. For core-engine changes run the FULL suite; a passing new test proves nothing about regressions.
- [ ] **Can't build it locally? Then CI is the SOLE gate — "reviewed + worker says passed" is NOT verified.** When the worker's output is in a language/toolchain the orchestrator host can't build (e.g. a C#/.NET change on a Linux box with no SDK, an iOS target, a CUDA kernel with no GPU), you CANNOT run the step above — so logic-review alone can never catch a compile error. Push the branch, let the PR's build+test gate run, and **do not report the change done until that check is green.** A worker's `using`/import omission, a type mismatch, a signature drift compile clean in the worker's head and pass its self-review, then fail CI: e.g. codex added a reporting test that used `RosterStatus` without `using Halo.App.ViewModels;` — invisible to a Linux-side logic review, a hard `CS0246` in CI. Treat a red CI as an un-finished worker task (fix it yourself or re-dispatch), never as "done, minor CI flake."
- [ ] **Pre-existing vs introduced**: if a test fails, run it on clean `main` too — a failure present on both is pre-existing (e.g. an env-specific test), not your worker's regression. Note it, don't block on it.
- [ ] **Spec adherence**: read the actual diff against what you asked. Workers deviate — one made a "projection" silently drop fields when the spec said identity/superset. Fix it yourself (you're the gate) or re-dispatch.
- [ ] **Then** commit (in the worktree, on its branch), push, PR, let CI confirm, merge.

## Cleanup

After each merge: `git worktree remove <wt> --force`, `git branch -D feat/gap-<slug>`, `git checkout main && git pull --ff-only`. Then cut the next worker's worktree off the freshly-pulled main.
