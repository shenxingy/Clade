# Clade — Project Context

## Project Type
- Type: cli + skill-system
- Frontend: Vite + React + TypeScript UI under orchestrator/web/src/. `web/dist` is the ONLY servable root — `orchestrator/start.sh` builds it on first run, or `cd orchestrator/web && npm ci && npm run build` by hand. Without it `/web` returns 503 naming that command; `web/` itself is a source tree and is never mounted, and `/` redirects to `/web/`.
- Backend: FastAPI (orchestrator/) — optional, CLI layer works standalone. TWO start
  paths with DIFFERENT ports, which is why a single number here was wrong:
  `orchestrator/start.sh` defaults to **8765** (`ORCHESTRATOR_PORT`, start.sh:11), while
  the bare `uvicorn server:app` below inherits uvicorn's own **8000**. Match the port to
  the command you actually ran.
- Test command: cd orchestrator && .venv/bin/python -m pytest tests/ -v
- Verify command: cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 .venv/bin/python -m py_compile

## Features (Behavior Anchors)
- install.sh: running `./install.sh` copies skills/hooks/scripts/agents/output-styles to ~/.claude/ without errors, and activates no output style
- slt: running `slt` cycles the statusline mode (symbol → percent → number → bar → off)
- /commit: creates repository-adaptive checkpoint commits and publishes when the active delivery or repository policy authorizes it
- /loop: given a goal file, runs supervisor+worker iterations until converged or max-iter
- committer: `committer "type: msg" file1 file2` stages only named files and commits
- loop-runner.sh: runs background loop — supervisor plans tasks, workers execute in parallel via worktrees
- /tasks: imports a shared Beads dependency graph, atomically claims ready work, and releases downstream tasks only after explicit acceptance; see docs/reference/shared-tasks.md
- context policy: `./install.sh --context-policy` writes top-level `autoCompactWindow: 350000` into `~/.claude/settings.json` only where the key is absent and records it in `~/.claude/.clade-context-state.json`; a plain `./install.sh` writes nothing (opt-in until measured), a value the user set is never touched again, a key the user deleted is not re-added until the next `--context-policy`, `--no-context-policy` (or `./uninstall.sh`) removes only a Clade-owned value, and while Claude Code's `.claude.json` caches a server-side window (`autoCompactWindowsCache`, `rowan_thicket`) it retracts its own value and writes none; see docs/configuration.md#context-window-policy

## What This Project Is

A multi-surface coding automation toolkit:

- **CLI layer** (`configs/`) — skills, hooks, scripts installed via `./install.sh`
- **Codex plugin** (`plugins/clade/`) — 31 generated native skills plus Codex hooks, distributed by `.agents/plugins/marketplace.json`
- **MCP package** (`mcp-package/`) — provider-selectable Claude/Codex execution for external MCP clients
- **Orchestrator layer** (`orchestrator/`) — FastAPI web server with worker pool, task queue, GitHub sync, iteration loops

## Key Commands

