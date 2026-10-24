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

## What This Project Is

A multi-surface coding automation toolkit:

- **CLI layer** (`configs/`) — skills, hooks, scripts installed via `./install.sh`
- **Codex plugin** (`plugins/clade/`) — 30 generated native skills plus Codex hooks, distributed by `.agents/plugins/marketplace.json`
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
# Measured across 89 parallel runs on this account (1777 agents, 49.9h): 45% of
# all makespan was spent with exactly ONE agent still running, and 55 of the 89
# had a tail over 15%. The shape matters more than the agent count — a
# 110-agent pipeline() scored 80% utilisation with a 0% tail, while a 10-agent
# parallel() barrier scored 55% with 19%.
python3 configs/scripts/workflow-scorecard.py --project Clade --since 7
python3 configs/scripts/workflow-scorecard.py --since 0 --json   # all runs, machine-readable

# Did a Codex worker actually delegate? `codex exec` CAN subdivide — measured
# 2026-09-05, the gate is the resolved model's catalog multi_agent_version, not
# the session source. This counts the children, and its self-test distinguishes
# a real zero from an unreadable state file.
python3 configs/scripts/workflow-scorecard.py --codex-children

# Native Codex plugin — regenerate after changing a shipped canonical skill
python3 configs/scripts/regen-codex-plugin.py
python3 configs/scripts/regen-codex-plugin.py --check
```

## Architecture — Surfaces and Layers

### CLI Layer (`configs/`)
- `skills/` — skill prompts invoked via `/skill-name` in Claude Code
- `hooks/` — pre/post hooks for Claude Code events (wired via `settings-hooks.json`)
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

**Per-attempt checkpoints** (separate from the correction pipeline above): `worker-checkpoint.sh` (PostToolUse **Edit|Write and Bash**, async) commits the whole worktree into a shadow repo OUTSIDE it, once per agent write. Until 2026-09-16 it was wired to Edit|Write only AND gated on a non-empty `tool_input.file_path`, so it was blind to a `python - <<EOF` heredoc — the one failure mode Ronacher's unattended run actually named. The path was only ever a commit-message label; the snapshot is `add -A`. In the same pass it stopped being inert on the terminal path: its only setter had been `orchestrator/worker.py`, in the layer `docs/layers.json` marks dormant, so the half of the system actually in use kept no checkpoints at all. `run-tasks-parallel.sh` now exports `CLADE_WORKER_SHADOW_DIR` per task. A worker commits exactly once — at the end of verification — and `stop()` force-removes the worktree, so "correct at call 14, wrong at 15" had no record. A separate `--git-dir` means a separate index, so checkpoints cannot contend with the worker's own commits (measured, see `tests/test-hooks.sh`). The final SHA and count land in the evidence bundle before cleanup deletes the repo. Setting: `worker_checkpoint_shadow`.
- `revert-detector.sh` (PreToolUse Bash, async) on `git revert/reset/restore` cross-refs that shadow **against the command's own pathspec** → writes `reverted_files` (the intersection), `session_files` (the loose session list, under its true name), `revert_scope`, `revert_paths` and `repeat` into `~/.claude/corrections/history.jsonl`. `repeat` is meaningful only when `revert_scope` is `paths`: `git revert` takes no pathspec, `git reset --hard` cannot take one, and the hook is async, so for those the file set is not knowable at hook time — `reverted_files` is `[]` and `repeat` is `null`. Records written before 2026-09 carry the old semantics. `revert_scope:"probe"` marks a command that puts back what it reverted (`git apply`/`git stash pop` after the revert), edits the very path it reverts (`sed -i`, `python3 - "$f" <<'EOF'` — the dominant shape: 62 of the 115 implicit-revert records on the author's machine 2026-10-05 → 10-12, by a Python replay of the rule, none labelled), or carries the `MUTATION` label agents print — the mutation test the global CLAUDE.md requires, not a rejection — so it carries no `reverted_files`, no `session_files` and a null `repeat` (seven such records on 2026-09-23 had been feeding correction-detector false "files behind this correction"). `project` is the `cd` that runs BEFORE the revert, with `~` and variables the command itself assigns resolved; an unresolvable `$VAR` falls back to the session directory rather than being filed as a literal `$WT`. Heredoc bodies are stripped before any of this parsing, because agents write files through `python3 - <<'EOF'` and prose about git in the body used to trigger the hook and pick its project. Only the persisted `prompt` keeps the raw command. Only the main thread writes: a call whose hook input carries `agent_id` (a subagent) or that runs under `CLADE_WORKER_TASK_ID` (a dispatched worker) records nothing. Of the 220 implicit-revert records on the author's machine 2026-09-22 → 10-22, 172 were issued by Workflow subagents inside their own runs, and every reader — `session-scorecard.sh`, the concrete-signal block of `correction-detector.sh`, `repeat`, radar Lane C — counted them as the owner rejecting a change; skipping rather than tagging keeps all of them correct without a new filter.
- `correction-detector.sh` (UserPromptSubmit, **sync**) on an explicit "that's wrong" surfaces those rejected files into the rule-extraction context. Silent when `CLADE_WORKER_TASK_ID` is set: a dispatched worker's brief is its only "user prompt", reads like a correction ("fix any…", "instead of", "不要"), and was being persisted as one per retry — 13 of the 72 explicit records `~/.claude/corrections/history.jsonl` holds for 2026-09-07 → 2026-09-21 on the author's machine. A `对不对` tag question ("…, right?") no longer fires; a real 不对 beside another 对 (绝对不对, 不对不对, a tag running into 不对) is split off first, so it still does. On 364 hand-labelled owner messages typed after Workflow runs (37 rejections) the strip takes precision from 41% to 57% at unchanged recall (35%), and on the 490 other main-thread messages the owner typed on the same machine 2026-08-26 → 10-23 all 5 fires it removed were tag questions. Eight rejection phrasings were added too (不太对, 理解错, 没懂, 不满意, 打不开, 做多了, 四不像, 说的/得太多), but only in-sample: they lift the labelled replay to 66% precision and 51% recall because they were read off that set's misses, they caught no rejection among the 490 (one non-rejection fire), and four of them — 理解错, 做多了, 四不像, 说得太多 — are never a message's only trigger, so they are unmeasured
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

> **The GUI is not in use.** The owner works entirely in the terminal; the
> FastAPI server, its React UI and the worker-pool / task-queue / routing /
> evidence stack behind them are deliberately dormant. It may be rebuilt, so
> nothing here is deleted and CI keeps it green — but this is **not**
> load-bearing code, and a finding here does not weigh the same as one on the
> terminal path (`configs/` skills, hooks, scripts, and the Codex plugin).
>
> The measurable consequence, and the reason this note exists: no `tasks.db` on
> the author's host carries the current schema and no evidence store exists, so
> every number this repository has about worker parallelism actually comes from
> Claude Code's own Workflow/subagent layer — which this orchestrator does not
> control. Auditing an unrun system as if it were load-bearing is how effort
> gets spent on a control that never applies.

Key modules (import DAG — leaf → root):

```
# Leaves (no project imports)
config.py            ← constants, settings, utilities
agent_runtime.py     ← agent-runtime ids + fail-closed validation
cascade_policy.py    ← pure verifier-aware cheap→strong eligibility, lineage, and signal helpers
fault_localize.py    ← multi-language SBFL: test-runner detection, go/js failure parsers, cross-lang symbol index (stdlib-only leaf; worker_tldr imports it)
agent_output.py      ← stdlib-only contract for reading a spawned agent's own usage report (stream-json/json → cost, tokens, per-model usage, prose projection)
pytest_report.py     ← stdlib-only pytest-output contract: colour-proof result parsing, verbosity normalization, colour-free subprocess env (shared by worker_utils, worker_tldr, evals/)
ideas.py             ← IdeasManager, async idea CRUD
process_manager.py   ← ProcessPool, start.sh lifecycle
repo_map.py          ← deterministic repository-structure analysis: AST/tree-sitter TLDR, entity pruning, PageRank centrality. Pure and synchronous — no LLM call, no subprocess, no DB (imports fault_localize)
worker_tldr.py       ← task-specific localization, fault location, SBFL, repro-test generation, scoring — the half that spends money (imports repo_map, fault_localize)
worker_review.py     ← oracle + PR review
worker_utils.py      ← output helpers, lint reflection, LoopDetectionService, worker-state helpers
worker_hydrate.py    ← _pre_hydrate (GitHub issue/PR pre-hydration)
condensers.py        ← Condenser ABC + implementations
api_auth.py          ← stdlib-only bearer-token guard for the control plane (ASGI middleware, so it covers websockets too) + settings-secret masking
runtime_redaction.py ← stdlib-only secret/path redaction before persistence
evidence_bundle.py   ← versioned immutable attempt evidence + digest-chain contract
event_stream.py      ← crash-safe JSONL event logging
tracing.py           ← TracingService, task spans
reactions.py         ← ReactionExecutor
error_classifier.py  ← error classify/summarize + retry decisions
session_tree.py      ← SessionTree
usage_tracker.py     ← multi-machine ccusage ingestion (used by routes/usage.py)
execution_envelope.py ← versioned immutable execution contract (runtime/provider/protocol/model split)
worker_envelope.py   ← versioned terminal contract emitted by workers
handoff_registry.py  ← typed worker-handoff schemas + prompt-safe projections
reset_handoff.py     ← compact typed context seeds for clean loop resets
run_contract.py      ← repository-owned autonomous-run policy (optional CLADE_WORKFLOW.md)
run_budget.py        ← pure run-budget policy + trace attribution
merge_policy.py      ← truthful pull-request history selection
judge_diversity.py   ← deterministic review checks independent of the LLM oracle, plus 9 test-integrity signals (counted from the diff, fed to the oracle, never an auto-fail); scored by evals/run_hack_eval.py — 100% recall / 6.2% false alarms on a 34-case adversarial corpus
status_snapshot.py   ← provider-neutral status truth rendered by surface adapters
worker_phase_graph.py ← declared worker/task/loop lifecycle graph (additive observability)
worker_sandbox.py    ← stdlib-only Landlock confinement: makes the shared .git/hooks and .git/config unwritable to a worker (default off)
compatibility_telemetry.py ← secret-free compatibility-window counters
webhook_trust.py     ← fail-closed actor authorisation for GitHub webhook events (payload-only; no API call to fail open on)
eval_candidates.py   ← validated identifiers + digests for quarantined eval candidates
eval_metrics.py      ← read-only, denominator-explicit evidence/eval quality metrics
    ↑