```bash
# Install CLI layer (skills, hooks, scripts, agents)
./install.sh

# slt — statusline-toggle (quota pace indicator). See /slt skill.

# Start orchestrator (from project root or orchestrator dir)
cd orchestrator && uvicorn server:app --reload

# Run tests
cd orchestrator && .venv/bin/python -m pytest tests/ -v

# Syntax check (all Python modules — same find-based sweep CI runs)
cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 .venv/bin/python -m py_compile

# Multi-machine usage tracking — see orchestrator/usage_tracker.py
#   A token is NOT optional here, which this line used to imply. `/api/usage/ingest`
#   is exempt from the control-plane token only WHILE `usage_ingest_token` is set
#   (api_auth.py:80, SELF_AUTHENTICATED_IF_SET); leave it empty and the endpoint
#   falls back to the control plane, so a token is still required — just a
#   different one. Either way the node sends `Authorization: Bearer`.
#   Hub:  start orchestrator normally, set usage_ingest_token in ~/.claude/orchestrator-settings.json
#   Node (no orchestrator): python3 configs/scripts/usage-agent.py --hub http://hub:8765 --token X [--once]
#     (--token defaults to $CLADE_USAGE_HUB_TOKEN and must match the hub's usage_ingest_token)
#   Node WITH an orchestrator: it pushes through the `usage_hub_token` setting
#     instead (config.py:319 → server.py:161) — a different mechanism, easily
#     confused with the env var above.
#   Dashboard: http://hub:8765/web/usage.html
# Per-machine ccusage data is stored in ~/.claude/orchestrator/usage.db.

# MCP server — exposes skills to external AI coding tools (Cursor, Cline, etc.)
# Inside Claude Code, skills are already native (/blog-write, /commit) — no MCP needed.
# The distributable mcp-package supports CLADE_RUNTIME=claude|codex. Do not add
# it inside Claude Code or Codex when native skills are installed: that duplicates
# every skill and spawns nested agent sessions. See mcp-package/README.md.

# Red-phase audit — run the tests a commit ADDS against its parent. One that
# already passes needed nothing from the change: it pins existing behaviour, or
# nothing. Covers the additive case judge_diversity.test_integrity is blind to
# (most test-carrying commits here are purely additive — no figure is quoted
# because 'purely additive' was never defined: re-deriving it gave 75 of 133
# under 'deletes no line from any test file' and 82 under another reading,
# against the 115 this line used to assert).
# Diagnostic, not a gate — a test that passes at base can be a deliberate
# characterization test. No fire rate is quoted here on purpose: the script
# samples candidates[::step][:limit], so the rate is a function of the limit
# you pass — measured 19% at 25, 29% at 30, 29% at the default 40, 33% at 21.
# An earlier '~17%' reproduced at none of them and had no recorded provenance.
# SCOPE, and it is narrower than this file implied until 2026-09-17:
# RED_PHASE_SUBDIR defaults to `orchestrator` — the layer docs/layers.json marks
# DORMANT. Pointed at the terminal path it measures NOTHING: measured, with
# RED_PHASE_SUBDIR=configs it checks 0 of 25 sampled commits ("out of scope"),
# because configs/ carries no pytest suite and this repo's load-bearing tests are
# the shell suites in tests/ (28 files on 2026-10-20), which the script says
# outright it cannot see.
# It used to print "FIRED on 0 (0% of checked)" in that case — a rate over a zero
# denominator, i.e. the script announcing the exact failure it exists to detect.
# It now refuses to print a rate when nothing was checked.
# So: a real instrument, on the dormant half. Do not wire it into CI as a gate
# over the terminal path; it cannot see it.
# The interpreter is found automatically; RED_PHASE_PYTHON only overrides it.
# Pass an absolute path or a repo-relative one — a venv python is a symlink to
# the system python, so the script uses abspath rather than resolve() to avoid
# following that link out of the venv.
python3 configs/scripts/red-phase-audit.py 30

# Ask the instrument whether it can still go red. One positive and one negative
# control; CI runs this on every push. A harness that cannot fire reports a
# clean 0% exactly like a clean codebase — this one has done that before.
python3 configs/scripts/red-phase-audit.py --self-test

# Which numbers does this repository assert about ITSELF, and does anything
# derive them? Not whether they are right — it cannot know that, and pretending
# otherwise is the failure it exists to expose. Five audit rounds fixed numbers
# one at a time and the count would not fall, because the mechanism was never
# named. A 2026-09-14 re-verification found "~17%", "241 commits", "115 of the
# last 133", "~94k lines" and "~0.03% of the window" all unreproducible; only
# the detector score had a derivation available, and nothing used it.
# Report-only and hand-run on purpose: --strict is for once the list is triaged.
python3 configs/scripts/check-asserted-numbers.py
python3 configs/scripts/check-asserted-numbers.py --self-test

# Does OUR code erode the way the literature says? Measured 2026-09-16: no, for
# complexity — configs/ is 7.409 -> 7.372 (-0.5%) and orchestrator/ -5.4% over
# comparable windows. What IS eroding is documentation: configs/ lost 17 points
# of docstring coverage (76.5% -> 59.3%) while growing 39 files. It compares
# against the earliest sample holding half the final file count, because a
# first-to-last delta measures the project being born (+93%, from 1 file).
# It cannot separate agent- from human-written code; agency is recorded nowhere.
python3 configs/scripts/erosion-trend.py --samples 14 --path configs/

# Bring every machine to HEAD and reinstall the kit. Nothing in this repository
# deployed Clade anywhere but the box you were sitting on, and machines drifted
# silently: on 2026-09-16 two Linux boxes were 270 commits behind, a Mac 520,
# and one host advertised itself reachable on the tailnet while refusing every
# connection. The host list is ~/.claude/fleet.conf — OUTSIDE the repo, because
# hostnames and home paths are yours and this repo is public. A dirty worktree
# is reported and SKIPPED, never stashed: install.sh rm -rf's each skill dir.
bash configs/scripts/fleet-install.sh            # report, change nothing
bash configs/scripts/fleet-install.sh --apply    # pull --ff-only + ./install.sh

# 2b2. Ask every OTHER --self-test the same question. Removing one guard must
#      turn that script's self-test red. Five self-tests written on 2026-09-12
#      could not fail, including one where deleting an entire licence allowlist
#      still printed PASSED. Runs inside the pytest job.
cd orchestrator && .venv/bin/python -m pytest tests/test_self_tests_can_fire.py -q

# 2c. Same question of the polling instrument. `workflow-scorecard.py --polls`
#     counts repeated status reads per background job; its mutation guard once
#     matched the `>/` of `2>/dev/null`, so every session reported zero.
python3 configs/scripts/workflow-scorecard.py --self-test

# How well did a multi-agent run use its parallelism? Every Workflow run writes
# per-agent transcripts under ~/.claude*/projects/<slug>/<session>/subagents/
# workflows/, and until 2026-09-02 nothing read them: /retro mines git history,
# session-scorecard.sh mines corrections, and the PROCESS went unmeasured.
# Over 285 parallel runs (4,038 agents, 394 h, started 2026-09-22 → 10-24 UTC,
# the author's two profiles), one agent ran alone for 52.4% of makespan: 35.5%
# one-agent stages, which pipeline() cannot shorten, and 16.9% an agent
# outliving its siblings, which it can; 108 of the 285 lost 15% or more that
# way. Those are the `--ledger-summary` line below, over the author's ledger.
# Claude Code deletes transcripts after 30 days and the figures quoted here
# before 2026-10-23 went with them, so `--ledger` keeps one row per finished
# run's end, append-only, per API call (a resumed run's later end is a new row,
# and a reader takes the last). `--outcome` prints what the owner typed in the
# 6 h after each end, for weekly labelling by hand.
python3 configs/scripts/workflow-scorecard.py --project Clade --since 7
python3 configs/scripts/workflow-scorecard.py --since 0 --json   # all runs, machine-readable
python3 configs/scripts/workflow-scorecard.py --since 0 --ledger # <config dir>/workflow-scorecard/runs.jsonl
python3 configs/scripts/workflow-scorecard.py --ledger-summary --recorded-before 2026-10-24T03:34Z
python3 configs/scripts/workflow-scorecard.py --outcome          # JSONL, label: null

# Did the merged work STICK? Everything above measures inputs (how much ran);
# this scores the author's PRs merged in the window as reverted, fixed-forward
# (a later fix into the same base sharing a file — a signal, precision
# unmeasured), settling (younger than --settle 7, never kept) or kept, plus
# review load; the author's own revert PRs are not rated. With --since 7 no PR
# has settled, so no kept rate is printed (reverts and fix-forwards are still
# listed); --since 14 gives a rate. --tokens adds host-wide Claude Code tokens
# per merged PR, and per settled and kept PR from the tokens before now - settle.
python3 configs/scripts/outcome-scorecard.py --since 14 --tokens
python3 configs/scripts/outcome-scorecard.py --since 7 --repo shenxingy/Clade --json

# Where did the harness say no, and in how many sessions? Errors, PreToolUse
# hook denials, permission refusals, timeouts, unchanged retries after one of
# those, and hook_non_blocking_error, from the transcripts, ranked by DISTINCT
# sessions then count, on discovery ISO weeks with the last week held out (it
# prints the held-out span and warns below 7 days; radar passes
# --holdout-weeks 2). Each family shows its full refusal text, the next 3 calls
# and provenance. Friction is not a defect: a refusal can be a guard doing its
# job. Radar Lane D.
python3 configs/scripts/friction-rank.py                  # 30 days, main thread
python3 configs/scripts/friction-rank.py --subagents --json

# What did merged PRs say they could NOT verify? Every PR body carries
# `Review depth: none | skimmed | read-in-full` and `Could not verify: none |
# <item>; <item>` (create-pr §4, delivery §6, /ship, the PR template). This rolls
# them up for one repository, any author, and prints the top 3 items recurring
# in 2+ PRs as candidate TODO entries; it writes nothing. Both lines are
# self-reported: depth is checked against forge reviews, and a window where no
# PR states a line reads NOT MEASURED, never "nothing unverified".
python3 configs/scripts/pr-verification-gaps.py --since 14

# Which shipped skills and hooks FIRE? Per skill in configs/skills/ (a hub's
# sub-skills also roll up to it) and per hook wired in settings-hooks.json:
# fires, denies, rejections, timeouts, last fire, and for a hook how many tool
# calls and compactions it is wired on, from every profile's transcripts (main
# thread unless --include-subagents) and .claude.json skillUsage. Report-only.
# Never fired lists REVIEW candidates, not retire candidates; a preventive
# (synchronous PreToolUse) guard is never retired by zero fires; invocation is
# not behaviour change. --ledger appends one row per whole UTC day and scope to
# <config dir>/harness-usage/days.jsonl, because Claude Code deletes transcripts
# after 30 days and a longer window needs them; a pass that cannot read every
# transcript (or finds a profile linked to nothing) writes nothing and exits 1.
# Run it from a checkout: the copy install.sh puts in ~/.claude/scripts/ needs
# --repo <checkout>. It reads subagent transcripts
# too: 6,734 transcripts took 2 min 40 s on the author's host (2026-11-06),
# and a first --ledger pass (29 days x 2 scopes) took 3 min 3 s.
python3 configs/scripts/harness-usage.py --since 30
python3 configs/scripts/harness-usage.py --include-subagents --json
python3 configs/scripts/harness-usage.py --ledger

# Did a Codex worker actually delegate? `codex exec` CAN subdivide — measured
# 2026-09-05, the gate is the resolved model's catalog multi_agent_version, not
# the session source. This counts the children, and its self-test distinguishes
# a real zero from an unreadable state file.
python3 configs/scripts/workflow-scorecard.py --codex-children

# Context window policy (opt-in): who owns autoCompactWindow, what shadows it, the installed
# Claude Code against the version the policy was verified through, and Codex/Kimi report-only.
# Read-only and offline. Opt in/out with ./install.sh --context-policy / --no-context-policy.
python3 configs/scripts/context-policy.py status