# Mid-tier
github_sync.py       ← gh CLI wrappers (issues, push, sync)
task_schema.py       ← tasks.db DDL: table creation + additive ALTER migrations (leaf; task_queue imports it)
task_queue.py        ← SQLite tasks + append-only evidence persistence
routing_break_even.py ← production-only observational routing analytics
swarm.py             ← SwarmManager (extracted from worker.py)
worker_pool.py       ← WorkerPool: which workers exist and polling them (extracted from worker.py; re-exported there, bound to that module's Worker)
worker_taskfile.py   ← build_task_file: task file construction + context injection
worker_runtime.py    ← runtime-route resolution + durable selection failure
worker_evidence.py   ← attempt lifecycle + worker/verifier/delivery evidence projection
attempt_telemetry.py ← pure attempt-level routing/phase telemetry builders (imports cascade_policy)
provider_registry.py ← secret-safe live model discovery, TTL cache, pinned fallback
worker_routing.py    ← pure route decision: runtime, model, effort, audit reason
worker_provider.py   ← WHICH agent CLI a worker runs (claude vs codex command + env)
execution_backend.py ← HOW a worker process is spawned/torn down (lazy config import)
execution_resolver.py ← route + provider → immutable execution envelope
worker_status.py     ← worker status serialization kept out of the execution engine
eval_review.py       ← human review + atomic corpus promotion for eval candidates
eval_review_cli.py   ← standalone CLI to promote/reject quarantined eval candidates
    ↑
worker.py            ← Worker, WorkerPool — core execution engine
session.py           ← ProjectSession, registry, status_loop (lazy-imports task_factory/)
    ↑
# Roots
server.py            ← FastAPI app, remaining routes, mounts all routes/* routers
mcp_server.py        ← standalone MCP entrypoint exposing skills (stdio transport)
oracle_cli.py        ← standalone oracle gate CLI (strangler extraction; shim configs/scripts/oracle-review.sh)
routes/tasks.py      ← Task CRUD + bulk-action routes
routes/workers.py    ← Worker control + inspection routes
routes/webhooks.py   ← GitHub webhook handler
routes/ideas.py      ← Ideas API routes (CRUD, evaluate, execute, promote)
routes/process.py    ← Process manager API routes
routes/usage.py      ← Usage dashboard API routes
routes/evals.py      ← Human-review routes for quarantined eval candidates
routes/providers.py  ← Secret-safe provider/model registry inspection + refresh
```

Every `orchestrator/*.py` and `orchestrator/routes/*.py` must appear above —
CI's "Architecture map coverage" gate fails on any module missing from this file.

`orchestrator/task_factory/` is excluded from that gate by `check-arch-map.py`'s
`SKIP_DIRS`, so its four modules are listed here for the reader rather than
enforced. All four are lazy-imported from `session.py`:

```
ci_watcher.py     ← failed GitHub Actions run → task
coverage_scan.py  ← coverage gap → task
dep_update.py     ← outdated dependency → task
mutation_scan.py  ← surviving mutant → task
```

### Key File Map
| File | Purpose |
|------|---------|
| `config.py` | `GLOBAL_SETTINGS`, `_ALLOWED_TASK_COLS`, model aliases, cost utils |
| `agent_runtime.py` | Agent-runtime identity and fail-closed selection shared by routing/settings/factory |
| `cascade_policy.py` | Pure default-off verifier-cascade policy, escalation signals, and retry contract projection |
| `evidence_bundle.py` | Immutable `clade.evidence/v1` snapshots, lifecycle validation, and digest-chain verification |
| `task_schema.py` | `ensure_schema` — every CREATE TABLE and additive migration for tasks.db, split out of `task_queue._ensure_db` |
| `task_queue.py` | SQLite CRUD for tasks, loops, messages, interventions, and append-only attempt evidence |
| `routing_break_even.py` | Read-only production EvidenceBundle aggregation for observational routing break-even metrics |
| `worker.py` | `Worker`, `WorkerPool` — core execution engine |
| `swarm.py` | `SwarmManager` (extracted from worker.py; re-exported there) |
| `worker_pool.py` | `WorkerPool` — worker scheduling and polling. `worker.py` subclasses it to bind its own `Worker`, which keeps privately-loaded test copies private |
| `worker_taskfile.py` | `build_task_file` — task file construction + context injection |
| `worker_runtime.py` | Runtime route resolution and fail-closed task outcome persistence |
| `worker_sandbox.py` | Landlock ruleset that PREVENTS the git control-surface escape `worker_git_surface_guard` only detects (`worker_sandbox`, default off) |
| `worker_evidence.py` | Evidence attempt lifecycle, Git/test/oracle/cost/artifact projection, and terminal delivery candidate |
| `repo_map.py` | `_generate_code_tldr`, `_pagerank_centrality`, `_keyword_filter_tldr` — builds the map of a repository. Split out of `worker_tldr.py` at 1459 of the 1500-line ceiling; the boundary is "map the repo" vs "narrow that map to a task", and the purity of this half is what the split buys |
| `worker_tldr.py` | `_localize_tldr_for_task`, `_localize_fault`, `_sbfl_prepass`, `_score_task` — narrows the map for one task |
| `agent_output.py` | `parse_agent_output` / `absorb_agent_result` — the agent's self-reported `total_cost_usd` and usage, and the prose projection every log consumer reads (leaf) |
| `pytest_report.py` | `parse_results` / `force_verbose` / `color_free_env` — the one definition of how pytest output is read back (leaf) |
| `worker_review.py` | `_write_pr_review`, `_oracle_review`, `_write_progress_entry` (leaf) |
| `oracle_cli.py` | Standalone oracle gate — same judge as the orchestrator, no server needed (`oracle-review.sh` shim; opt-in `/commit` gate via `CLADE_ORACLE_GATE=1`) |
| `worker_utils.py` | Output helpers, lint reflection, `LoopDetectionService`, worker-state helpers (leaf) |
| `session.py` | `ProjectSession`, `SessionRegistry`, `status_loop()` |
| `server.py` | FastAPI app, session/loop/swarm/usage/settings routes, WebSocket |
| `github_sync.py` | GitHub issue create/update/pull/push via `gh` CLI |
| `ideas.py` | `IdeasManager` — async idea CRUD, AI evaluation, promotion |
| `process_manager.py` | `ProcessPool`, `StartProcess` — start.sh lifecycle control |
| `usage_tracker.py` | Multi-machine ccusage ingestion (`~/.claude/orchestrator/usage.db`) |
| `routes/tasks.py` | Task CRUD, bulk actions, and on-demand verified evidence attempts |
| `routes/workers.py` | Worker control + inspection routes (10 handlers) |
| `routes/ideas.py` | Ideas API routes (CRUD, evaluate, execute, promote) |
| `webhook_trust.py` | `is_trusted_actor` — a signature proves the event came from GitHub, not that its author may direct a permission-bypassed worker |
| `api_auth.py` | `TokenAuthMiddleware` — default-closed authorisation for all 93 routes and both websockets. Middleware, not per-route `Depends`, because the next route added would silently forget the dependency and because `BaseHTTPMiddleware` never sees a websocket scope |
| `routes/usage.py` | Usage dashboard API routes |
| `web/src/` | Vite + React + TypeScript UI source (App.tsx, components/, stores/, hooks/, lib/) |
| `web/index.html` | Vite *source* shell (`<div id="root">` + main.tsx) — the build entry, never served. It loads `/src/main.tsx`, which no browser executes. |
| `web/usage.html` | Standalone usage dashboard. Served by an explicit route registered BEFORE the `/web` mount — `vite.config.ts` declares no `publicDir`, so the build never copies it into `dist/` and the mount alone 404s it on every machine that built. |

## The dotfiles sync store — a THIRD remote, and it was eating data

`~/.claude/{skills,hooks,scripts,corrections}` can be symlinks into a sync store
(`~/.claude/.sync-config` → `SYNC_DIR`) that is **its own git repository with its
own GitHub remote**. So "everything is pushed" has three answers, not one: this
repo's `origin`, the machines in `~/.claude/fleet.conf`, and that store. Nothing
said so, which is how the next defect went unseen for months.

`sync-push.sh` ran `git pull --rebase --autostash` and, on conflict,
`git merge -X ours`. Two failures compounded:

- The **autostash pop** (not the rebase) writes `         quiet-run scan-health pre-tool-guardian ask-while-live loop-args \
         memory-watchdog ci-local seo-geo radar-cron workflow-preflight; do
  bash "tests/test-$t.sh" >/dev/null || echo "FAILED: $t"
done

# 13. The install-test job (its own CI job, not part of shell-tests)
bash tests/test-install.sh

# 14. Plugin manifest validator + component resolution (separate workflow;
#     both need the claude CLI). --strict checks the manifest against a schema
#     and is blind to a schema-valid manifest that resolves nothing, which is
#     what this repo shipped: 37 agent paths loading as Agents (0).
claude plugin validate . --strict
bash configs/scripts/check-cc-plugin-components.sh

# 15. This list is a superset of CI — enforced, not merely asserted. It had
#     drifted twice (df802c3, then again by 2026-08-29) because the only thing
#     holding it was the sentence below telling you to keep it in sync.
python3 configs/scripts/check-ci-checklist.py
```

**Anything under `configs/scripts/` that CI runs in `syntax-check` must be
stdlib-only.** That job installs no project dependencies — it sets up Python and
goes straight to the gates. A gate that imports `orchestrator/config.py` pulls in
`aiosqlite` and dies there while passing on a developer machine that happens to
have it installed system-wide, which is exactly how the settings-reference gate
failed its first CI run after a clean local sweep. Parse what you need
(`ast.literal_eval`) rather than importing the module.

`tests/test-loop.sh` additionally asserts that the deployed
`~/.claude/scripts/loop-runner.sh` matches source. A stale local install fails
it with no repository defect — the fix is `./install.sh`, not a code change.

This checklist drifted twice before anything watched it: 4 of 7 gates until
2026-08-22 (`df802c3`), then 7 of 11 `syntax-check` gates and 0 of 17 shell
suites until 2026-08-29. `check-ci-checklist.py` (item 15) now enforces the
superset and runs in CI, and `ci-local.py` runs the gates so nobody has to
re-type them. **When you add a CI step, add its explanation here in the same
commit.** The gate catches a forgotten entry as long as the new step invokes
something `ARTEFACT_PATTERNS` already recognises, or lands in `syntax-check` or
`shell-tests`, whose step counts it also compares. A step running a tool no
pattern names is invisible to it — the gate's own documented blind spot
(`check-ci-checklist.py:67-74`), which fired the day the ruff step landed. **A
new KIND of gate therefore needs its pattern added to that script in the same
commit too.**

On push/PR to `main`, four workflow files fire:

- `ci.yml` — `syntax-check` (24 gates), `pytest` (suite + 2 offline evals),
  `shell-tests` (24 suites), `install-test`. `run_hack_eval.py` scores
  `judge_diversity.test_integrity` against the labelled reward-hack corpus in
  `evals/hack_cases/` — read its README before changing either, because that
  gate's floor and ceiling are measured, not chosen.
- `validate-plugin.yml` — `claude plugin validate . --strict` against the real
  plugin loader rather than a hand-rolled schema that would drift from it.
- `pr-honeypot-check.yml` — flags a PR body that echoes the `AGENTS.md`
  compliance token verbatim. An informational comment, never a block.
- `vouch-gate.yml` — closes issues and PRs opened by untrusted authors.

Three `ci.yml` jobs are key-gated and skip cleanly without credentials:
`real-api-loop` (workflow_dispatch or the weekly schedule — one live claude CLI
loop scenario, roughly $0.05, via `bash tests/test-loop.sh --real`),
`provider-live-anthropic`, and `provider-live-openai` (read-only catalog
smokes).

### Stacked PRs get no CI

Both `ci.yml` and `validate-plugin.yml` filter on `pull_request: branches:
[main]`, so a PR whose base is another feature branch runs only the honeypot
and vouch gates — the two that trigger on `pull_request_target` with no branch
filter. Retargeting such a PR to `main` does not help on its own either: a base
change emits `edited`, which is not one of `pull_request`'s default trigger
types. Close and reopen the PR (or push to its head) to get a real run, and
confirm the check list actually grew before reading green as evidence.

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
  more units than you have slots.** Measured across 89 parallel Workflow runs on
  this account (1777 agents, 49.9h), 45% of all makespan was spent with exactly
  ONE agent still running. The shape decides that, not the agent count: this
  repository's 110-agent `pipeline()` finished with a **0%** single-agent tail at
  80% utilisation *despite* its slowest agent taking 6.9x the median, while a
  10-agent `parallel()` barrier with a far narrower 2.0x spread wasted 19% of its
  makespan. A pipeline absorbs variance; a barrier converts it into idle
  capacity. When a stage genuinely needs every prior result at once (dedup,
  early-exit on zero, "compare against the others"), a barrier is correct — say
  so in a comment, because it is the exception.
- **Size units, or give the queue depth instead.** A fan-out cut by *topic*
  produces units of wildly different length with no way to rebalance, which is
  what produced that 2.0x. You do not need duration estimates if there are more
  units than slots — the queue packs them. That is the half of CPU work-stealing
  that transfers; the migration half does not, because an agent cannot be
  preempted or moved mid-flight.
- **A one-agent stage is not a straggler, and reshaping recovers little of
  it.** It sits on the critical path for its whole length, so shorten the stage
  itself: a tight brief, its own `effort`, waits that keep the subagent cache
  warm, and a return as soon as the artifact the next stage reads is frozen.
  Over 316 runs on one account (2026-09-22 → 10-22), one-agent stages were a
  larger sink than stragglers, and waits on external jobs were 38% of their
  agent time. Overlapping them instead would have recovered only ~9–20 h of
  272 h, and 3 of 5 audited "this could overlap" diagnoses were refuted by a
  hidden data dependency. One shape is worth fixing: units that each build
  their own worktree from origin/main go in
  `pipeline(UNITS, implVerify, landBehindMutex)`, not a for-await loop
  (3 of 294 scripts; one run lost ~4–8 h to it). Until `workflow-scorecard.py`
  separates serial from outlived time, its tail counts a lone stage too, so a
  tail over 15% on a serial-dominated run is not by itself a shape error.
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
  A tail over 15% means the shape was wrong.

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