# Native Codex plugin — regenerate after changing a shipped canonical skill
python3 configs/scripts/regen-codex-plugin.py
python3 configs/scripts/regen-codex-plugin.py --check
```

## Architecture — Surfaces and Layers

### CLI Layer (`configs/`)
- `skills/` — skill prompts invoked via `/skill-name` in Claude Code
- `hooks/` — pre/post hooks for Claude Code events (wired via `settings-hooks.json`).
  Each `hooks/*.sh` carries one `# exists-for: <incident or need, date, commit/PR> ·
  retire-when: <condition>` line in its first 10 (`tests/test-hook-provenance.sh`). Name a
  recorded incident or write "no incident recorded"; a blocking guard retires on an
  ablation, never on a quiet log.
- `scripts/` — shell utilities (e.g., `committer.sh`)
- `agents/` — subagent definitions for the Agent tool
- `output-styles/` — system-prompt register overrides selected via `/config`. The
  only primitive here that edits the *system* prompt rather than appending a user
  message, so it reaches turns `CLAUDE.md` cannot. All ship
  `keep-coding-instructions: true` (omitting it silently drops Claude Code's
  built-in engineering instructions) and none is activated by `install.sh` —
  selection stays the user's.

**Correction-pairing pipeline** (the learn-from-corrections loop — captures the "AI did X → it got rejected" pair so a rule is grounded in the real diff, not just words):
- `edit-shadow-detector.sh` (PostToolUse, async) logs files Claude writes → session-keyed shadow at `<runtime>/claude-edit-shadows/session-<session_id>.jsonl`, where `<runtime>` is `$XDG_RUNTIME_DIR/clade` or `${TMPDIR:-/tmp}/clade-$EUID` (`configs/hooks/lib/runtime-dir.sh`) — a fixed `/tmp` path is squattable, and on this 40-account host it silently disabled pairing for every account but the one that created the directory

**Per-attempt checkpoints** (separate from the correction pipeline above): `worker-checkpoint.sh` (PostToolUse **Edit|Write and Bash**, async) commits the whole worktree into a shadow repo OUTSIDE it, once per agent write. Until 2026-09-16 it was wired to Edit|Write only AND gated on a non-empty `tool_input.file_path`, so it was blind to a `python - <<EOF` heredoc — the one failure mode Ronacher's unattended run actually named. The path was only ever a commit-message label; the snapshot is `add -A`. In the same pass it stopped being inert on the terminal path: its only setter had been `orchestrator/worker.py`, in the layer `docs/layers.json` marks dormant, so the half of the system actually in use kept no checkpoints at all. `run-tasks-parallel.sh` now exports `CLADE_WORKER_SHADOW_DIR` per task. A worker commits exactly once — at the end of verification — and `stop()` force-removes the worktree, so "correct at call 14, wrong at 15" had no record. A separate `--git-dir` means a separate index, so checkpoints cannot contend with the worker's own commits (measured, see `tests/test-worker-checkpoint.sh`). A separate git-dir also has its own (empty) `info/exclude` and its own idea of what is tracked, so since 2026-11-26 the hook hands it the worktree's `info/exclude` (the common dir's, on a linked worktree) and `core.excludesFile`, drops a recorded path once a rule matches it, and keeps a tracked forced one: a snapshot holds what `git add -A` in the worktree would stage. The final SHA and count land in the evidence bundle before cleanup deletes the repo. Setting: `worker_checkpoint_shadow`.
- `revert-detector.sh` (PreToolUse Bash, async) on `git revert/reset/restore` cross-refs that shadow **against the command's own pathspec** → writes `reverted_files` (the intersection), `session_files` (the loose session list, under its true name), `revert_scope`, `revert_paths`, `repeat`, `session_id` and `transcript_path` into `~/.claude/corrections/history.jsonl`. `repeat` is meaningful only when `revert_scope` is `paths`: `git revert` takes no pathspec, `git reset --hard` cannot take one, and the hook is async, so for those the file set is not knowable at hook time — `reverted_files` is `[]` and `repeat` is `null`. Records written before 2026-09 carry the old semantics. `revert_scope:"probe"` marks a command that puts back what it reverted (`git apply`/`git stash pop` after the revert), edits the very path it reverts (`sed -i`, `python3 - "$f" <<'EOF'` — the dominant shape: 62 of the 115 implicit-revert records on the author's machine 2026-10-05 → 10-12, by a Python replay of the rule, none labelled), writes into it through a redirect or `tee` (`git show REV:f > f`), saves a diff it then applies elsewhere before cleaning this checkout (a move to another worktree), or carries the `MUTATION` label agents print — the mutation test the global CLAUDE.md requires, not a rejection — so it carries no `reverted_files`, no `session_files` and a null `repeat` (seven such records on 2026-09-23 had been feeding correction-detector false "files behind this correction"). `project` is the `cd` that runs BEFORE the revert, with `~` and variables the command itself assigns resolved; an unresolvable `$VAR` falls back to the session directory rather than being filed as a literal `$WT`. Heredoc bodies are stripped before any of this parsing, because agents write files through `python3 - <<'EOF'` and prose about git in the body used to trigger the hook and pick its project. Only the persisted `prompt` keeps the raw command. An index-only `git restore --staged` (no `--worktree`) changes no file, so it records nothing. Only the main thread writes: a call whose hook input carries `agent_id` (a subagent) or that runs under `CLADE_WORKER_TASK_ID` (a dispatched worker) records nothing. Of the 220 implicit-revert records on the author's machine 2026-09-22 → 10-22, 172 were issued by Workflow subagents inside their own runs, and every reader — `session-scorecard.sh`, the concrete-signal block of `correction-detector.sh`, `repeat`, radar Lane C — counted them as the owner rejecting a change; skipping rather than tagging keeps all of them correct without a new filter.
- `correction-detector.sh` (UserPromptSubmit, **sync**) on an explicit "that's wrong" surfaces those rejected files into the rule-extraction context. Silent when `CLADE_WORKER_TASK_ID` is set: a dispatched worker's brief is its only "user prompt", reads like a correction ("fix any…", "instead of", "不要"), and was being persisted as one per retry — 13 of the 72 explicit records `~/.claude/corrections/history.jsonl` holds for 2026-09-07 → 2026-09-21 on the author's machine. A `对不对` tag question ("…, right?") no longer fires; a real 不对 beside another 对 (绝对不对, 不对不对, a tag running into 不对) is split off first, so it still does. On 364 hand-labelled owner messages typed after Workflow runs (37 rejections) the strip takes precision from 41% to 57% at unchanged recall (35%), and on the 490 other main-thread messages the owner typed on the same machine 2026-08-26 → 10-23 all 5 fires it removed were tag questions. Eight rejection phrasings were added too (不太对, 理解错, 没懂, 不满意, 打不开, 做多了, 四不像, 说的/得太多), but only in-sample: they lift the labelled replay to 66% precision and 51% recall because they were read off that set's misses, they caught no rejection among the 490 (one non-rejection fire), and four of them — 理解错, 做多了, 四不像, 说得太多 — are never a message's only trigger, so they are unmeasured
- **Every record links to its session:** both detectors write `session_id` and
  `transcript_path`, so a corrected session can be found and replayed as an eval
  while its transcript lasts (Claude Code deletes transcripts after 30 days).
  None of the 1,636 records in the author's history.jsonl on 2026-11-05 had
  either: `correction-detector.sh` resolved the id only for its private-session
  check, after the append. It now resolves both from the hook input before the
  append, in the one `jq` call that check reuses, so the common path (no
  correction) spawns nothing new. The id keeps `[A-Za-z0-9_-]` (the underscore
  covers Kimi's `session_…` ids); a transcript path with a control character or
  over 1,024 characters is dropped, never trimmed.
  Unknown is `null`, and records written before this change lack both keys.
  The two hooks carry the filter verbatim (pinned by the test suite), and both
  write paths (`cp_append_history` and the no-lib `jq >>`) are tested.
- **Nothing raw is persisted:** `correction-detector.sh` masks the prompt through
  `redact.py` before any disk write, and all three persistence sites consume the
  masked value. Redaction runs *after* the correction gate — this is a sync
  `UserPromptSubmit` hook, so python3 must not spawn on prompts that write
  nothing — and *before* `cp_bound_prompt`, since clipping first can cut a token
  below its detection threshold and persist a partial credential. With python3
  unavailable the hook detects with a fallback pattern and **withholds the whole
  prompt** rather than substituting: those patterns are fixed-count, so a
  substitution masks a token's prefix and leaves its tail on disk (measured: 16
  of 48 characters survived).
- **The gate is the wiring, not code:** the two silent-signal hooks are `async` (output never fed back) → a bare revert stays data-only; only an explicit correction (sync hook) escalates to context. `repeat=true` is stored for auto-audit but never auto-writes a rule (avoids noise).
- Shared helpers: `hooks/lib/correction-pair.sh` (session key + shadow read) and `hooks/lib/runtime-dir.sh` (per-user scratch root; fails closed on a squatted path — not a symlink, owned by our euid, mode 0700). `history.jsonl`/shadow are compact JSONL (one object per line). Tests: `tests/test-correction-pairing.sh`.

### Orchestrator Layer (`orchestrator/`) — DORMANT as of 2026-09-02

Deliberately unused, kept building and green, and not load-bearing: a finding
here weighs less than one on the terminal path (`docs/layers.json`). Its import
DAG and key-file table are in
[docs/orchestrator-architecture.md](docs/orchestrator-architecture.md), and
`check-arch-map.py` fails when an `orchestrator/` module is missing there.

## The dotfiles sync store — a THIRD remote, and it was eating data

`~/.claude/{skills,hooks,scripts,corrections}` can be symlinks into a sync store
(`~/.claude/.sync-config` → `SYNC_DIR`) that is **its own git repository with its
own GitHub remote**. So "everything is pushed" has three answers, not one: this
repo's `origin`, the machines in `~/.claude/fleet.conf`, and that store. Nothing
said so, which is how the next defect went unseen for months.

`sync-push.sh` ran `git pull --rebase --autostash` and, on conflict,
`git merge -X ours`. Two failures compounded:

- The **autostash pop** (not the rebase) writes `<<<<<<< Updated upstream` /
  `>>>>>>> Stashed changes` into the working tree, and `git rebase --abort` does
  not clean that. The next run's `git add -A` committed the markers; the run
  after conflicted on a file that already held them, so they NESTED. Found
  2026-09-17: 11 marker lines two deep in `corrections/rules.md`, a file injected
  into every session's context. `correction-detector.sh` already carried a
  self-heal for exactly this in `stats.json` — the symptom was patched twice and
  the producer never was.
- **`-X ours` on an append-only log discards the other machine's appends.**
  Measured: 191 rule disappearances from `corrections/rules.md`, every one inside
  a `sync:` or `Merge` commit and **not one** inside an audit/promote commit,
  which is what a deliberate retirement looks like. 178 rules survived only in
  git history; they are now parked in `corrections/rules-archive.md`.

Fixed by `.gitattributes merge=union` on the append-only files (verified to keep
both sides where `-X ours` dropped one), plus a guard that refuses to commit any
file carrying conflict markers. Both pinned by `tests/test-hooks.sh`. A merge
`-X ours` cannot settle (a modify/delete) is aborted before the run records
`unresolved-conflict`, so the next run is not refused on unmerged paths; an abort
that itself fails records `merge-abort-failed` (`tests/test-memory-sync-breaker.sh`).

**A per-host circuit breaker stops a wedged store from spawning endless pushes.**
`sync-push.sh` records conflict, staging, commit and push failures as one
`<epoch> <count> <reason>` line in `~/.claude/.sync-push-backoff` (outside every
synced directory). `memory-sync.sh` checks it before all topic gates: the window
starts at 30 minutes, doubles per failure to 24 hours, then admits one claimed
probe; the claim timestamp is the last probe time. Success clears it, and a manual
`sync-push.sh` always runs. An empty-index run stays offline unless HEAD is ahead
of its upstream or backoff exists. Tests override the window and clock with
`CLADE_SYNC_PUSH_BACKOFF_BASE_SECONDS`, `CLADE_SYNC_PUSH_BACKOFF_MAX_SECONDS` and
`CLADE_SYNC_PUSH_BACKOFF_NOW`. `tests/test-memory-sync-breaker.sh` uses temporary
stores and remotes, and mutates every breaker guard.

**Project auto-memory reaches the store only through `sync-link-projects.sh`**
(run by `sync-pull.sh` at every session start). Until 2026-11-06 it never did:
the linker matched projects by basename with `find -name` (so `clade` resolved
to some repository's `.git/clade`), wrote links without the leading `-` Claude
Code's slugs carry, died under `set -e` after its first entry, and never moved a
local memory directory into the store. On the author's main host that left 24
non-empty memory directories, including the one this repository's sessions
load, with no git history. It now scans `~/.claude/projects`,
`$CLAUDE_CONFIG_DIR/projects` and every `~/.claude-profiles/*/projects`, and
adopts a real memory directory into `projects-memory/<key>/` (verified by cksum,
original kept as `memory.pre-sync-<stamp>`). A normalised `origin` at a physical
repository root (not a subdirectory or linked worktree) makes the key `repo-…`:
`.project-remote` holds the identity and `.project-paths` appends one relative
path per hostname and checkout, so every checkout on every machine keeps a link
to the shared memory; stale lines stay because a missing NFS path is not proof
of deletion. Without an origin the old path key and `.project-path` remain.
A local path-keyed entry with an origin is union-copied to the remote entry;
a differing same-name file blocks it, and success leaves the old entry with
`.migrated-to`, preserves its old link beside the new one, and never deletes
store content. The linker prunes wrong links and links each active entry at every
matching slug Claude Code reads. Origin discovery builds one deduplicated index
of candidate roots per run, skipping non-HOME slugs before decoding and checking
the budget between slugs. A partial index still supplies matches; an entry with
no match in an incomplete index is deferred, not called absent. A private project
is skipped in every pass, and a link it already has is replaced by a local copy
without linker metadata. It commits whenever `projects-memory/` has anything
uncommitted, so a commit lost to a killed run or a held lock is made next time.
A store copy that differs is a conflict: written to
`~/.claude/.sync-memory-conflicts`, which `sync-health.sh` prints at session
start, and once a day to `~/.claude/.sync-conflicts.log`. The hook it runs in
times out at 30 s, so adoption and migration defer after
`CLADE_SYNC_LINK_BUDGET` seconds (default 10), discovery stops between slugs,
and the next session resumes.
Run `bash configs/scripts/sync-link-projects.sh --dry-run` to see what it would
do on a machine. Pinned by `tests/test-sync-link-projects.sh` and
`tests/test-sync-link-projects-remote.sh`.

**When asked whether things are synced, check all three.** A clean `git status`
here says nothing about the other two.

## Path-scoped rules — the channel that was wired and empty

`configs/rules/*.md` carry rules that only matter for certain files. Each declares
a `paths:` glob in YAML front matter; `rule-injector.sh` (PostToolUse on Edit|Write
**and Bash**) injects the body **at the moment a matching file is touched**, not at
session start. `install.sh` deploys them to `~/.claude/rules/`; a project may also
carry `.claude/rules/`, which is read first, and any directory under the project
may carry a nested `<dir>/.claude/rules/` whose globs are relative to `<dir>`.

**Until 2026-10-18 it mostly could not fire.** Agents touch files through the
shell: over the author's 40 latest sessions (approximate regex counts), 6,890
Bash reads (`cat`/`head`/`tail`/`sed -n`) against 484 Read calls, and 2,738 Bash
writes against 373 Edit/Write — and the hook was Edit|Write only. On Bash it
now takes path-like tokens of the command that exist as regular files after it
ran (never expanded, glob tokens skipped, at most 40 files), resolving relative
ones after a leading `cd DIR` against DIR. It also walks nested `.claude/rules`
dirs up to the project root, which Claude Code honours natively but the hook
never scanned — skipping third-party trees (`node_modules`, `vendor`, …, judged
on the physical path too, so a symlink into one or out of the project is not
scanned) and any file `claudeMdExcludes` names — and keys its once-per-session
sentinel on `agent_id` too, because subagents share the parent's `session_id`,
so no subagent could get a rule the main thread had.

**One command can match many rules, and Claude Code caps a hook's
`additionalContext` at 10,000 characters**: past that Claude sees a 2,000-character
preview and is not asked to read the rest. So the hook stops adding rule bodies
short of the cap (`CTX_BUDGET`), names the rules it held back, and does not
record them as delivered — they inject on the next matching access. Identical rule text from
two copies (a worktree's checkout of a root rule) is injected once.

**It overlaps the native loader.** Current Claude Code docs say a path-scoped
rule also loads when Claude views a matching file with a single-file `cat` or
`head`, so on those commands a rule can arrive twice. Re-measured on Claude Code
2.1.331 (2026-11-26, the "Retire `rule-injector.sh`" item in `TODO.md`): the native
loader covered 6 of the hook's 1,283 deliveries, so the hook stays, and the
duplicates are too few to pay for a transcript read on every call.

`tests/test-rule-injector.sh` pins all of it, and its last suite removes each
guard from a copy of the hook in turn and requires the suite to go red, beside
a no-op control that must stay green, so CI re-checks that every guard is
observed rather than trusting a one-off mutation run.

This exists because the alternative measurably does not work. A prose rule in a
context file is followed ~64% of the time and decays ~5.6% in odds per function
generated, with no detectable effect from file size or position (arXiv:2605.10039)
— so moving a rule earlier in CLAUDE.md buys nothing, and CLAUDE.md is already 750
lines. The change here is **proximity, not enforcement**: the rule arrives with the
edit it governs. That is a bet, not a measured result, and it should be labelled
that way until the adoption is re-measured.

**It shipped broken and silent.** `install.sh` created `~/.claude/rules` from the
day the hook landed and nothing ever wrote into it. The hook is silent on no-match
by design, so an empty channel and a working one produced identical output — the
same shape as every other instrument this repo has found unable to fire. Pinned now
by four cases in `tests/test-hooks.sh`, including one that fails if `configs/rules/`
is empty and one that fails if a rule file omits `paths:` (without which the hook
ignores it, silently).

A rule file with no `paths:` key is ignored. Keep each short: it is injected into
context, so a long rule is the context bloat it was meant to avoid.

## Settings

Global settings stored at `~/.claude/orchestrator-settings.json`. Defaults defined in `config.py:_SETTINGS_DEFAULTS`. To add a new setting: add to `_SETTINGS_DEFAULTS`, NOT task_queue.py.

## DB Migrations

Add try/except `ALTER TABLE` blocks in `task_schema.py:ensure_schema()`. New columns added to `_ALLOWED_TASK_COLS` in `config.py`. And remove the new column from `LEGACY_SCHEMA` in `orchestrator/tests/test_task_schema_upgrade.py`, so the upgrade-path test actually exercises the migration — on a fresh DB the column is already in the CREATE block and the ALTER can only fail into a bare `except`.

## Commits

```bash
# Always use committer script — NEVER git add .
committer "type: message" file1 file2 file3
```

`committer` runs `.claude/pre-commit.sh` before it commits: the five drift gates,
about one second. They are 26% of this repository's failed CI runs — 7 of the last
27 failed on a drift gate and nothing else, which is a red run and a round trip for
a check that costs a second locally. It is scoped to the five GENERATED surfaces on
purpose; `ci-local.py` remains the gate before a push. A bare `git commit` bypasses
it, which is accepted: `.git/hooks` is not versioned, so a hook there would exist
only on the machine that installed it — the drift this gate exists to catch.

After the commit it pushes, but only to the remote branch with the same name as
the local one (`<remote> HEAD:refs/heads/<branch>`, `-u` when there is no
upstream). A branch tracking another name — `git worktree add -b X <path>
origin/main` makes origin/main the upstream — is committed and not pushed, exit 0;
a detached HEAD likewise. An autonomous worker (`CLADE_WORKER_TASK_ID` set) never
pushes: its runner owns delivery — `run-tasks-parallel.sh` merges each
`batch/task-*` branch locally, `run-tasks.sh` leaves its commits on the current
branch for the caller to push, and `worker.py` gates its own `auto_push` — so the
`-u` path would otherwise publish every unreviewed task branch. Both runners give
each task its own id (`batch-<ts>-<n>`) unless the caller passed one
(`loop-runner.sh`: `loop-iter<N>`). `--no-push` skips
the push; a push git rejects exits 3, never forced. `tests/test-checks.sh` pins
each case against a bare remote.

Conventional commit types: `feat` / `fix` / `refactor` / `test` / `chore` / `docs` / `perf`

## Release Versioning

One base version spans every surface, and until 2026-09-02 nothing said so —
which is how mcp-package sat at 0.2.0 for 241 commits while the plugin manifests
advertised 0.3.1.

`plugins/clade/.codex-plugin/plugin.json` is CANONICAL and hand-maintained.
`regen-cc-plugin.py:canonical_version()` strips the `+codex.<stamp>` build
metadata and writes the base into `.claude-plugin/plugin.json` and
`marketplace.json`, so never hand-edit those two — the drift gate reverts you.
The stamp exists to bust the Codex plugin cache; refresh it whenever generated
plugin content changes.

The same base must appear at five mcp-package sites, none of them generated:

```
mcp-package/pyproject.toml             version = "x.y.z"
mcp-package/server.json                "version"  (twice: server, and the pypi pin)
mcp-package/src/clade_mcp/__init__.py  __version__
mcp-package/src/clade_mcp/server.py    SERVER_VERSION  ← what clients are told
```

Both package READMEs carry it in prose on their first lines as well.
`test_clade_mcp_runtime.py::test_release_version_surfaces_are_aligned` gates all
six: it DERIVES the expected version from `mcp-package/pyproject.toml`, so
cutting a release no longer means editing the gate — that hand-edit was the
failure the gate existed to catch, one level up. It covers the two plugin
manifests as well, comparing the Codex one on the part before its `+codex.`
build metadata.

## CI (GitHub Actions)

Gate before every push with `python3 configs/scripts/ci-local.py` (`--list`
shows what runs here and why; `--json` is for `/green`). It exits 1 on a
failure and 2 when nothing failed but the run is not green (PARTIAL, FLAKY,
NOTHING RAN); `--no-strict` makes that 2 a 0. Every workflow and
gate, why each exists, how to run one by hand, and why stacked PRs get no CI
are in [docs/ci-gates.md](docs/ci-gates.md). A new CI step needs its
explanation there in the same commit; `check-ci-checklist.py` fails otherwise.

## Code Rules

> The general architecture rules (file size, section markers, cohesion, DAG
> imports, CSS extraction) are NOT repeated here. They live once, in the shipped
> template at `configs/CLAUDE.md`, and reach a session through the global
> profile. That is a real deploy gap — working inside this repository they
> arrive by accident of whose machine it is — and the fix is not a seventh copy
> to drift: the two that matter are ENFORCED rather than written down. The
> 1500-line cap is `test_conventions.py`, and the DAG is `check-arch-map.py`
> plus the import graph. Everything below is specific to this repository.

- Keep all files < 1500 lines (Read tool default = 2000 lines)
- No circular imports — module deps must form a strict DAG
- Settings → `config.py:_SETTINGS_DEFAULTS` only
- DB migrations → try/except ALTER TABLE in `task_schema.ensure_schema()`
- Never return `error.message` in 500 responses
- `orchestrator/mcp_server.py` and `mcp-package/src/clade_mcp/server.py` serve an
  asyncio event loop, and the MCP SDK dispatches `tools/call` concurrently. Every
  shellout there must be `asyncio.create_subprocess_*` + `wait_for`, or
  `asyncio.to_thread`; a bare `subprocess.run` freezes every concurrent MCP call
  for the whole timeout.
- Shipped hooks and scripts target bash 3.2 and a BSD userland — macOS is a
  documented platform. Reach for capability detection with a fallback
  (`command -v X`, `stat -c … || stat -f …`), not `uname` branching. A script
  that genuinely needs bash 4 carries the `BASH_VERSINFO` re-exec guard from
  `run-tasks-parallel.sh`. Per-user runtime state goes through
  `configs/hooks/lib/runtime-dir.sh`, never a fixed `/tmp` path.
- If you fan out your own Task-tool subagents within one task: **serialize any
  subagent that writes/builds/runs tests** (they race on the same worktree's
  build artifacts and test state); reads (grep/analysis/research) may run in
  parallel freely. Geoffrey Huntley: uncoordinated parallel writers to shared
  build/test state is a real race, not a hypothetical one.
- **Prefer `pipeline()` to `parallel()` whenever the work has stages, and cut
  more units than you have slots.** Over 285 parallel Workflow runs (4,038
  agents, 394 h, started 2026-09-22 → 10-24 UTC, the author's two profiles;
  `workflow-scorecard.py --ledger-summary --recorded-before 2026-10-24T03:34Z`),
  16.9% of makespan was one agent outliving the siblings it started with, and
  108 of the 285 lost 15% or more that way. That is the time a barrier turns
  into idle slots and a pipeline refills: a pipeline absorbs variance; a
  barrier converts it into idle capacity. (The 110-agent and 10-agent pair this
  bullet cited is historical, measured 2026-09-02 on transcripts since deleted;
  see docs/research/2026-09-02-agent-orchestration-efficiency.md.) When a stage
  genuinely needs every prior result at once (dedup, early-exit on zero,
  "compare against the others"), a barrier is correct — say so in a comment,
  because it is the exception.
- **Size units, or give the queue depth instead.** A fan-out cut by *topic*
  produces units of wildly different length with no way to rebalance, which is
  what leaves one agent running after the rest. You do not need duration
  estimates if there are more units than slots — the queue packs them. That is
  the half of CPU work-stealing that transfers; the migration half does not,
  because an agent cannot be preempted or moved mid-flight.
- **A one-agent stage is not a straggler, and reshaping recovers little of
  it.** It sits on the critical path for its whole length, so shorten the stage
  itself: a tight brief, its own `effort`, waits that keep the subagent cache
  warm, and a return as soon as the artifact the next stage reads is frozen.
  Over 316 runs on the author's two profiles (2026-09-22 → 10-22), one-agent
  stages were a larger sink than stragglers, and waits on external jobs were
  38% of their agent time. Overlapping them instead would have recovered only
  ~9–20 h of 272 h, and 3 of 5 audited "this could overlap" diagnoses were
  refuted by a hidden data dependency. One shape is worth fixing: units that
  each build their own worktree from origin/main go in
  `pipeline(UNITS, implVerify, landBehindMutex)`, not a for-await loop
  (3 of 294 scripts; one run lost ~4–8 h to it). `workflow-scorecard.py`
  reports the two apart since 2026-10-23: `serial` is a lone stage, `outlived`
  a straggler, and only an outlived share is a shape error.
- **The other Workflow script rules live once, in `configs/CLAUDE.md`
  § Adaptive Delegation**, which `install.sh` deploys as the global CLAUDE.md:
  waits that keep the cache warm, nulls counted per stage and returned as a
  resumable result, a deferred launch near the quota cap, a short return with
  the full result in a file, fix rounds inside the script, no AskUserQuestion
  while a run is live, a launch contract before large runs, and a device
  matrix for UI verify. Change them there, not in a copy.
- **Bound a data-dependent stage.** `pipeline(items, find, verify)` where the
  verify stage fans out one agent per finding does not have `items.length`
  agents — it has however many the finders chose to report. Two audits on
  2026-09-12 turned 17 units into 100 and 107 agents that way, past this
  session's own 50-agent guideline, and the width was decided by how much the
  hunters felt like reporting. Sort by severity and `.slice(0, N)` before the
  fan-out, and `log()` what the cap dropped — a silent truncation reads as
  "everything was verified".
- Check the result: `python3 configs/scripts/workflow-scorecard.py --since 7`.
  An `outlived` share of 15% or more means the shape was wrong.

## Auto-Promoted Rules
<!-- Promoted from .claude/corrections/rules.md via /audit. Each rule lists its original recording date. -->

- **Explain mechanisms when summarizing** `[auto-promoted 2026-04-15 from 2026-03-30 summary-vs-explanation]`: When wrapping up a completed task, explain where the feature lives, how it's triggered, and what it produces — not just bullet-point outcomes. The user needs the "how" to trust and actually use the feature.

- **Processing external research into Clade** `[auto-promoted 2026-04-15 from 2026-03-31 research cluster × 5]`: When evaluating research on other tools/patterns (landscape docs, competitor analysis), don't mark anything `needs_work` without first: (1) verifying Clade's existing approach is demonstrably *deficient*, not just *different*; (2) comparing actual capabilities, not names (Ralph ≈ /loop — same supervisor-loop pattern, not a gap); (3) confirming the pattern applies to Clade's single-tool scope (Universal Hook Injection targets multi-tool orchestration — N/A here); (4) checking mechanism equivalence before claiming parity (`session-context.sh` ≠ Pi's `before_agent_start` hook — one is a shell script, the other fires between user message and agent `prompt()`). Once a gap IS confirmed, immediately modify code and verify — "plan changes" means "modify code, then verify", not "write TODO".

- **SVG → PNG export** `[auto-promoted 2026-04-15 from 2026-04-01 svg-rendering]`: Use `rsvg-convert`, not ImageMagick — ImageMagick mangles gradients, filters, and low-opacity elements. Also: strip unused `<defs>`, use Linux-available fonts (Helvetica/Arial, not `-apple-system`), and keep opacity ≥ 0.15 for visibility.

- **Domain-specific diagram conventions** `[auto-promoted 2026-04-15 from 2026-04-01 svg-diagram-accuracy]`: Before drawing a domain-specific diagram (cladogram, flowchart, architecture), research the type's established visual conventions. A cladogram uses right-angle bifurcating branches (horizontal + vertical lines), NOT radial/diagonal lines from a center point. Match the established visual language of the diagram type.
- [2026-04-11] config-tracking (deploy-gap): When adding a new ~/.claude/ config file, immediately check if configs/ tracks it and install.sh deploys it — not end with "want me to add it?". Should have run `diff ~/.claude/CLAUDE.md configs/CLAUDE.md` before asking. [auto-promoted 2026-05-11]
- [2026-04-12] prompt-hook-verbosity (settings-disconnect): Always add statusMessage to type:prompt hooks — without it Claude Code displays the full prompt text in the UI, blocking content. Should have noticed the missing statusMessage when writing the hook. [auto-promoted 2026-05-11]
- [2026-04-15] stop-hook-scope (edge-case): Stop-hook cleanliness checks must be session-scoped (baseline at SessionStart, diff at Stop), not repo-global — parallel CC sessions on the same repo cause deadlock when one session's dirt blocks another session's stop. Always pair a blocking Stop hook with an `stop_hook_active`+attempt-counter circuit breaker to escape LLM loops. [auto-promoted 2026-05-11]
- [2026-04-19] stop-hook-ack-loop (async-race): When a Stop hook blocks awaiting user input and the user hasn't replied yet, STOP GENERATING after ONE acknowledgment — every subsequent "等待授权"/"waiting" reply counts as a new turn, re-fires the Stop hook, and creates a response→hook→response cycle that burns tokens until ctrl-C. Circuit-breaker in the hook is defense #1 (see 2026-04-15), my own silence is defense #2 — if the same hook reason fires twice in a row with no user message in between, the next message MUST be the last until the user speaks. [auto-promoted 2026-05-11]
- [2026-04-20] upstream-design (edge-case): When designing an "absorb from external" system, scope the input space BEFORE the mechanics — (a) one upstream owner often ships many repos/clusters, so enumerate the full set, not just the one you first noticed; (b) the trust/review model (blind-sync vs curate-first) is the architectural spine, not a detail. Ask the user "what's your trust level per upstream?" before proposing file-diff logic. Should have fetched AgriciDaniel's profile on first mention of claude-seo instead of treating it as one isolated repo. [auto-promoted 2026-05-11]
- [2026-05-06] design-scope (edge-case): When designing a learning/automation/observability feature, default to ~/.claude/ universal scope unless the value is genuinely repo-local — not bake it into the project you happen to be sitting in. Cross-project applicability is the input dimension I keep missing: dotfiles deploy is global, memory-sync is global, hooks are global, so "learn from commits" should be too. Should have asked "does this live in ~/.claude/ or in <project>/?" before drafting architecture. [auto-promoted 2026-05-25]
- [2026-05-06] topic-pivot (edge-case): When the user's next message is in a domain with zero overlap with current conversation (e.g. commit-archeology → trial pricing strategy in a project with no pricing), ONE-line confirm scope before investing in investigation — wrong-session / mis-pasted prompts are a real failure mode. The 5-second "wait, is this for this repo?" check saves a 10-minute scan of a project that doesn't have the topic at all. [auto-promoted 2026-05-25]
- [2026-05-07] reduction-recommendation (deploy-gap): Before recommending "remove/disable X" to fix bloat, verify (a) X is actually running, (b) what value X provides beyond the immediate context, (c) whether the bloat is from X itself or from X-being-loaded-in-the-wrong-place. Recommended killing the clade MCP server to fix "95 skill descriptions dropped" without checking it was actively running, what external tools depend on it, or that the real issue was Claude-Code-as-MCP-client double-loading skills. Should have run `ps aux | grep mcp` and read the .mcp.json before proposing the cut. [auto-promoted 2026-05-25]
- [2026-07-14] codex-plugin-dev (deploy-gap): When iterating on a locally-installed Codex/CC plugin that ships hooks, warn up front that each hook-file change forces a "hooks need review" re-trust prompt and point to the dev bypass (`--dangerously-bypass-hook-trust`, global + DANGEROUS) — instead of leaving the user to hit the recurring nag and ask why their own edits aren't trusted. [auto-promoted 2026-09-01]
- [2026-08-10] own-tooling (settings-disconnect): When my own tooling fails mid-task and I work around it with a flag, fix the tool in the same pass — raise the bad default AND surface the escape hatch — instead of reporting the gap and asking for direction. `loop-runner.sh` defaulted the supervisor planning budget to 120s and blew it twice (its own comment recorded the earlier incident), yet `--supervisor-timeout` was never listed in `print_usage`, so the "workaround" was undiscoverable and the default was never revisited. A flag nobody can find is not a mitigation. Corollary: a source file sitting exactly at the 1500-line ceiling is a blocked file — split it (CLAUDE.md prescribes this) rather than trimming the fix to fit or reaching for LINE_LIMIT_EXCEPTIONS, which is for upstream-synced code only. [auto-promoted 2026-09-01]
- [2026-08-15] response-length (constraint-violation): Match answer length to the question's size even during sustained analytical work — a three-part question deserves a three-part answer, not another six-section report with tables. Signal I missed: the user surfaced an ELI5 output style ("short sentences, short paragraphs, 2 options max, only what's necessary") immediately after six consecutive long structured reports; that is feedback on register, not a research request. The existing global rule only covers colloquial/venting messages, so I read "they're still asking analytical questions" as license to keep expanding. Catch it by checking whether the LAST answer was long before writing the next one, not by waiting for the register to change. [auto-promoted 2026-09-01]
- [2026-08-16] verification-reporting (inaccurate-self-reporting): Read the WHOLE result before drawing a conclusion from it, and run every suite the gate runs — not a `tail -4` snapshot or the subset I remember. Twice in one session I turned partial evidence into a completion claim: a mid-stream "7 passed, 5 failed" counter caught by `tail -4` (the real result was 187/187), and two red CI runs from skipping pytest and test-checks.sh locally. Both are exactly arXiv:2605.29442's S7, 22.58% of real-world agent failures and growing. Catch it by asking "is this output complete?" before "what does this output mean?". [auto-promoted 2026-09-01]
- [2026-08-30] review-outcomes (inaccurate-self-reporting): When a review/audit ends with "I deliberately did NOT do X", write X into TODO.md/PROGRESS.md in the SAME turn before reporting done — not state the deferral only in chat (repeated 03efd77's exact defect one day later; the code was all merged, but nothing on disk mentioned the review or its two deferred decisions) [auto-promoted 2026-09-17]
- [2026-09-02] branch-delivery (constraint-violation): Push a feature branch and open its PR as soon as the work is coherent, and re-push after each later batch — never accumulate local commits and report "N commits, not pushed" as if withholding were the safe default. The global "ask before `git push`" rule covers SHARED/PROTECTED branches only; a `docs/`-prefixed feature branch on an unprotected `main` is neither, and treating it as such stranded 36 commits where the owner could not see or review them. Catch it by asking "can the owner reach this work right now?" at every commit, not at the end. [auto-promoted 2026-09-17]
- [2026-09-02] standing-preferences (settings-disconnect): When the owner repeatedly hand-types the same long brief (artifact/report angles, diagram professionalism, "no detail omitted", who-works-on-what, gap-to-goal, failed attempts), encode those angles as a SKILL in configs/skills/ so the next invocation carries them by default — not answer the current instance well and leave the next one dependent on them typing it again. Their words for it: "与其在疯狂说，还不如直接在我们这个Clade项目里面配置好". [auto-promoted 2026-09-17]
- [2026-09-02] ci-cost (standing-preference): Hosted CI is billed per job, rounded up per job, Linux 1x / Windows 2x / macOS 10x — so run the gates locally with `ci-local.py` and drive them green with `/green`; the policy lives in `configs/CLAUDE.md` "## CI — run it on hardware you already own" and the machine mapping in the private `~/.claude/CLAUDE.md`. Not: re-deriving the argument each time it comes up, which is what happened when a promoted rule cited "the ci-cost rule above" that had never been written. [auto-promoted 2026-09-17]
